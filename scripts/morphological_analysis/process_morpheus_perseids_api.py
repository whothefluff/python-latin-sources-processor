import csv
import os
import requests
import logging
from typing import Dict, List, Set, TextIO

from scripts.morphological_analysis.process_morpheys_perseids_api_aux.overrides import (
    FORMS, NOT_WANTED_INFLECTIONS,
)


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
                    self.processed_forms = {row["form"] for row in reader}
                logging.info(
                    f"Loaded {len(self.processed_forms)} existing processed forms"
                )
            except Exception as e:
                logging.error(f"Error loading existing forms: {str(e)}")
                raise

    def collect_unique_words(self):
        """Collect unique words from the input file"""
        try:
            with open(self.input_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Since the API doesn't handle proper nouns anyway, treat all words as lower case to avoid duplicates
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
            url = f"http://localhost:1501/analysis/word"
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
    def process_analysis(word: str, analysis: Dict) -> tuple[List[Dict], List[Dict]]:
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
        for body in bodies:
            if "rest" not in body:
                continue

            try:
                entry = body["rest"]["entry"]
                dict_info = entry["dict"]
                headword = dict_info["hdwd"]["$"]

                detail = {"form": word, "item": item, "dictionaryRef": headword}
                details.append(detail)

                infl_list = entry.get("infl", [])
                if not isinstance(infl_list, list):
                    infl_list = [infl_list]

                pos_dict = dict_info.get("pofs", {} ).get("$")

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
                    computed_pos = part_of_speech(pos_dict, pos_infl, verb_form, gender, suffix, gramm_case, word)
                    tense = infl.get("tense", {}).get("$")
                    inflection = {
                        "form": word,
                        "item": item,
                        "cnt": cnt,
                        "partOfSpeech": computed_pos,
                        "stem": MorphologicalAnalyzer.macronize(term.get("stem", {}).get("$")).replace(":", "-"),
                        "suffix": suffix,
                        "segmentsInfo": segments_info(computed_pos, verb_form, tense, stem_type, suffix),
                        "gender": None if gender == "adverbial" else "neuter" if verb_form == "infinitive" else "masculine/feminine/neuter" if gender is None and decl == "3rd" else gender,
                        "number": "singular" if verb_form == "infinitive" else infl.get("num", {}).get("$"),
                        "declension": declension( computed_pos, decl, suffix, verb_form, tense ),
                        "case": "nominative/vocative" if gramm_case is None and suffix == "er" and stem_type == "er_eris" else gramm_case,
                        "verbForm": verb_form,
                        "tense": tense,
                        "voice": infl.get("voice", {}).get("$"),
                        "person": infl.get("pers", {}).get("$"),

                        # uncomment during development
                        #"stem_type": stem_type,
                        #"pos_dict": pos_dict,
                        #"pos_infl": pos_infl,
                        #"gend": gender,
                    }

                    key = f"{word}_{item}_{cnt}"
                    if key in FORMS:
                        inflection.update( FORMS[key] )
                    if key in NOT_WANTED_INFLECTIONS:
                        continue
                    else:
                        inflections.append(inflection)

                item += 1
            except KeyError as e:
                logging.error(f"Error processing analysis for word '{word}': {str(e)}")
                continue

        return details, inflections


    def write_results(self, details: List[Dict], inflections: List[Dict]):
        """Write results to CSV files"""
        try:
            details_fieldnames = ["form", "item", "dictionaryRef"]
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
                # noinspection PyTypeChecker
                writer = csv.DictWriter[TextIO](f, fieldnames=details_fieldnames)
                if not details_exists:
                    writer.writeheader()
                writer.writerows(details)

            # Write inflections
            inflections_exists = os.path.exists(self.inflections_file)
            with open(self.inflections_file, "a", newline="", encoding="utf-8") as f:
                # noinspection PyTypeChecker
                writer = csv.DictWriter(f, fieldnames=inflections_fieldnames)
                if not inflections_exists:
                    writer.writeheader()
                writer.writerows(inflections)

        except Exception as e:
            logging.error(f"Error writing results: {str(e)}")
            raise

    def process_words(self):
        """Process all words from the input file"""
        words_to_process = self.unique_words - self.processed_forms
        logging.info(f"Starting to process {len( words_to_process )} new words")

        for word in words_to_process:
            logging.debug(f"Processing word: {word}")
            try:
                analysis = self.analyze_word(word)
                details, inflections = self.process_analysis(word, analysis)

                if details:
                    self.write_results(details, inflections)
                    self.processed_forms.add(word)
                    logging.info(f"Successfully processed word: {word}")
                else:
                    logging.warning(f"No analysis results for word: {word}")

            except Exception as e:
                logging.error(f"Error processing word '{word}': {str( e )}")
                continue

        logging.info(
            f"Finished processing words. Total processed: {len( self.processed_forms )}"
        )


def part_of_speech(pos_dict, pos_infl, verb_form, gender, suffix, case, form) -> str:
    """
    The service ignore the fact that gerund exists, so there's that

    Some adjectives like *fallaci* don't have gender, so there's that

    I suspect some comparatives are broken in such a way that a form from a 1st & 2nd declension will not show the actual declension of the comparative form (*notior* for *notus*), so there's that

    :param pos_dict: pofs tag
    :param pos_infl: infl.pofs tag
    :param verb_form: mood tag
    :param gender: gend tag
    :param suffix: suff tag
    :param case: case tag
    :param form: the word
    :return: a normalized part of speech
    """

    # adjective first
    if pos_dict == "adjective":
        if case is None and ( gender == "adverbial"
                              or suffix in ["ē", "ius", "ter", "issimē"]
                              or form.endswith(("e", "ius", "ter", "issime"))):
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
        if case is None and gender == "adverbial":
            return "adverb"
        else:
            if pos_infl == "noun":
                return "noun"
            elif pos_infl == "adjective":
                return "adjective"
            elif pos_infl == "verb":
                return "verb"
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
        else:
            return "new combination, check"

    # pronoun first
    elif pos_dict == "pronoun":
        if pos_infl == "pronoun":
            return "pronoun"
        else:
            return "new combination, check"

    # verb first
    elif pos_dict == "verb":
        if verb_form is None:
            if gender == "adverbial":
                return "adverb"
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


def declension( computed_pos:str, decl_tag:str, suffix:str, verb_form:str, verb_tense:str ) -> str:
    if verb_form == "gerundive":
        return "1st & 2nd"
    elif verb_form == "participle":
        if verb_tense == "present":
            return "3rd"
        elif verb_tense in ["perfect", "future"]:
            return "1st & 2nd"
    elif verb_form == "supine":
        return "4th"
    elif computed_pos in ["noun","adjective"] and suffix is not None and ( suffix.find("ior") != -1 or suffix.find("ius") != -1 ):
        return "3rd"
    elif computed_pos in ["noun","adjective"] and suffix is not None and suffix.find("issim") != -1:
        return "1st & 2nd"
    else:
        return decl_tag


def segments_info( computed_pos: str, verb_form: str, verb_tense: str, stemtype_tag: str, suffix: str ) -> str:

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
            if verb_form is None:
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

        elif computed_pos == "new combination, check":
            return "new combination, check"


def main():
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        analyzer = MorphologicalAnalyzer(project_root)
        analyzer.process_words()
    except Exception as e:
        logging.critical(f"Critical error in main execution: {str( e )}")
        raise


if __name__ == "__main__":
    main()
