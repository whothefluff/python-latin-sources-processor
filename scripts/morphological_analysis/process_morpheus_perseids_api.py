import csv
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from itertools import product
from pathlib import Path
from typing import Dict, List, NamedTuple, Set, Any, Tuple, Callable

import requests
from scripts.common.macrons import strip_macrons
from scripts.common.publishing import publish, raise_for_publication_leftovers
from scripts.common.services import MORPHEUS_URL
from scripts.library.util.casing import apply_contract_casing, is_proper_item
from scripts.library.util.proper_noun import ProperNounState
from scripts.library.util.token_classification import TokenType
from scripts.library.util.unambiguous_macronizations import lookup_key
from scripts.morphological_analysis.process_morpheus_perseids_api_aux.overrides import (
    FORMS, FULL_OVERRIDES, ANALYSIS_ALIASES, IGNORED_DICT_REFS, DICT_REF_REPLACEMENTS, TRUE_ADVERB_FORMS, ReadingRule
)


def _merge_bodies(analysis_lower: Dict, analysis_title: Dict) -> List[Dict]:
    """Merge Body entries from lowercase + Title-case queries. Morpheus answers a lowercase word with its lowercase
    analyses only, so proper-noun-only entries (e.g. 'Athena') never surface there. A capitalized word it answers with
    those analyses too, grouped with the capitalized ones under their headword: 'Hercules' gives one entry with the
    noun and the exclamation that 'hercules' gives. So an entry of the capitalized answer is kept whole under a headword
    that the lowercase answer doesn't have. Under one it has, the entry keeps the inflections that are new when its
    headword is capitalized (Hercules's noun), and is dropped when it isn't: a lowercase headword's readings are the
    lowercase answer's. An inflection is new when its headword doesn't have it yet, a stem that differs only in case
    aside: Hymenaeus has the god's stem and the song's, Hymenae and hymenae, and the capitalized answer gives both,
    which read the same. Lowercase-sourced bodies come first."""
    def get_bodies(analysis):
        if not analysis or "RDF" not in analysis or "Body" not in analysis["RDF"]["Annotation"]:
            return []
        bodies = analysis["RDF"]["Annotation"]["Body"]
        return bodies if isinstance(bodies, list) else [bodies]

    def headword_of(body):
        return body.get("rest", {}).get("entry", {}).get("dict", {}).get("hdwd", {}).get("$")

    def inflections_of(body):
        inflections = body.get("rest", {}).get("entry", {}).get("infl", [])
        return inflections if isinstance(inflections, list) else [inflections]

    def reading_of(inflection):
        # As text: each answer gives its bodies ids of their own, but the same inflection the same tags
        stem = inflection.get("term", {}).get("stem", {})
        if "$" in stem:
            inflection = {**inflection, "term": {**inflection["term"], "stem": {**stem, "$": stem["$"].lower()}}}
        return json.dumps(inflection, sort_keys=True)

    merged = list(get_bodies(analysis_lower))
    headwords = {headword_of(body) for body in merged}
    known = {(headword_of(body), reading_of(inflection)) for body in merged for inflection in inflections_of(body)}
    for body in get_bodies(analysis_title):
        headword = headword_of(body)
        if headword is not None and headword in headwords:
            if not headword[0].isupper():
                continue
            new = [inflection for inflection in inflections_of(body)
                   if (headword, reading_of(inflection)) not in known]
            if not new:
                continue
            body = {**body, "rest": {**body["rest"], "entry": {**body["rest"]["entry"], "infl": new}}}
        headwords.add(headword)
        merged.append(body)
        known.update((headword, reading_of(inflection)) for inflection in inflections_of(body))
    return merged


class ValidationFailed(ValueError):
    """The output files have issues, which the validator logged."""

    def __init__(self, issues: int):
        self.issues = issues
        super().__init__(f"Validation failed. Found {issues} issues, logged above.")


class WordsWithoutAnalysis(Exception):
    """The words that a run couldn't write an analysis for, each with the reason."""

    def __init__(self, reasons_by_word: Dict[str, str]):
        self.reasons_by_word = reasons_by_word
        super().__init__(f"{len(reasons_by_word)} words have no analysis written: "
                         + ", ".join(f"'{word}' ({reason})" for word, reason in reasons_by_word.items()))


