import csv
import logging
import os
from itertools import product
from typing import Dict, List, Set, Any, Tuple, Callable

import requests
from scripts.library.util.casing import apply_contract_casing
from scripts.morphological_analysis.process_morpheys_perseids_api_aux.overrides import (
    FORMS, NOT_WANTED_INFLECTIONS, FULL_OVERRIDES, ANALYSIS_ALIASES, FORMS_TO_IGNORE, IGNORED_DICT_REFS,
    DICT_REF_REPLACEMENTS, TRUE_ADVERB_FORMS
)


def _merge_bodies(analysis_lower: Dict, analysis_title: Dict) -> List[Dict]:
    """Merge Body entries from lowercase + Title-case queries. The API is now
    strict-case, so proper-noun-only entries (e.g. 'Athena') never surface
    under a lowercase query. Dedupes by headword; lowercase-sourced bodies
    come first so existing FORMS/FORMS_TO_IGNORE indices stay stable."""
    def get_bodies(analysis):
        if not analysis or "RDF" not in analysis or "Body" not in analysis["RDF"]["Annotation"]:
            return []
        bodies = analysis["RDF"]["Annotation"]["Body"]
        return bodies if isinstance(bodies, list) else [bodies]

    seen = set()
    merged = []
    for body in get_bodies(analysis_lower) + get_bodies(analysis_title):
        try:
            headword = body["rest"]["entry"]["dict"]["hdwd"]["$"]
        except KeyError:
            merged.append(body)
            continue
        if headword in seen:
            continue
        seen.add(headword)
        merged.append(body)
    return merged