class RulesThatChangeNothing(ValueError):
    """Rules in FORMS that change nothing in a word's readings, each with why."""
    NO_READING = "none of the word's readings has its values"

    def __init__(self, word: str, why_by_rule: List[Tuple[ReadingRule, str]]):
        self.why_by_rule = why_by_rule
        super().__init__(f"Rules in FORMS change nothing for '{word}': "
                         + "; ".join(f"{rule.headword} {dict(rule.match)}: {why}" for rule, why in why_by_rule))


class MorphologicalAnalyzer:
    # What follows a vowel in Morpheus's notation: _ makes it long, ^ short, and both, in either order, common
    _QUANTITY_MARKS = ("_^", "^_", "_", "^")
    _LONG_VOWELS = str.maketrans("aeiouyAEIOUY", "āēīōūȳĀĒĪŌŪȲ")
    # A mute (b, c, d, g, p, t, or ch, ph, th) and a liquid (l, r)
    _MUTE_AND_LIQUID = re.compile(r"[bcdgpt]h?[lr]")

    # List of Latin enclitics, sorted by length descending to match longer ones first (e.g., "cumque" before "que")
    ENCLITICS = sorted([
        "que", "ne", "ve", "ue", "vis", "piam", "dem", "dum",
    ], key=len, reverse=True)

    # Endings that an analysis can leave out of the form, such as que in jubetque or cumque in qualecumque
    OMITTED_TAILS = (*ENCLITICS, "cumque")

    _PLAIN_LETTERS = str.maketrans("", "", "_^:-*+")


    def __init__(self, project_root: str, working_dir: str | None = None):
        """working_dir is where the analyses are read and added to, the output directory when it's None."""
        self.project_root = project_root
        self.input_file = os.path.join(
            project_root, "output", "library", "work_contents.csv"
        )
        self.output_dir = os.path.join(project_root, "output", "morphological_analysis")
        self.details_file = os.path.join(working_dir or self.output_dir, "morphological_details.csv")
        self.inflections_file = os.path.join(
            working_dir or self.output_dir, "morphological_detail_inflections.csv"
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
        self.check_outputs_match_source()

    def check_outputs_match_source(self):
        """Raise if morphological_details.csv has forms that work_contents.csv doesn't have anymore.
        Since this script only adds missing forms, the old analyses would stay."""
        stale_forms = sorted(self.processed_forms - self.unique_words)
        if stale_forms:
            raise ValueError(
                f"morphological_details.csv has {len(stale_forms)} forms that work_contents.csv doesn't have "
                f"anymore, such as {stale_forms[:10]}. Delete the CSVs in {self.output_dir} and run again"
            )

    @staticmethod
    def spellings(text: str) -> List[str]:
        """Returns the spellings that a stem or suffix in Morpheus's notation stands for, long vowels with macrons. A
        common vowel can be either, so it gives two spellings, the short one first: tibi_^ is tibi and tibī. Unless a
        mute and a liquid follow it: then the mark is the syllable's, which they can lengthen, and the vowel is short,
        as in pa_^tr for patrem. No ending starts with them. The diaeresis (+) is dropped."""
        letters: List[List[str]] = []
        position = 0
        while position < len(text):
            letter = text[position]
            mark = next((m for m in MorphologicalAnalyzer._QUANTITY_MARKS if text.startswith(m, position + 1)), "")
            position += 1 + len(mark)
            if letter in "_^+":
                continue
            long = letter.translate(MorphologicalAnalyzer._LONG_VOWELS)
            if long == letter or mark in ("", "^"):
                letters.append([letter])
            elif mark == "_":
                letters.append([long])
            else:
                rest = text[position:].translate(MorphologicalAnalyzer._PLAIN_LETTERS).lower()
                letters.append([letter] if MorphologicalAnalyzer._MUTE_AND_LIQUID.match(rest) else [letter, long])
        return ["".join(spelling) for spelling in product(*letters)]

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
        """Collect unique lowercase words, macron-stripped expansions and detached enclitics.
        A detached enclitic gets a hyphen in front: the *ne* of *tune* is '-ne', apart from the word 'ne'."""
        try:
            with open(self.input_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                words = set()
                for row in reader:
                    word = row.get("word")
                    if word:
                        words.add(word.lower())
                    expansion = row.get("expansion")
                    if expansion:
                        words.add(strip_macrons(expansion).lower())
                    enclitic = row.get("enclitic")
                    if enclitic:
                        enclitic_form = f"-{enclitic.lower()}"
                        if enclitic_form not in FULL_OVERRIDES:
                            raise ValueError(f"FULL_OVERRIDES has no analysis for the detached enclitic '{enclitic_form}'")
                        words.add(enclitic_form)
                self.unique_words = words
            logging.info(f"Collected {len(self.unique_words)} unique words from source")
        except Exception as e:
            logging.error(f"Error collecting unique words: {str(e)}")
            raise

    @staticmethod
    def analyze_word(word: str) -> Dict:
        """Query the local API for word analysis. Raises when the request fails, or when the status isn't 201 or the
        answer has no annotation (Morpheus answers every word with 201 and an annotation, known or not)."""
        try:
            params = {"lang": "lat", "engine": "morpheuslat", "word": word}
            response = requests.get(MORPHEUS_URL, params=params, timeout=10)
            if response.status_code == 201:
                answer = response.json()
                if "Annotation" not in answer.get("RDF", {}):
                    raise ValueError(f"Morpheus's answer for '{word}' has no annotation: {answer}")
                return answer
            else:
                raise RuntimeError(f"Morpheus answered '{word}' with status {response.status_code}")
        except requests.RequestException as e:
            logging.error(f"API request error for word '{word}': {str(e)}")
            raise e

    @staticmethod
    def _spelling_of(infl: Dict) -> str:
        """Returns the inflection's stem and suffix, lowercase and without macrons."""
        term = infl.get("term", {})
        spelling = (term.get("stem", {}).get("$") or "") + (term.get("suff", {}).get("$") or "")
        return spelling.translate(MorphologicalAnalyzer._PLAIN_LETTERS).lower()

    @staticmethod
    def _spelled_like(form: str, spelling: str) -> bool | None:
        """Returns False when the spelling has v where the form has u, j where it has i, or the reverse, and True
        otherwise. When the spelling is shorter, it's compared with the form without an ending in OMITTED_TAILS.
        Returns None when neither has the spelling's length."""
        hosts = [form] + [form[:-len(tail)] for tail in MorphologicalAnalyzer.OMITTED_TAILS
                          if form.endswith(tail) and len(form) > len(tail)]
        host = next((host for host in hosts if len(host) == len(spelling)), None)
        return None if host is None else not any({letter, other} in ({"u", "v"}, {"i", "j"})
                                                 for letter, other in zip(host, spelling))

    @staticmethod
    def process_analysis(word: str, analysis: Dict, stripped_enclitic: str | None = None,
                         analyzed_as: str | None = None) -> tuple[List[Dict], List[Dict]]:
        """Process the analysis JSON and return details and inflections.
        analyzed_as is the word that Morpheus was asked for, when it isn't word.
        Raises when an analysis has no headword."""
        details = []
        inflections = []
        spellings_not_compared = set()

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

        rules_used: List[ReadingRule] = []
        rules_that_change_readings: List[ReadingRule] = []
        fields_changed: List[Tuple[ReadingRule, str]] = []

        # The analysis's place in Morpheus's answer, for the messages
        for original_item_index, body in enumerate(bodies):
            # Filters
            try:
                headword = body["rest"]["entry"]["dict"]["hdwd"]["$"]
                # Check IGNORED_DICT_REFS.
                ignored_for = IGNORED_DICT_REFS.get(headword)
                if ignored_for is not None and (not ignored_for or word in ignored_for):
                    logging.info(f"Ignoring form '{word}_{original_item_index}' due to unwanted dictionary reference '{headword}'.")
                    continue # Skip to the next body without incrementing final_item_index
            except KeyError as e:
                raise ValueError(f"Analysis {original_item_index} of '{word}' has no {e}") from e

            try:
                entry = body["rest"]["entry"]
                dict_info = entry["dict"]
                headword = dict_info["hdwd"]["$"].replace("^", "")
                headword = DICT_REF_REPLACEMENTS.get(headword, headword)

                infl_list = entry.get("infl", [])
                if not isinstance(infl_list, list):
                    infl_list = [infl_list]

                # Inflections spelled with other letters are skipped below, such as volvo's volv-it for voluit.
                spelled_like = {cnt: MorphologicalAnalyzer._spelled_like((analyzed_as or word).lower(),
                                                                          MorphologicalAnalyzer._spelling_of(infl))
                                for cnt, infl in enumerate(infl_list)}
                spellings_not_compared.update(MorphologicalAnalyzer._spelling_of(infl_list[cnt])
                                              for cnt, kept in spelled_like.items() if kept is None)
                if infl_list and not any(kept is not False for kept in spelled_like.values()):
                    logging.info(f"Ignoring '{headword}' for '{word}': every inflection is spelled with other letters")
                    continue

                pos_dict = dict_info.get("pofs", {}).get("$")

                # Strip a stripped enclitic before using the word for pos-of-speech heuristics
                if stripped_enclitic and len(word) > len(stripped_enclitic) and word.lower().endswith(stripped_enclitic):
                    lookup_word = word[:-len(stripped_enclitic)]
                else:
                    lookup_word = word

                item_inflections = []
                # Each reading a rule matches: the rule, the reading the script gave, and the readings it became
                readings_of_rules: List[Tuple[ReadingRule, Dict, List[Dict]]] = []

                for cnt, infl in enumerate(infl_list):
                    if spelled_like[cnt] is False:
                        logging.info(f"Ignoring inflection {cnt} of '{headword}' for '{word}': spelled with other letters")
                        continue
                    term = infl.get("term", {})
                    gender = infl.get("gend", {}).get("$")
                    pos_infl = infl.get("pofs", {}).get("$")
                    verb_form = infl.get("mood", {}).get("$")
                    gramm_case = infl.get("case", {}).get("$")
                    raw_suffix = term.get("suff", {}).get("$")
                    suffixes = [None] if raw_suffix is None else [
                        None if suffix == "*" else suffix for suffix in MorphologicalAnalyzer.spellings(raw_suffix)]
                    raw_stem = term.get("stem", {}).get("$")
                    stems = [stem.replace(":", "-") for stem in MorphologicalAnalyzer.spellings(raw_stem)]
                    # The grammar is the same in every spelling
                    suffix = suffixes[0]
                    decl = infl.get("decl", {}).get("$")
                    stem_type = infl.get("stemtype", {}).get("$")
                    degree = infl.get("comp", {}).get("$")
                    computed_pos = part_of_speech(pos_dict, pos_infl, verb_form, gender, suffix, gramm_case, degree, lookup_word)
                    if computed_pos == "new combination, check":
                        spelling = MorphologicalAnalyzer._spelling_of(infl)
                        logging.warning(f"'{word}': inflection {cnt} of {headword} ({spelling}) is {pos_infl!r} in an "
                                        f"entry that is {pos_dict!r}, a pair that part_of_speech has no rule for")
                    tense = infl.get("tense", {}).get("$")
                    inflection = {
                        # "form" filled in after the loop, once we know is_proper
                        "item": item,
                        "cnt": cnt,
                        "partOfSpeech": computed_pos,
                        "stem": stems[0],
                        "suffix": suffix,
                        # One inflection each, after the de-duplication below
                        "spellings": list(product(stems, suffixes)),
                        "segmentsInfo": segments_info(computed_pos, verb_form, tense, stem_type, suffix, degree,
                                                      lookup_word),
                        "gender": None if gender == "adverbial" else "neuter" if verb_form == "infinitive" else "masculine/feminine/neuter" if gender is None and decl == "3rd" else gender,
                        "number": "singular" if verb_form == "infinitive" else infl.get("num", {}).get("$"),
                        "declension": declension(computed_pos, decl, degree, verb_form, tense),
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

                    rule = MorphologicalAnalyzer._rule_for(word, headword, infl)
                    if rule is None:
                        item_inflections.append(inflection)
                        continue
                    rules_used.append(rule)
                    given = inflection.copy()
                    first = len(item_inflections)

                    override = rule.changes
                    if override is not None:
                        fields_changed.extend(
                            (rule, field) for field, value in override.items()
                            if set(value if isinstance(value, list) else [value]) != {inflection[field]})

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
                    readings_of_rules.append((rule, given, item_inflections[first:]))

                # A rule changes the item when its readings differ from those with the script's in place of the rule's
                readings = {MorphologicalAnalyzer._signature(i) for i in item_inflections}
                for rule in [rule for rule in FORMS if any(rule == used for used, _, _ in readings_of_rules)]:
                    made = [id(i) for used, _, became in readings_of_rules if used == rule for i in became]
                    script_readings = [reading for used, reading, _ in readings_of_rules if used == rule]
                    without = {MorphologicalAnalyzer._signature(i)
                               for i in [i for i in item_inflections if id(i) not in made] + script_readings}
                    if without != readings:
                        rules_that_change_readings.append(rule)

                # Judged on the inflections the item keeps, after overrides and exclusions. An interjection whose
                # headword is a name ("hercle" -> "Hercules") isn't proper, but a proper adjective ("Atticus") is
                contract_form = apply_contract_casing(
                    word, is_proper_item(headword, (i["partOfSpeech"] for i in item_inflections)))

                detail = {"form": contract_form, "item": item, "dictionaryRef": headword}
                details.append(detail)

                for inflection in item_inflections:
                    inflection["form"] = contract_form
                    inflections.append(inflection)

                item += 1
            except KeyError as e:
                raise ValueError(f"Analysis {original_item_index} of '{word}' has no {e}") from e

        # A word without readings is asked for again without its enclitic, so only one with readings is checked here
        rules_that_change_nothing = [(rule, RulesThatChangeNothing.NO_READING) for rule in FORMS
                                     if inflections and word in rule.words and rule not in rules_used]
        for rule in [rule for rule in FORMS if rule in rules_used]:
            unchanged = [field for field in rule.changes or {} if (rule, field) not in fields_changed]
            if rule not in rules_that_change_readings:
                rules_that_change_nothing.append((rule, "it changes none of the word's readings"))
            elif unchanged:
                rules_that_change_nothing.append(
                    (rule, f"every reading it matches has its {', '.join(unchanged)} already"))
        if rules_that_change_nothing:
            raise RulesThatChangeNothing(word, rules_that_change_nothing)

        if spellings_not_compared:
            logging.warning(f"'{word}' kept analyses whose letters weren't compared, review them: {sorted(spellings_not_compared)}")

        # De-duplication and re-indexing
        # The API sometimes returns the same grammatical inflection twice
        # with different stem notation. Collapse those (preferring the
        # hyphenated stem), give each kept one its spellings, then repack
        # 'cnt' with no gaps
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
                signature = MorphologicalAnalyzer._signature(infl)

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

            # Now that we have the final, de-duplicated list for this item in the correct order, make one
            # inflection per spelling of each (a duplicate that replaced one brings its own), re-index the 'cnt'
            # and add them to the final results.
            spelled = [{**infl, "stem": stem, "suffix": suffix}
                       for infl in ordered_unique_inflections for stem, suffix in infl["spellings"]]
            for new_cnt, final_infl in enumerate(spelled):
                final_infl.pop('spellings')
                final_infl['cnt'] = new_cnt
                final_inflections.append(final_infl)

        return details, final_inflections

    @staticmethod
    def _signature(infl: Dict) -> frozenset:
        """Returns an inflection's fields but those that vary for duplicates: its stem, cnt and spellings."""
        return frozenset((field, value) for field, value in infl.items() if field not in ("stem", "cnt", "spellings"))

    @staticmethod
    def _rule_for(word: str, headword: str, infl: Dict) -> ReadingRule | None:
        """Returns the rule in FORMS for one of Morpheus's inflections of word under headword, or None. Raises when
        several rules are for it."""
        rules = [rule for rule in FORMS if rule.headword == headword and (not rule.words or word in rule.words)
                 and all(infl.get(element, {}).get("$") == value for element, value in rule.match.items())]
        if len(rules) > 1:
            raise ValueError(f"'{word}': an inflection of {headword} has {len(rules)} rules in FORMS: {rules}")
        return rules[0] if rules else None

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
                writer = csv.DictWriter(f, fieldnames=details_fieldnames, lineterminator="\n")
                if not details_exists:
                    writer.writeheader()

                writer.writerows(details)

            # Write inflections
            inflections_exists = os.path.exists(self.inflections_file)

            with open(self.inflections_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=inflections_fieldnames, lineterminator="\n")

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
        """Process all words from the input file, with retries for enclitics. After the last word, raises when a word
        has no analysis written: when Morpheus couldn't be asked or its answer couldn't be read, or when every analysis
        was dropped."""
        details: list[dict]
        inflections: list[dict]
        reasons_by_word_without_analysis: Dict[str, str] = {}
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
                details, inflections = self.process_analysis(word, analysis, analyzed_as=word_for_analysis)

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
                            retry_details, retry_inflections = self.process_analysis(word, retry_analysis, stripped_enclitic=enclitic,
                                                                                     analyzed_as=word_for_analysis)

                            if retry_inflections:
                                details = retry_details
                                inflections = retry_inflections
                                break  # Success, exit enclitic loop

                rules_that_change_nothing = [(rule, RulesThatChangeNothing.NO_READING) for rule in FORMS
                                             if word in rule.words]
                if not inflections and rules_that_change_nothing:
                    raise RulesThatChangeNothing(word, rules_that_change_nothing)

                # After all attempts, write the result (success, retry-success, or failure)
                if details:
                    self.write_results(word, details, inflections)
                    if inflections:
                        logging.info(f"Successfully processed word: {word}")
                    else:
                        logging.warning(f"No analysis found for '{word}', stored as unknown.")
                else:
                    logging.warning(f"No analysis results for word: {word}")
                    reasons_by_word_without_analysis[word] = "every analysis was dropped"

            except requests.RequestException as e:
                logging.error(f"API request error for word '{word}': {str(e)}. Will retry next run.")
                reasons_by_word_without_analysis[word] = str(e)
                continue
            except Exception as e:
                logging.error(f"Error processing word '{word}': {str( e )}")
                reasons_by_word_without_analysis[word] = str(e)
                continue

        logging.info(
            f"Finished processing words. Total processed: {len( self.processed_forms )}"
        )
        if reasons_by_word_without_analysis:
            raise WordsWithoutAnalysis(reasons_by_word_without_analysis)

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


def declension( computed_pos:str, decl_tag:str, degree:str | None, verb_form:str, verb_tense:str ) -> str | None:
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
    # Morpheus gives a comparative built on its positive's stem the positive's declension: firmiores is 1st & 2nd
    elif computed_pos in ["noun","adjective"] and degree == "comparative":
        return "3rd"
    elif computed_pos in ["noun","adjective"] and degree == "superlative":
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


#: The segments of a superlative by the ending in its suffix, such as the errim of pulcherrime
SUPERLATIVE_SEGMENTS = {
    "issim": "issimus, -issima, -issimum",
    "issum": "issumus, -issuma, -issumum",
    "errim": "errimus, -errima, -errimum",
}


def segments_info(
    computed_pos: str,
    verb_form: str,
    verb_tense: str,
    stemtype_tag: str,
    suffix: str | None,
    degree: str | None,
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

    # A comparative or superlative with a stem of its own, such as the meli- of melior or the optim- of optimus, keeps
    # its stem type's segments
    if degree == "comparative" and not stemtype_tag.endswith("_comp"):
        degree_segments = "ior, -ius"
    elif degree == "superlative":
        degree_segments = next((segments for ending, segments in SUPERLATIVE_SEGMENTS.items()
                                if suffix is not None and ending in suffix), None)
    else:
        degree_segments = None

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
                elif degree_segments is not None:
                    return degree_segments
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
            elif degree_segments is not None:
                return degree_segments
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
        """Runs all validation checks on the inflections file. Raises when a file is missing or a check finds an
        issue."""
        logging.info(f"Starting validation of morphological data in '{self.file_path}'...")
        for path in (self.file_path, self.details_path):
            if not os.path.exists(path):
                raise FileNotFoundError(f"Validation failed: '{path}' not found")

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
            raise ValidationFailed(self.warning_count)

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
        """A form is capitalized exactly when its item is proper: a capitalized headword with a noun or adjective
        inflection. Catches 'Hercle' capitalized (an interjection whose headword is Hercules) and a proper adjective
        like 'atticus' left lowercase."""
        refs: Dict[Tuple[str, str], str | None] = {}
        with open(self.details_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                refs[(row['form'], row['item'])] = row.get('dictionaryRef')

        groups: Dict[Tuple[str, str], List[str | None]] = {}
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                groups.setdefault((row['form'], row['item']), []).append(row.get('partOfSpeech'))

        for (form, item), pos_list in groups.items():
            ref = refs.get((form, item))
            is_capitalized = bool(form) and form[0].isupper()
            if is_capitalized != is_proper_item(ref, pos_list):
                self._log_warning(0, 'casing', form,
                                  f"item {item}: {'capitalized' if is_capitalized else 'lowercase'} but headword "
                                  f"'{ref}' with pos {pos_list} says otherwise.")

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

_LONG_VOWELS = frozenset("āēīōūȳĀĒĪŌŪȲ")
_VOWELS = _LONG_VOWELS | frozenset("aeiouyAEIOUY")


class Reading(NamedTuple):
    spelling: str
    lemma: str


class RuledOutReadings(NamedTuple):
    """The readings that the macronizer's certain vowels rule out, in the library's word tokens. A reading is ruled out
    when its spelling has the other length at one of them, as tibī is for the text's tibi."""
    #: The tokens whose every reading is ruled out, by their macronization in lowercase
    every_reading: Dict[str, List[str]]
    #: The tokens that rule out a reading, by the reading
    by_reading: Dict[Reading, List[str]]


def _rules_out(spelling: str, macronized: str, certain_vowels: List[int]) -> bool:
    """Whether the spelling has as many letters as the macronized word, and the other length at one of its certain
    vowels."""
    return len(spelling) == len(macronized) and any(
        (spelling[i] in _LONG_VOWELS) != (macronized[i] in _LONG_VOWELS) for i in certain_vowels)


def readings_ruled_out_by_certain_vowels(library_dir: Path, details_path: Path,
                                         inflections_path: Path) -> RuledOutReadings:
    """Returns the readings that certain vowels rule out, with the tokens that rule them out, each as its work's name
    and its reference. The tokens are the words and those with an expansion, which is certain, and they get the
    macronizations and readings that the reader gives them, before any reading is ruled out. A reading's spelling has
    back an ending that Morpheus leaves out of it, such as an enclitic, and a spelling with more or fewer letters than
    the token rules nothing out."""
    with open(details_path, encoding="utf-8") as f:
        lemmas = {(row["form"], row["item"]): row["dictionaryRef"] for row in csv.DictReader(f)}
    readings_by_form: Dict[str, List[Reading]] = {}
    with open(inflections_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            spelling = row["stem"].replace("-", "") + row["suffix"]
            ending = row["form"][len(spelling):]
            readings_by_form.setdefault(row["form"], []).append(
                Reading(spelling + ending if ending.lower() in MorphologicalAnalyzer.OMITTED_TAILS else spelling,
                        lemmas[(row["form"], row["item"])]))
    with open(library_dir / "works.csv", encoding="utf-8") as f:
        work_names = {row["id"]: row["name"] for row in csv.DictReader(f)}
    with open(library_dir / "unambiguous_macronizations.csv", encoding="utf-8") as f:
        unambiguous_macronizations = {row["word"]: row["macronizedWord"] for row in csv.DictReader(f)}
    with open(library_dir / "work_macronizations.csv", encoding="utf-8") as f:
        work_macronizations = {(row["workId"], row["idx"]): (row["macronizedWord"], int(row["uncertaintyBitMask"]))
                               for row in csv.DictReader(f)}

    ruled_out = RuledOutReadings({}, {})
    with open(library_dir / "work_contents.csv", encoding="utf-8") as f:
        for token in csv.DictReader(f):
            expansion = token["expansion"]
            if not expansion and token["tokenType"] != str(TokenType.WORD.value):
                continue
            state = int(token["properNounState"]) if token["properNounState"] else None
            if expansion:
                word, macronized, mask = strip_macrons(expansion), expansion, 0
            else:
                word = token["word"]
                key = lookup_key(word, TokenType.WORD, state, unambiguous_macronizations)
                macronized, mask = work_macronizations.get(
                    (token["workId"], token["idx"]),
                    (unambiguous_macronizations[key], 0) if key is not None else (word, -1))
            # A name's readings are under the capitalized word, other words' under the lowercase one, and a word that
            # can be either has both
            forms = {*([word.capitalize()] if state in (ProperNounState.YES, ProperNounState.EITHER) else []),
                     *([word.lower()] if state != ProperNounState.YES else [])}
            readings = {reading for form in forms for reading in readings_by_form.get(form, [])}
            certain_vowels = [i for i, letter in enumerate(macronized) if letter in _VOWELS and (mask >> i) & 1 == 0]
            ruled_out_readings = {reading for reading in readings
                                  if _rules_out(reading.spelling, macronized, certain_vowels)}
            reference = f"{work_names[token['workId']]} {token['sourceReference']}"
            for reading in ruled_out_readings:
                ruled_out.by_reading.setdefault(reading, []).append(reference)
            if readings and ruled_out_readings == readings:
                ruled_out.every_reading.setdefault(macronized.lower(), []).append(reference)
    return ruled_out


def _log_by_token_count(references_by_key: Dict[str, List[str]]):
    """Logs each key with how many tokens it has, the most first, and the references of the first three."""
    for key, references in sorted(references_by_key.items(), key=lambda item: (-len(item[1]), item[0])):
        logging.info(f"  {key}: {len(references)}, such as {', '.join(list(dict.fromkeys(references))[:3])}")


def analyze(project_root: str):
    """Adds the analyses of the library's new words to the output files when every word gets one and they pass
    validation. Otherwise raises, and the output files stay as they were. Doesn't start while a publication of the
    library didn't finish or left a file it replaced. Then logs the readings that the macronizer's certain vowels rule
    out."""
    raise_for_publication_leftovers(Path(project_root) / "output" / "library")
    output_dir = Path(project_root) / "output" / "morphological_analysis"
    with tempfile.TemporaryDirectory() as working_dir:
        for path in output_dir.glob("*.csv"):
            shutil.copyfile(path, Path(working_dir) / path.name)
        analyzer = MorphologicalAnalyzer(project_root, working_dir)
        analyzer.process_words()
        MorphologicalDataValidator(analyzer.inflections_file, analyzer.details_file).validate()
        publish(Path(working_dir), output_dir)

    library_dir = Path(project_root) / "output" / "library"
    files = ("works.csv", "unambiguous_macronizations.csv", "work_macronizations.csv")
    if all((library_dir / name).exists() for name in files):
        ruled_out = readings_ruled_out_by_certain_vowels(library_dir, output_dir / "morphological_details.csv",
                                                         output_dir / "morphological_detail_inflections.csv")
        logging.info(f"{sum(map(len, ruled_out.every_reading.values()))} word tokens have certain vowels that rule out "
                     f"every reading, by their macronization")
        _log_by_token_count(ruled_out.every_reading)
        logging.info(f"{len(ruled_out.by_reading)} readings are ruled out by the certain vowels of some tokens, by "
                     f"their spelling and lemma")
        _log_by_token_count({f"{reading.spelling} ({reading.lemma})": references
                             for reading, references in ruled_out.by_reading.items()})
    else:
        logging.warning(f"The macronizations weren't checked against the readings: {library_dir} has no "
                        f"{', '.join(files)}")


def main():
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        analyze(project_root)
        logging.info("Morphological analysis processing complete.")

    # What's wrong is in the data, not the code, so it's said without a traceback
    except ValidationFailed as failure:
        logging.error(f"Nothing was saved: validation found {failure.issues} issues, listed above. Their line numbers "
                      f"are of the files that weren't kept. The output files are as they were.")
        sys.exit(1)
    except WordsWithoutAnalysis as failure:
        logging.error(f"Nothing was saved: {failure}. The output files are as they were.")
        sys.exit(1)
    except Exception as e:
        logging.critical(f"Critical error in main execution: {str( e )}")
        raise


if __name__ == "__main__":
    main()