class MorphologicalAnalyzer:
    MACRON_MAP = {
        "a_": "ā",
        "e_": "ē",
        "i_": "ī",
        "o_": "ō",
        "u_": "ū",
        "A_": "Ā",
        "E_": "Ē",
        "I_": "Ī",
        "O_": "Ō",
        "U_": "Ū",
    }

    # List of Latin enclitics, sorted by length descending to match longer ones first (e.g., "cumque" before "que")
    ENCLITICS = sorted([
        "que", "ne", "ve", "ue", "vis", "piam", "dem", "dum",
    ], key=len, reverse=True)


    def __init__(self, project_root: str):
        self.project_root = project_root
        self.input_file = os.path.join(
            project_root, "output", "library", "work_contents.csv"
        )
        self.output_dir = os.path.join(project_root, "output", "morphological_analysis")
        self.details_file = os.path.join(self.output_dir, "morphological_details.csv")
        self.inflections_file = os.path.join(
            self.output_dir, "morphological_detail_inflections.csv"
        )
        self.processed_forms: Set[str] = set()
        self.unique_words: Set[str] = set()

        # Setup logging
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )

        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)

        # Load existing processed forms
        self.load_existing_forms()
        # Collect unique words from source
        self.collect_unique_words()

    @staticmethod
    def macronize(text: str) -> str:
        """Convert underscore notation to macrons"""
        if not text:
            return text
        result = text
        for underscore_vowel, macron_vowel in MorphologicalAnalyzer.MACRON_MAP.items():
            result = result.replace(underscore_vowel, macron_vowel)
        return result

    def load_existing_forms(self):
        """Load already processed forms from existing morphological_details.csv"""
        if os.path.exists(self.details_file):
            try:
                with open(self.details_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    # Normalize to lowercase to match the lowercase keys in unique_words
                    self.processed_forms = {row["form"].casefold() for row in reader if row.get("form")}
                logging.info(f"Loaded {len(self.processed_forms)} existing processed forms")
            except Exception as e:
                logging.error(f"Error loading existing forms: {str(e)}")
                raise

    def collect_unique_words(self):
        """Collect unique words from the input file"""
        try:
            with open(self.input_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # A single input like "Veneris" can produce outputs for common
                # words like 'venio' or proper nounds like 'Venus'
                # Since the script handles both we can flatten it to skip them
                self.unique_words = {row["word"].lower() for row in reader}
                # Filter out nulls
                self.unique_words.discard("")
            logging.info(f"Collected {len(self.unique_words)} unique words from source")
        except Exception as e:
            logging.error(f"Error collecting unique words: {str(e)}")
            raise

    @staticmethod
    def analyze_word(word: str) -> Dict:
        """Query the local API for word analysis"""
        try:
            url = f"http://localhost:1500/analysis/word"
            params = {"lang": "lat", "engine": "morpheuslat", "word": word}
            response = requests.get(url, params=params)
            if response.status_code == 201:
                return response.json()
            else:
                logging.warning(
                    f"API request failed for word '{word}' with status {response.status_code}"
                )
                return {}
        except requests.RequestException as e:
            logging.error(f"API request error for word '{word}': {str(e)}")
            raise e

    @staticmethod
    def process_analysis(word: str, analysis: Dict, stripped_enclitic: str | None = None) -> tuple[List[Dict], List[Dict]]:
        """Process the analysis JSON and return details and inflections"""
        details = []
        inflections = []

        # Handle unknown words (no Body object)
        if (
            not analysis
            or "RDF" not in analysis
            or "Body" not in analysis["RDF"]["Annotation"]
        ):
            details.append({"form": word, "item": 0, "dictionaryRef": None})
            return details, inflections

        bodies = analysis["RDF"]["Annotation"]["Body"]
        if not isinstance(bodies, list):
            bodies = [bodies]

        item = 0

        # Use enumerate to get the ORIGINAL index, which is needed for the FORMS_TO_IGNORE check.
        for original_item_index, body in enumerate(bodies):
            # Filters
            try:
                headword = body["rest"]["entry"]["dict"]["hdwd"]["$"]
                # Check FORMS_TO_IGNORE using the original index from enumerate.
                form_key_to_ignore = f"{word}_{original_item_index}"
                if form_key_to_ignore in FORMS_TO_IGNORE:
                    logging.info(f"Ignoring form '{form_key_to_ignore}' based on FORMS_TO_IGNORE list.")
                    continue # Skip to the next body without incrementing final_item_index
                # Check IGNORED_DICT_REFS.
                if headword in IGNORED_DICT_REFS:
                    logging.info(f"Ignoring form '{word}_{original_item_index}' due to unwanted dictionary reference '{headword}'.")
                    continue # Skip to the next body without incrementing final_item_index
            except KeyError:
                pass # Malformed body, no checks possible here so proceed as normally

            if "rest" not in body:
                continue

            try:
                entry = body["rest"]["entry"]
                dict_info = entry["dict"]
                headword = dict_info["hdwd"]["$"].replace("^", "")
                headword = DICT_REF_REPLACEMENTS.get(headword, headword)

                infl_list = entry.get("infl", [])
                if not isinstance(infl_list, list):
                    infl_list = [infl_list]

                pos_dict = dict_info.get("pofs", {}).get("$")

                # Strip a stripped enclitic before using the word for pos-of-speech heuristics
                if stripped_enclitic and len(word) > len(stripped_enclitic) and word.lower().endswith(stripped_enclitic):
                    lookup_word = word[:-len(stripped_enclitic)]
                else:
                    lookup_word = word

                item_inflections = []
                computed_pos_seen = []

                for cnt, infl in enumerate(infl_list):
                    term = infl.get("term", {})
                    gender = infl.get("gend", {}).get("$")
                    pos_infl = infl.get("pofs", {}).get("$")
                    verb_form = infl.get("mood", {}).get("$")
                    gramm_case = infl.get("case", {}).get("$")
                    suffix_aux = MorphologicalAnalyzer.macronize(term.get("suff", {}).get("$"))
                    suffix = None if suffix_aux == "*" else None if suffix_aux is None else suffix_aux.replace("^", "")
                    decl = infl.get("decl", {}).get("$")
                    stem_type = infl.get("stemtype", {}).get("$")
                    degree = infl.get("comp", {}).get("$")
                    computed_pos = part_of_speech(pos_dict, pos_infl, verb_form, gender, suffix, gramm_case, degree, lookup_word)
                    computed_pos_seen.append(computed_pos)
                    tense = infl.get("tense", {}).get("$")
                    inflection = {
                        # "form" filled in after the loop, once we know is_proper
                        "item": item,
                        "cnt": cnt,
                        "partOfSpeech": computed_pos,
                        "stem": MorphologicalAnalyzer.macronize(term.get("stem", {}).get("$")).replace(":", "-").replace("^", ""),
                        "suffix": suffix,
                        "segmentsInfo": segments_info(computed_pos, verb_form, tense, stem_type, suffix, lookup_word),
                        "gender": None if gender == "adverbial" else "neuter" if verb_form == "infinitive" else "masculine/feminine/neuter" if gender is None and decl == "3rd" else gender,
                        "number": "singular" if verb_form == "infinitive" else infl.get("num", {}).get("$"),
                        "declension": declension(computed_pos, decl, suffix, verb_form, tense),
                        "case": case(gramm_case, verb_form, suffix, stem_type),
                        "verbForm": verb_form,
                        "tense": calc_tense(verb_form, tense),
                        "voice": voice(verb_form, tense, infl.get("voice", {}).get("$")),
                        "person": infl.get("pers", {}).get("$"),

                        # uncomment during development
                        #"stem_type": stem_type,
                        #"pos_dict": pos_dict,
                        #"pos_infl": pos_infl,
                        #"gend": gender,
                    }

                    key = f"{word}_{item}_{cnt}"

                    if key in NOT_WANTED_INFLECTIONS:
                        continue

                    if key in FORMS:
                        override = FORMS[key]

                        # A list means that this field has multiple possible values.
                        # Expand the single Morpheus inflection into one inflection per
                        # combination of list-valued fields.
                        list_fields = {
                            field: values
                            for field, values in override.items()
                            if isinstance(values, list)
                        }

                        if list_fields:
                            scalar_overrides = {
                                field: value
                                for field, value in override.items()
                                if field not in list_fields
                            }

                            for values in product(*list_fields.values()):
                                expanded = inflection.copy()
                                expanded.update(scalar_overrides)
                                expanded.update(dict(zip(list_fields, values)))
                                item_inflections.append(expanded)
                        else:
                            inflection.update(override)
                            item_inflections.append(inflection)
                    else:
                        item_inflections.append(inflection)

                # Casing only makes sense for nouns. An interjection/adverb/etc. whose
                # headword happens to reference a proper noun (e.g. "hercle" -> "Hercules")
                # is not itself proper — headword casing is meaningless outside pos "noun".
                is_proper = bool(headword) and headword[0].isupper() and "noun" in computed_pos_seen

                contract_form = apply_contract_casing(word, is_proper)

                detail = {"form": contract_form, "item": item, "dictionaryRef": headword}
                details.append(detail)

                for inflection in item_inflections:
                    inflection["form"] = contract_form
                    inflections.append(inflection)

                item += 1
            except KeyError as e:
                logging.error(f"Error processing analysis for word '{word}': {str(e)}")
                continue

        # De-duplication and re-indexing
        # The API sometimes returns the same grammatical inflection twice
        # with different stem notation. Collapse those (preferring the
        # hyphenated stem) then repack 'cnt' with no gaps
        if not inflections:
            return details, inflections

        final_inflections: List[Dict] = []
        inflections_by_item: Dict[int, List[Dict]] = {}

        # Group all generated inflections by their 'item' number
        for infl in inflections:
            inflections_by_item.setdefault(infl['item'], []).append(infl)

        for item_key in sorted(inflections_by_item.keys()):
            # This list contains all inflections for a given 'item', in their original order
            item_inflections = inflections_by_item[item_key]
            # Store unique inflections for this item, preserving the original relative order
            ordered_unique_inflections: List[Dict] = []
            # Map a signature to its index in the ordered_unique_inflections list to find it quickly
            signature_to_index: Dict[frozenset, int] = {}

            for infl in item_inflections:
                # Create a signature for the inflection, excluding fields that vary for duplicates
                signature_dict = infl.copy()
                signature_dict.pop('stem', None)
                signature_dict.pop('cnt', None)
                signature = frozenset(signature_dict.items())

                if signature not in signature_to_index:
                    # First time seeing this unique inflection. Add it to our ordered list.
                    # Store its index so we can find it again if a preferred version comes along.
                    signature_to_index[signature] = len(ordered_unique_inflections)
                    ordered_unique_inflections.append(infl)
                else:
                    # We've seen this signature before. Check if this new version has a better stem.
                    existing_index = signature_to_index[signature]
                    existing_infl = ordered_unique_inflections[existing_index]
                    current_stem = infl.get('stem', '') or ''
                    existing_stem = existing_infl.get('stem', '') or ''
                    # Rule: Prefer the stem with a hyphen.
                    if '-' in current_stem and '-' not in existing_stem:
                        # Replace the old inflection in-place with this new, preferred one.
                        # This maintains the original position.
                        ordered_unique_inflections[existing_index] = infl

            # Now that we have the final, de-duplicated list for this item in the correct order,
            # re-index the 'cnt' and add them to the final results.
            for new_cnt, final_infl in enumerate(ordered_unique_inflections):
                final_infl['cnt'] = new_cnt
                final_inflections.append(final_infl)

        return details, final_inflections

    def write_results(self, source_word: str, details: List[Dict], inflections: List[Dict]):
        """Write one result batch for a source word."""

        source_key = source_word.casefold()

        detail_keys = [
            (
                (detail.get("form") or "").casefold(),
                detail.get("item"),
                detail.get("dictionaryRef"),
            )
            for detail in details
        ]

        # Detect duplicate generation before anything reaches the CSV.
        if len(detail_keys) != len(set(detail_keys)):
            raise RuntimeError(
                f"Duplicate details were generated before writing: {detail_keys}"
            )

        # Re-read the actual file immediately before appending.
        # Catches stale in-memory state or another writer modifying the file.
        if os.path.exists(self.details_file):
            with open(self.details_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                if any(
                        (row.get("form") or "").casefold() == source_key
                        for row in reader
                ):
                    raise RuntimeError(
                        f"Refusing to append '{source_word}': it is already "
                        f"present on disk in {os.path.abspath(self.details_file)}"
                    )


        logging.info(
            "Writing '%s': %d details, %d inflections",
            source_word,
            len(details),
            len(inflections),
        )

        try:
            details_fieldnames = [
                "form",
                "item",
                "dictionaryRef",
            ]

            inflections_fieldnames = [
                "form",
                "item",
                "cnt",
                "partOfSpeech",
                "stem",
                "suffix",
                "segmentsInfo",
                "gender",
                "number",
                "declension",
                "case",
                "verbForm",
                "tense",
                "voice",
                "person",

                #"stem_type",
                #"pos_dict",
                #"pos_infl",
                #"gend",
            ]

            # Write details
            details_exists = os.path.exists(self.details_file)

            with open(self.details_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=details_fieldnames)
                if not details_exists:
                    writer.writeheader()

                writer.writerows(details)

            # Write inflections
            inflections_exists = os.path.exists(self.inflections_file)

            with open(self.inflections_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=inflections_fieldnames)

                if not inflections_exists:
                    writer.writeheader()

                writer.writerows(inflections)

            self.processed_forms.add(source_key)

        except Exception:
            logging.exception(
                "Failed while writing results for '%s'",
                source_word,
            )
            raise

    def process_words(self):
        """Process all words from the input file, with retries for enclitics."""
        details: list[dict]
        inflections: list[dict]
        words_to_process = self.unique_words - self.processed_forms
        sorted_words_to_process = sorted(list(words_to_process))
        logging.info(f"Starting to process {len( sorted_words_to_process )} new words")

        for word in sorted_words_to_process:
            logging.debug(f"Processing word: {word}")

            if word in FULL_OVERRIDES: # Some words might not be found or be complete wack, these are overridden
                logging.info(f"Using full override for '{word}'")
                details, inflections = FULL_OVERRIDES[word]
                self.write_results(word, details, inflections)
                continue  # Already processed, skip to next word

            try:

                word_for_analysis = ANALYSIS_ALIASES.get(word, word)
                if word_for_analysis != word:
                    logging.info(f"'{word}' analyzed as '{word_for_analysis }'")

                analysis = self._query_merged(word_for_analysis)
                details, inflections = self.process_analysis(word, analysis)

                # If the initial analysis found no inflections, try stripping enclitics.
                if not inflections:
                    if word_for_analysis == word:
                        logging.debug(f"Initial analysis for '{word}' failed, checking for enclitics.")
                    else:
                        logging.debug(f"Initial analysis for '{word}' (as '{word_for_analysis}') failed, checking for enclitics.")
                    for enclitic in self.ENCLITICS:
                        if word_for_analysis.endswith(enclitic) and len(word_for_analysis) > len(enclitic):
                            base_word = word_for_analysis[:-len(enclitic)]
                            logging.info(f"Retrying '{word}' as base '{base_word}' (enclitic '{enclitic}').")

                            retry_analysis = self._query_merged(base_word)
                            # Pass the original `word` to keep it as the `form` in the output.
                            retry_details, retry_inflections = self.process_analysis(word, retry_analysis, stripped_enclitic=enclitic)

                            if retry_inflections:
                                details = retry_details
                                inflections = retry_inflections
                                break  # Success, exit enclitic loop

                # After all attempts, write the result (success, retry-success, or failure)
                if details:
                    self.write_results(word, details, inflections)
                    if inflections:
                        logging.info(f"Successfully processed word: {word}")
                    else:
                        logging.warning(f"No analysis found for '{word}', stored as unknown.")
                else:
                    logging.warning(f"No analysis results for word: {word}")

            except requests.RequestException as e:
                logging.error(f"API request error for word '{word}': {str(e)}. Will retry next run.")
                continue
            except Exception as e:
                logging.error(f"Error processing word '{word}': {str( e )}")
                continue

        logging.info(
            f"Finished processing words. Total processed: {len( self.processed_forms )}"
        )

    def _query_merged(self, word: str) -> Dict:
        lower_form = word.lower()
        title_form = lower_form.capitalize()
        analysis_lower = self.analyze_word(lower_form)
        analysis_title = self.analyze_word(title_form) if title_form != lower_form else {}
        merged_bodies = _merge_bodies(analysis_lower, analysis_title)
        return {"RDF": {"Annotation": {"Body": merged_bodies}}} if merged_bodies else {}


def part_of_speech(pos_dict, pos_infl, verb_form, gender, suffix, gramm_case, degree, form) -> str:
    """
    The service ignore the fact that gerund exists, so there's that

    Some adjectives like *fallaci* don't have gender, so there's that

    I suspect some comparatives are broken in such a way that a form from a 1st & 2nd declension will not show the actual declension of the comparative form (*notior* for *notus*), so there's that

    :param pos_dict: pofs tag
    :param pos_infl: infl.pofs tag
    :param verb_form: mood tag
    :param gender: gend tag
    :param suffix: suff tag
    :param gramm_case: case tag
    :param form: the word
    :param degree: adjective degree
    :return: a normalized part of speech
    """

    def _strip_known_enclitic(raw_form: str) -> str:
        """If `raw_form` has no enclitic, this either finds no match
        or strips something harmless for the suffix check and adverb whitelist"""
        for enclitic in MorphologicalAnalyzer.ENCLITICS:
            if raw_form.endswith(enclitic) and len(raw_form) > len(enclitic):
                return raw_form[:-len(enclitic)]
        return raw_form

    stripped_form = _strip_known_enclitic(form)

    # trust pos_infl == 'adverb' only if confirmed manually
    if pos_infl == "adverb" and (form in TRUE_ADVERB_FORMS or stripped_form in TRUE_ADVERB_FORMS):
        return "adverb"

    # adjective first
    if pos_dict == "adjective":
        if gramm_case is None and (gender == "adverbial"
                                   or suffix in ["ē", "ius", "ter", "issimē"]
                                   or form.endswith(("e", "ius", "ter", "issime"))):
                                   # or stripped_form.endswith(("e", "ius", "ter", "issime"))): might be necessary eventually
            return "adverb"
        else:
            if pos_infl in ["adjective", "numeral", "verb", "verb participle"]:
                return "adjective"
            elif pos_infl == "noun":
                return "noun"
            else:
                return "new combination, check"

    # adverb first
    elif pos_dict == "adverb":
        if pos_infl == "adverb":
            return "adverb"
        elif pos_infl == "adjective":
            return "adjective"
        elif pos_infl == "conjunction":
            return "conjunction"
        elif pos_infl == "irregular":
            return "noun"
        elif pos_infl == "noun":
            return "noun"
        elif pos_infl == "preposition":
            return "preposition"
        elif pos_infl == "pronoun":
            return "pronoun"
        elif pos_infl == "verb":
            return "verb"
        else:
            return "new combination, check"

    # conjunction first
    elif pos_dict == "conjunction":
        if pos_infl == "conjunction":
            return "conjunction"
        elif pos_infl == "preposition":
            return "preposition"
        elif pos_infl == "adverb":
            return "adverb"
        else:
            return "new combination, check"

    # exclamation first
    elif pos_dict == "exclamation":
        if pos_infl == "exclamation":
            return "interjection"
        else:
            return "new combination, check"

    # irregular first
    elif pos_dict == "irregular":
        return "irregular"

    # noun first
    elif pos_dict == "noun":
        if gramm_case is None and gender == "adverbial":
            return "adverb"
        else:
            if pos_infl == "noun":
                return "noun"
            elif pos_infl == "adjective":
                return "adjective"
            elif pos_infl == "verb":
                return "verb"
            elif pos_infl == "verb participle" and verb_form == "participle":
                return "adjective"
            else:
                return "new combination, check"

    # numeral first
    elif pos_dict == "numeral":
        if pos_infl == "numeral":
            return "numeral"
        else:
            return "new combination, check"

    # preposition first
    elif pos_dict == "preposition":
        if pos_infl == "preposition":
            return "preposition"
        if pos_infl == "adverb":
            return "adverb"
        else:
            return "new combination, check"

    # pronoun first
    elif pos_dict == "pronoun":
        if pos_infl == "pronoun":
            return "pronoun"
        elif pos_infl == "adverb":
            return "adverb"
        else:
            return "new combination, check"

    # verb first
    elif pos_dict == "verb":
        if verb_form is None:
            if gender == "adverbial":
                return "adverb"
            elif degree in ["comparative", "superlative"]:
                return "adjective"
            elif pos_infl == "noun":
                return "noun"
            else:
                return "new combination, check"
        else:
            if pos_infl == "verb":
                if verb_form == "infinitive":
                    return "noun"
                elif verb_form == "gerundive":
                    return "adjective"
                elif verb_form in ["indicative", "subjunctive", "imperative"]:
                    return "verb"
                else:
                    return "new combination, check"
            elif pos_infl == "noun": # supine
                return "noun"
            elif pos_infl == "verb participle":
                return "adjective"
            else:
                return "new combination, check"

    # no matches
    return "new combination, check"


def declension( computed_pos:str, decl_tag:str, suffix:str | None, verb_form:str, verb_tense:str ) -> str | None:
    if verb_form == "gerundive":
        return "1st & 2nd"
    elif verb_form == "participle":
        if verb_tense == "present":
            return "3rd"
        elif verb_tense in ["perfect", "future"]:
            return "1st & 2nd"
        return None
    elif verb_form == "supine":
        return "4th"
    elif computed_pos in ["noun","adjective"] and suffix is not None and ( suffix.find("ior") != -1 or suffix.find("ius") != -1 ):
        return "3rd"
    elif computed_pos in ["noun","adjective"] and suffix is not None and suffix.find("issim") != -1:
        return "1st & 2nd"
    else:
        return decl_tag


def case(gramm_case: str, verb_form: str, suffix: str | None, stem_type: str) -> str:
    """
    Determines the grammatical case, overriding API errors for specific forms like supine.
    """
    # Supine seems mis-cased by the API. Override based on the suffix.
    if verb_form == "supine":
        if suffix == "um":
            return "accusative"
        elif suffix == "ū":
            return "ablative"
        return gramm_case # Fallback

    # Handle -er adjectives
    if ( gramm_case is None or gramm_case == "" ) and suffix == "er" and stem_type == "er_eris":
        return "nominative/vocative"

    # Otherwise
    return gramm_case


def voice(verb_form: str | None, tense: str | None, original_v: str | None) -> str | None:
    new_v = original_v
    if verb_form is not None and original_v is None:
        if verb_form == 'participle' and tense == 'present':
            new_v = 'active'
        elif verb_form == 'gerundive':
            new_v = 'passive'
    return new_v

def calc_tense(verb_form: str | None, original_t: str | None) -> str | None:
    new_t = original_t
    if verb_form is not None and original_t is None:
        if verb_form == 'gerundive':
            new_t = 'future'
    return new_t


def segments_info(
    computed_pos: str,
    verb_form: str,
    verb_tense: str,
    stemtype_tag: str,
    suffix: str | None,
    lookup_word: str
) -> str | None:

    def remove_adj_suffix( text:str ) -> str:
        suffixes = ['_adj', '_adj1', '_adj2', '_adj3', '_comp']
        for s in suffixes:
            text = text.removesuffix( s )
        return text

    def process_tag( stemtype: str ) -> str:
        # Remove leading '0' if present
        if stemtype.startswith( '0' ):
            stemtype = stemtype[1:]
        # Convert L-notation to macrons
        replacements = {
            'eL': 'ē',
            'aL': 'ā',
            'iL': 'ī',
            'oL': 'ō',
            'uL': 'ū',
            'EL': 'Ē',
            'AL': 'Ā',
            'IL': 'Ī',
            'OL': 'Ō',
            'UL': 'Ū'
        }
        for key, value in replacements.items( ):
            stemtype = stemtype.replace( key, value )
        # Replace underscore with comma and hyphen
        return stemtype.replace( '_', ', -' )

    if stemtype_tag.startswith("irreg"):
        return "irregular"
    elif stemtype_tag == "indecl":
        return "indeclinable"
    else:

        # for nouns
        if computed_pos == "noun":
            if verb_form is None or verb_form == "":
                noun_st_tag = "is_is" if stemtype_tag == "is_is_C" else "ion_iī" if stemtype_tag == "ios_i" else stemtype_tag
                if noun_st_tag.count("_") == 1:
                    return process_tag( noun_st_tag )
                elif suffix is not None and ( suffix.find("ior") != -1 or suffix.find("ius") != -1 ):
                    return "ior, -ius"
                elif suffix is not None and suffix.find("issim") != -1:
                    return "issimus, -issima, -issimum"
            elif verb_form == "supine":
                return "supine stem"

        # for adjectives
        elif computed_pos == "adjective":
            if verb_form == "participle":
                if verb_tense == "present":
                    if stemtype_tag == "conj1":
                        return "āns, -antis"
                    elif stemtype_tag in ["conj2", "conj3"]:
                        return "ēns, -entis"
                    elif stemtype_tag in ["conj3_io", "conj4"]:
                        return "iēns, -ientis"
                elif verb_tense == "perfect":
                    return "us, -a, -um"
                elif verb_tense == "future": # voice not necessary because it is always active (the passive one has form *gerundive*)
                    return "ūrus, -ūra, -ūrum"
            elif verb_form == "gerundive":
                gerundive_suffixes = { "conj1": "andus, -anda, -andum", "conj2": "endus, -enda, -endum", "conj3": "endus, -enda, -endum", "conj3_io": "iendus, -ienda, -iendum","conj4": "iendus, -ienda, -iendum",}
                if stemtype_tag in gerundive_suffixes:
                    return gerundive_suffixes[stemtype_tag]
            elif suffix is not None and ( suffix.find("ior") != -1 or suffix.find("ius") != -1 ):
                return "ior, -ius"
            elif suffix is not None and suffix.find("issim") != -1:
                return "issimus, -issima, -issimum"
            else:
                adj_st_tag = remove_adj_suffix(stemtype_tag)
                return process_tag( adj_st_tag )

        # for verbs
        elif computed_pos == "verb":
            perfect_stems = { "perfstem": "perfect stem", "evperf": "v-perfect", "avperf": "v-perfect", "ivperf": "v-perfect",}
            conjugations = { "conj1": "1st conjugation", "conj2": "2nd conjugation", "conj3": "3rd conjugation", "conj3_io": "3rd conjugation -iō", "conj4": "4th conjugation",}
            verb_inflections = perfect_stems | conjugations
            if stemtype_tag in verb_inflections:
                return verb_inflections[stemtype_tag]

        elif lookup_word == "aliquot":
            return "indeclinable"

        elif computed_pos == "new combination, check":
            return "new combination, check"

        return None


class MorphologicalDataValidator:
    """
    Validates the generated morphological inflections CSV against a set of grammatical rules for Classical Latin.
    """
    ADJECTIVE_ALLOWED_VERB_FORMS = {None, 'gerundive', 'participle'}
    ADJECTIVE_VERB_COMBOS = {
        # (verbForm, tense, voice)
        (None, None, None),
        ('gerundive', 'future', 'passive'),
        ('participle', 'future', 'active'),
        ('participle', 'present', 'active'),
        ('participle', 'perfect', 'passive'),
    }

    def __init__(self, inflections_file_path: str, details_file_path: str):
        self.file_path = inflections_file_path
        self.details_path = details_file_path
        self.warning_count = 0

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """Checks if a value from the CSV is None or an empty string."""
        return value is None or value == ''

    def _log_warning(self, line_num: int, pos: str, form: str, message: str):
        """Formats and logs a validation warning."""
        logging.warning(f"L{line_num} | {pos.upper()} '{form}': {message}")
        self.warning_count += 1

    def validate(self):
        """Runs all validation checks on the inflections file."""
        logging.info(f"Starting validation of morphological data in '{self.file_path}'...")
        if not os.path.exists(self.file_path):
            logging.error(f"Validation failed: Inflections file not found at '{self.file_path}'")
            return

        self._validate_casing_pos_gate()
        self._validate_no_duplicate_details()
        self._validate_no_duplicate_inflections()
        self._validate_dictionary_ref_consistency()

        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                line_num = i + 2 # +1 for zero-index, +1 for header
                pos = row.get('partOfSpeech', '')
                form = row.get('form', '')

                if self._is_empty(pos):
                    self._log_warning(line_num, '???', form, "partOfSpeech is null.")
                    continue
                if pos == 'new combination, check':
                    self._log_warning(line_num, pos, form, "partOfSpeech is 'new combination, check'.")
                    continue

                dispatch: Dict[str, Callable[[Dict[str, str], int], None]] = {
                    'adjective': self._validate_adjective,
                    'adverb': self._validate_adverb,
                    'conjunction': self._validate_uninflected_particle,
                    'interjection': self._validate_uninflected_particle,
                    'preposition': self._validate_uninflected_particle,
                    'irregular': self._validate_irregular,
                    'noun': self._validate_noun,
                    'numeral': self._validate_numeral,
                    'pronoun': self._validate_pronoun,
                    'verb': self._validate_verb,
                }

                handler = dispatch.get(pos)
                if handler:
                    handler(row, line_num)
                else:
                    self._log_warning(line_num, pos, form, f"Unknown partOfSpeech '{pos}'.")

        if self.warning_count == 0:
            logging.info("Validation complete. No issues found.")
        else:
            logging.warning(f"Validation complete. Found {self.warning_count} potential issues.")

    def _validate_adjective(self, row: Dict[str, str], line_num: int):
        form = row['form']
        segm_info = row.get('segmentsInfo', '')
        is_indeclinable = (not self._is_empty(segm_info) and segm_info == 'indeclinable')

        # Required fields
        if not is_indeclinable:
            for field in ['gender', 'number', 'declension', 'case']:
                if self._is_empty(row.get(field)):
                    self._log_warning(line_num, 'adjective', form, f"Required field '{field}' is empty.")

        # Forbidden fields
        if not self._is_empty(row.get('person')):
            self._log_warning(line_num, 'adjective', form, f"Field 'person' must be empty, but found '{row.get('person')}'.")

        # Verb form constraints
        verb_form = row.get('verbForm') if not self._is_empty(row.get('verbForm')) else None
        if verb_form not in self.ADJECTIVE_ALLOWED_VERB_FORMS:
            self._log_warning(line_num, 'adjective', form, f"Invalid verbForm '{verb_form}'. Allowed: {self.ADJECTIVE_ALLOWED_VERB_FORMS}.")

        # Verb form combination constraints
        combo = (
            verb_form,
            row.get('tense') if not self._is_empty(row.get('tense')) else None,
            row.get('voice') if not self._is_empty(row.get('voice')) else None,
        )
        if combo not in self.ADJECTIVE_VERB_COMBOS:
            self._log_warning(line_num, 'adjective', form, f"Invalid verbForm-tense-voice combination: {combo}.")

    def _validate_adverb(self, row: Dict[str, str], line_num: int):
        form = row['form']

        # Forbidden fields
        for field in ['segmentsInfo', 'gender', 'number', 'case', 'verbForm', 'tense', 'voice', 'person']:
            if not self._is_empty(row.get(field)):
                self._log_warning(line_num, 'adverb', form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")

        declension_val = row.get('declension', '')
        suffix_val = row.get('suffix', '')
        if not self._is_empty(declension_val) and self._is_empty(suffix_val):
            self._log_warning(line_num, 'adverb', form, f"declension is '{declension_val}' but suffix is null (derived adverbs must have a suffix).")

    def _validate_uninflected_particle(self, row: Dict[str, str], line_num: int):
        pos = row['partOfSpeech']
        form = row['form']

        # Forbidden fields
        for field in ['segmentsInfo', 'suffix', 'gender', 'number', 'declension', 'case', 'verbForm', 'tense', 'voice', 'person']:
            if not self._is_empty(row.get(field)):
                self._log_warning(line_num, pos, form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")

        # Required fields
        if self._is_empty(row.get('stem')):
            self._log_warning(line_num, pos, form, "Field 'stem' must not be empty.")

    def _validate_irregular(self, row: Dict[str, str], line_num: int):
        form = row['form']
        segm_info = row.get('segmentsInfo', '')
        if self._is_empty(segm_info) or segm_info != 'indeclinable':
            self._log_warning(line_num, 'irregular', form, f"segmentsInfo must be 'indeclinable', but is '{segm_info}'.")

    def _validate_noun(self, row: Dict[str, str], line_num: int):
        form = row['form']

        if self._is_empty(row.get('gender')):
            self._log_warning(line_num, 'noun', form, "Required field 'gender' is empty.")
        if self._is_empty(row.get('number')):
            self._log_warning(line_num, 'noun', form, "Required field 'number' is empty.")
        if not self._is_empty(row.get('person')):
            self._log_warning(line_num, 'noun', form, f"Field 'person' must be empty, but is '{row.get('person')}'.")

        has_declension = not self._is_empty(row.get('declension'))
        verb_form = row.get('verbForm') if not self._is_empty(row.get('verbForm')) else None
        segments_info_val = row.get('segmentsInfo', '')
        is_indeclinable = (not self._is_empty(segments_info_val) and segments_info_val == 'indeclinable')

        if is_indeclinable:
            # Indeclinable nouns (e.g. fas, nefas): no declension paradigm, no verbal properties
            if has_declension:
                self._log_warning(line_num, 'noun (indeclinable)', form, f"Declension must be empty, but is '{row.get('declension')}'.")
            for field in ['verbForm', 'tense', 'voice']:
                if not self._is_empty(row.get(field)):
                    self._log_warning(line_num, 'noun (indeclinable)', form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")
        elif verb_form == 'supine':
            if row.get('declension') != '4th':
                self._log_warning(line_num, 'noun (supine)', form, f"Declension must be '4th', but is '{row.get('declension')}'.")
            if row.get('case') not in ('accusative', 'ablative'):
                self._log_warning(line_num, 'noun (supine)', form, f"Case must be 'accusative' or 'ablative', but is '{row.get('case')}'.")
            for field in ['tense', 'voice']:
                if not self._is_empty(row.get(field)):
                    self._log_warning(line_num, 'noun (supine)', form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")
        elif has_declension:
            if self._is_empty(row.get('case')):
                self._log_warning(line_num, 'noun', form, "Has declension but 'case' is empty.")
            for field in ['verbForm', 'tense', 'voice']:
                if not self._is_empty(row.get(field)):
                    self._log_warning(line_num, 'noun', form, f"Has declension but '{field}' is '{row.get(field)}' (must be empty).")
        else:
            if verb_form != 'infinitive':
                self._log_warning(line_num, 'noun', form, f"No declension: verbForm must be 'infinitive', but is '{verb_form}'.")
            if self._is_empty(row.get('tense')):
                self._log_warning(line_num, 'noun', form, "No declension (infinitive): tense must not be empty.")
            if self._is_empty(row.get('voice')):
                self._log_warning(line_num, 'noun', form, "No declension (infinitive): voice must not be empty.")

    def _validate_numeral(self, row: Dict[str, str], line_num: int):
        form = row['form']
        # Forbidden fields
        for field in ['verbForm', 'tense', 'voice', 'person']:
            if not self._is_empty(row.get(field)):
                self._log_warning(line_num, 'numeral', form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")

    def _validate_pronoun(self, row: Dict[str, str], line_num: int):
        form = row['form']
        segm_info = row.get('segmentsInfo', '')
        is_indeclinable = (not self._is_empty(segm_info) and segm_info == 'indeclinable')

        if is_indeclinable:
            # Forbidden fields
            for field in ['gender', 'number', 'case']:
                if not self._is_empty(row.get(field)):
                    self._log_warning(line_num, 'pronoun', form, f"segmentsInfo is 'indeclinable' but '{field}' is '{row.get(field)}' (must be empty).")
        else:
            # Required fields
            for field in ['gender', 'number', 'case']:
                if self._is_empty(row.get(field)):
                    self._log_warning(line_num, 'pronoun', form, f"Required field '{field}' is empty.")

        # Always forbidden
        for field in ['verbForm', 'tense', 'voice', 'person']:
            if not self._is_empty(row.get(field)):
                self._log_warning(line_num, 'pronoun', form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")

    def _validate_verb(self, row: Dict[str, str], line_num: int):
        form = row['form']
        # Required fields
        for field in ['number', 'verbForm', 'tense', 'voice', 'person']:
            if self._is_empty(row.get(field)):
                self._log_warning(line_num, 'verb', form, f"Required field '{field}' is empty.")

        # Forbidden fields
        for field in ['gender', 'declension', 'case']:
            if not self._is_empty(row.get(field)):
                self._log_warning(line_num, 'verb', form, f"Field '{field}' must be empty, but is '{row.get(field)}'.")

    def _validate_casing_pos_gate(self):
        """If one inflection or more have partOfSpeech 'noun', then we are allowed to
        have capitalized 'form' values. Catches cases like 'Hercle' (interjection,
        headword references Hercules but the word itself isn't a proper noun)."""
        groups: Dict[Tuple[str, str], List[str | None]] = {}

        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                groups.setdefault((row['form'], row['item']), []).append(row.get('partOfSpeech'))

        for (form, item), pos_list in groups.items():
            if form and form[0].isupper() and 'noun' not in pos_list:
                self._log_warning(0, 'casing', form,
                                  f"item {item}: capitalized but no inflection is 'noun' (pos: {pos_list}).")

    def _validate_no_duplicate_details(self):
        """MorphologicalDetails rows must be unique on (form, item)."""
        counts: Dict[Tuple[str, str], int] = {}
        with open(self.details_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get('form', ''), row.get('item', ''))
                counts[key] = counts.get(key, 0) + 1
        for (form, item), count in counts.items():
            if count > 1:
                self._log_warning(0, 'details-dup', form,
                                  f"item {item}: appears {count}x in MorphologicalDetails.")

    def _validate_no_duplicate_inflections(self):
        """MorphologicalDetailInflections rows must be unique on (form, item, cnt)."""
        counts: Dict[Tuple[str, str, str], int] = {}
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get('form', ''), row.get('item', ''), row.get('cnt', ''))
                counts[key] = counts.get(key, 0) + 1
        for (form, item, cnt), count in counts.items():
            if count > 1:
                self._log_warning(0, 'inflections-dup', form,
                                  f"item {item}, cnt {cnt}: appears {count}x in MorphologicalDetailInflections.")

    def _validate_dictionary_ref_consistency(self):
        """A details row with a dictionaryRef must have at least one inflection row.
        A details row without one must have none."""
        ref_by_key: Dict[Tuple[str, str], str | None] = {}
        with open(self.details_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ref_by_key[(row.get('form', ''), row.get('item', ''))] = row.get('dictionaryRef')

        infl_keys: Set[Tuple[str, str]] = set()
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                infl_keys.add((row.get('form', ''), row.get('item', '')))

        for (form, item), ref in ref_by_key.items():
            has_inflections = (form, item) in infl_keys
            if not self._is_empty(ref) and not has_inflections:
                self._log_warning(0, 'ref-consistency', form,
                                  f"item {item}: dictionaryRef='{ref}' but has no inflections.")
            elif self._is_empty(ref) and has_inflections:
                self._log_warning(0, 'ref-consistency', form,
                                  f"item {item}: dictionaryRef is null but has inflections.")

def main():
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        analyzer = MorphologicalAnalyzer(project_root)
        analyzer.process_words()
        logging.info("Morphological analysis processing complete.")

        validator = MorphologicalDataValidator(analyzer.inflections_file, analyzer.details_file)
        validator.validate()

    except Exception as e:
        logging.critical(f"Critical error in main execution: {str( e )}")
        raise


if __name__ == "__main__":
    main()