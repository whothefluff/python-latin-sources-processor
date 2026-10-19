# "Ambiguous"/"ambiguity" is and should always be reserved exclusively for doubtful macronizations,
# both in comments and code. Any other kind of uncertainty should be described with different words

import base64
import json
import logging
import os
import re
import tempfile
import uuid
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import cache
from pathlib import Path
from typing import Dict, FrozenSet, List, NamedTuple, Sequence, Set, Tuple, TypedDict, cast

import pandas as pd

import requests
from scripts.common.macrons import strip_macrons
from scripts.common.publishing import publish
from scripts.common.services import MACRONIZER_URL, MORPHEUS_URL
from scripts.library.util.nomina import NOMINA
from scripts.library.util.proper_noun import (
    is_proper_noun_lemma, compute_inherent_state, compute_context_aware_state, ProperNounState,
)
from scripts.library.util.spelling import (
    LetterConvention, differs_in_told_apart_letters, respell, respell_macronized, spellings_of, token_spellings_of,
)
from scripts.library.util.tei_edition import TEI_NAMESPACE, Division, LostPassage, TextBlock, read_edition
from scripts.library.util.text_normalization import normalize_digraphs
from scripts.library.util.token_classification import TokenType, get_token_type
from scripts.library.util.unambiguous_macronizations import (
    CertainToken, WorkMacronization, agreed_macronizations, lookup_key, work_macronizations_where_lookup_differs,
)

# Enclitics split off into the `enclitic` column; deliberately a subset of Morpheus' LatinSuff
SPLIT_ENCLITICS: list[str] = ["que", "ne", "ve", "ue", "dum"]

KNOWN_ABBREVIATIONS: set[str] = {
    *NOMINA.keys()
}

# A text splits into words and single punctuation marks
_SEGMENT_PATTERN = r'\w+|[^\w\s]'

#: Each known abbreviation as the segments that the text splits it into, such as M and ' for M'
_ABBREVIATION_SEGMENTS: FrozenSet[Tuple[str, ...]] = frozenset(
    tuple(re.findall(_SEGMENT_PATTERN, abbreviation)) for abbreviation in KNOWN_ABBREVIATIONS)

CAPITALIZATION_RESET_PUNCTUATION = ".!?:—"

# Punctuation that ends a grammatical sentence for sentenceIdx/wordIdx purposes.
# Deliberately narrower than the CAPITALIZATION_RESET_PUNCTUATION set: a colon
# introduces a clause, it doesn't end a sentence.
SENTENCE_TERMINATORS = ".!?"


class WorkConfiguration(NamedTuple):
    """The settings of a work's processing that depend on its edition: how it cites its text, the letters that it
    prints, the corrections that its tokens need, and its author's abbreviations, about texts and image"""
    #: The TEI subtypes of the divisions whose n is part of their tokens' references, as the edition cites them
    cited_division_subtypes: Tuple[str, ...]
    #: The subdivision types of the poems whose n isn't a poem's, such as prologus
    poem_types_by_n: Dict[str, str]
    letter_convention: LetterConvention
    #: Token types by token index, where the script's own would be wrong
    token_overrides: Dict[int, TokenType]
    #: Expansions of abbreviations and numerals, by token index
    expansions: Dict[int, str]
    #: Proper-noun states by token index, where the script's own would be wrong
    proper_noun_overrides: Dict[int, ProperNounState | None]
    author_abbreviations: Tuple[str, ...]
    work_about_file: str
    author_about_file: str
    author_image_file: str


logging.basicConfig(level=logging.INFO)


def _parsed_morpheus_answer(xml_string: str) -> ET.Element:
    """Returns Morpheus's answer as XML. Raises when it isn't XML, or when it's an error, which the API only sends for
    an unknown engine or language. A word that Morpheus doesn't know gets an answer without analyses."""
    root = ET.fromstring(xml_string)
    if root.tag == 'error':
        raise ValueError(f"Morpheus answered with an error: '{root.text if root.text is not None else 'None'}'")
    return root


def _extract_lemmas_from_morpheus_xml(xml_string: str) -> List[str]:
    """Parses the XML output from the morpheus endpoint to extract lemmas."""
    lemmas = []
    root = _parsed_morpheus_answer(xml_string)
    # Find all headwords (hdwd), which contain the lemma
    for hdwd_element in root.findall('.//hdwd'):
        if hdwd_element.text:
            lemmas.append(hdwd_element.text.strip())
    return list(set(lemmas)) # Return unique lemmas


def _is_valid_dum_stem(xml_string: str) -> bool:
    """
    Parses Morpheus XML to check if a word is an imperative, interjection, or adverb.
    This is used to validate if 'dum' is acting as a clitic.
    """
    root = _parsed_morpheus_answer(xml_string)
    # Find all inflection blocks (<infl>)
    for infl_element in root.findall('.//infl'):
        # Check for <mood>imperative</mood>
        mood = infl_element.find('mood')
        if mood is not None and mood.text == 'imperative':
            return True

        # Check for <pofs>exclamation</pofs> or <pofs>adverb</pofs>
        pofs = infl_element.find('pofs')
        if pofs is not None and pofs.text in ['exclamation', 'adverb']:
            return True
    return False


def _surface_forms(xml_string: str) -> Set[str]:
    """Returns each inflection's stem and suffix as one spelling, lowercase and without Morpheus's marks: _ and ^ for
    vowel length, : after a compound's prefix (ob:jurg) and * for an empty suffix (vir)."""
    surfaces = set()
    for term in _parsed_morpheus_answer(xml_string).findall('.//term'):
        stem = term.findtext('stem') or ''
        suff = term.findtext('suff') or ''
        surface = re.sub(r'[_^:*\-]', '', (stem + suff)).lower()
        if surface:
            surfaces.add(surface)
    return surfaces


class MorpheusAnswer(NamedTuple):
    """Morpheus's answer to one query"""
    lemmas: FrozenSet[str]
    #: The analyzed forms, lowercase and without macrons. They leave out the enclitic when Morpheus splits one off.
    surfaces: FrozenSet[str]
    #: Whether an inflection is an imperative, an interjection or an adverb, which dum can follow
    dum_can_follow: bool


_NO_ANSWER = MorpheusAnswer(frozenset(), frozenset(), False)


def _any_surface_spells(word: str, surfaces: FrozenSet[str], convention: LetterConvention) -> bool:
    return bool(spellings_of(word, surfaces, convention))


@cache
def _lookup(word: str) -> MorpheusAnswer:
    """Asks Morpheus for the word once, with strictCase: a capitalized word gets no analysis when all its forms are
    lowercase, and the other way round. Raises when the request fails, or when the answer is an error or isn't XML, so
    that nothing is cached for the word"""
    if not word or not word.isalpha():
        return _NO_ANSWER

    params = {"lang": "lat", "engine": "morpheuslat", "word": word, "strictCase": str(int(True))}
    headers = {"Accept": "application/xml"}
    try:
        response = requests.get(MORPHEUS_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logging.error("Error calling morpheus API for word '%s'", word)
        raise

    lemmas = frozenset(_extract_lemmas_from_morpheus_xml(response.text))
    if not lemmas:
        return _NO_ANSWER
    return MorpheusAnswer(lemmas, frozenset(_surface_forms(response.text)), _is_valid_dum_stem(response.text))


class _Analysis(Enum):
    WHOLE = auto()
    SPLIT = auto()
    NONE = auto()


def _analysis_of(word: str, answer: MorpheusAnswer, convention: LetterConvention) -> Tuple[_Analysis, str | None]:
    """Says whether the answer analyzes the whole word, or the word without an ending of SPLIT_ENCLITICS that Morpheus
    split off, and which one, or neither. A dum split counts only when dum can follow the host. An answer that no
    spelling lines up with, such as one for an assimilated prefix (affert), is the whole word."""
    if not answer.lemmas:
        return _Analysis.NONE, None
    lower = word.lower()
    if answer.surfaces and not _any_surface_spells(lower, answer.surfaces, convention):
        for ending in SPLIT_ENCLITICS:
            if lower.endswith(ending) and _any_surface_spells(lower[:-len(ending)], answer.surfaces, convention):
                if ending == "dum" and not answer.dum_can_follow:
                    return _Analysis.NONE, None
                return _Analysis.SPLIT, ending
    return _Analysis.WHOLE, None


def _host_answer(word: str, enclitic: str) -> MorpheusAnswer:
    """Returns Morpheus's answer for the word without the enclitic, in the word's case.
    For Morpheus builds that don't strip enclitics themselves, e.g. with a4d8f61 applied"""
    host = word[:-len(enclitic)]
    logging.warning("Analysis for '%s' was empty. Retrying with stem '%s'.", word, host)
    answer = _lookup(host)
    if not answer.lemmas or (enclitic == "dum" and not answer.dum_can_follow):
        return _NO_ANSWER
    logging.warning("'%s'-'%s' found", host, enclitic)
    return answer


class MorpheusReading(NamedTuple):
    """What Morpheus says about a word, whatever its case and place in the text"""
    enclitic: str | None
    #: What counts for the word in lowercase: the answer for the word, or for its host when there's an enclitic
    lowercase: MorpheusAnswer
    #: The same for the word capitalized
    capitalized: MorpheusAnswer


_NO_READING = MorpheusReading(None, _NO_ANSWER, _NO_ANSWER)


@cache
def _morpheus_reading(lower: str, convention: LetterConvention) -> MorpheusReading:
    """Asks Morpheus for the lowercase word and the word capitalized. Then:
    1. When either answer is the whole word, there's no enclitic, and a split in the other is dropped: Iove is
       Juppiter, not io and ve.
    2. Otherwise, when either is a split, that's the enclitic, the lowercase one first. A case without an analysis gets
       its host's, since a capitalized host can be a name that the lowercase split doesn't show.
    3. Otherwise, the word without its ending of SPLIT_ENCLITICS is asked for in both cases, and the ending is the
       enclitic when either answers."""
    if not lower.isalpha():
        return _NO_READING
    words = (lower, lower.capitalize())
    answers = tuple(_lookup(word) for word in words)
    analyses = tuple(_analysis_of(word, answer, convention) for word, answer in zip(words, answers))

    if any(analysis is _Analysis.WHOLE for analysis, _ in analyses):
        return MorpheusReading(None, *(answer if analysis is _Analysis.WHOLE else _NO_ANSWER
                                       for answer, (analysis, _) in zip(answers, analyses)))

    splits = [ending for analysis, ending in analyses if analysis is _Analysis.SPLIT]
    enclitic = splits[0] if splits else next((ending for ending in SPLIT_ENCLITICS if lower.endswith(ending)), None)
    if enclitic is None or enclitic == lower:
        return _NO_READING
    answers = tuple(answer if analysis is _Analysis.SPLIT else _host_answer(word, cast(str, enclitic))
                    for word, answer, (analysis, _) in zip(words, answers, analyses))
    if not any(answer.lemmas for answer in answers):
        return _NO_READING
    return MorpheusReading(enclitic, *answers)


def find_enclitic(word_to_analyze: str, convention: LetterConvention) -> str | None:
    """Returns the enclitic that Morpheus splits off the word in either case, from the lowercase answer first"""
    return _morpheus_reading(word_to_analyze.lower(), convention).enclitic


def morpheus_surfaces(word: str, convention: LetterConvention) -> FrozenSet[str]:
    """Returns Morpheus's spellings of the word (stem and suffix, lowercase, without macrons)"""
    reading = _morpheus_reading(word.lower(), convention)
    return reading.lowercase.surfaces | reading.capitalized.surfaces


def spelled_with_morpheus_letters(word: str, convention: LetterConvention) -> str:
    return respell(word, find_enclitic(word, convention), morpheus_surfaces(word, convention), convention)


def _title_spelled_like_its_tokens(title: str, tokens: List[list], convention: LetterConvention) -> str:
    spellings: Dict[str, str] = {token[2]: spelled_with_morpheus_letters(token[2], convention)
                                 for token in tokens if token[5] == TokenType.WORD}

    def spelled_like_its_token(word: re.Match[str]) -> str:
        return spellings.get(word[0], word[0])

    return re.sub(r'\w+', spelled_like_its_token, title)


def project_display_casing(original: str, macronized: str) -> str:
    """

    :param original:
    :param macronized:
    :return:
    """
    if not original:
        return macronized
    # ALL CAPS
    if original == original.upper() and len(original) > 1:
        return macronized.upper()
    # Title Case
    if original[0].isupper() and original[0] != original[0].lower():
        return macronized[0].upper() + macronized[1:].lower()
    # lowercase
    if original == original.lower():
        return macronized.lower()
    # passthrough
    return macronized


def apply_norm_casing(text: str, proper_noun_state) -> str:
    """

    :param text:
    :param proper_noun_state:
    :return:
    """
    if not text:
        return text
    if proper_noun_state in (1, 2):
        return text[0].upper() + text[1:].lower()
    return text.lower()


@cache
def determine_proper_noun_state(word_in_text: str, is_sentence_start: bool, prev_word_was_capitalized: bool,
                                convention: LetterConvention) -> Tuple[ProperNounState | None, ProperNounState | None]:
    """
    Determines both the inherent (based only on dictionary lookups) and context-aware
    (using sentence start and capitalization sequences) proper noun states for a word.

    It handles consecutive capitalized words as a sequence, aligning with *macronizer* logic.

    Returns: A tuple of (inherent_state, context_aware_state) or None for non-alphabetic
    tokens or words that cannot be analyzed at all
    """
    if not word_in_text or not word_in_text.isalpha():
        return None, None

    word_is_capitalized = word_in_text[0].isupper()

    # Perform dictionary lookups. This part is PURE and based only on
    # word forms, completely independent of context.
    reading = _morpheus_reading(word_in_text.lower(), convention)
    analyses_lower = reading.lowercase.lemmas
    analyses_upper = reading.capitalized.lemmas

    # A word has a common form if its lowercase analysis returns anything,
    # OR if its capitalized analysis contains a lowercase lemma.
    # Check analysis for 'hercle' which has lemma Hercules
    has_common_word_analysis = bool(analyses_lower) or any(not is_proper_noun_lemma(lemma) for lemma in analyses_upper)

    # A word has a proper form if its capitalized analysis contains a capitalized lemma.
    has_proper_noun_analysis = any(is_proper_noun_lemma(lemma) for lemma in analyses_upper)

    inherent_state = compute_inherent_state(has_common_word_analysis, has_proper_noun_analysis)

    # Capitalization is "forgivable" if it's at the start of a sentence OR part of a capitalized sequence.
    is_forgivable_context = is_sentence_start or prev_word_was_capitalized
    context_aware_state = compute_context_aware_state(inherent_state, word_is_capitalized, is_forgivable_context)

    return inherent_state, context_aware_state


class TokenResult(TypedDict):
    word: str
    is_word: bool
    macronized: str
    uncertainty_mask: int
    candidates: list[str]


def macronize_text(text: str) -> List[TokenResult]:
    """
    Calls the local macronization API to get macronization data for a given text.
    Raises when the request fails.
    """
    payload = {"text": text, "clean": False}
    headers = {"Content-Type": "application/json"}
    try:
        # Set a generous timeout as macronizing a large text can take time
        response = requests.post(MACRONIZER_URL, data=json.dumps(payload), headers=headers, timeout=300)
        response.raise_for_status()
        results = response.json().get('results', [])
        for res in results:
            if 'macronized' in res and res['macronized']:
                res['macronized'] = normalize_digraphs(res['macronized'])

        return results

    except requests.exceptions.RequestException:
        logging.error("Error calling macronization API")
        raise


def _process_text_segments(
        segments: List[str],
        work_id: str,
        fragment_index: int,
        sentence_idx: int,
        word_idx: int,
        source_ref: str,
        is_capitalization_forgivable: bool,
        starts_new_sentence: bool,
        work_contents_data: List,
        inherent_states_map: Dict[str, ProperNounState | None],
        work: WorkConfiguration,
) -> Tuple[int, int, int, bool, bool]:
    """
    Two independent context flags are threaded through, on purpose:

    - is_capitalization_forgivable: poetic convention capitalizes a line's first
      word regardless of grammar. Reset by the caller at the start of every
      line/head. Only feeds the proper-noun heuristic.
    - starts_new_sentence: real sentence boundary, driven only by actual
      terminal punctuation (plus a forced reset at book/poem starts). NOT reset
      per verse line — Latin verse sentences routinely run over several lines.
    """
    prev_word_was_capitalized = False

    for segment in segments:

        if starts_new_sentence:
            sentence_idx += 1
            word_idx = 0
            starts_new_sentence = False

        inherent_state, context_dependent_state = determine_proper_noun_state(
            segment, is_capitalization_forgivable, prev_word_was_capitalized, work.letter_convention
        )

        t_type = get_token_type(segment, inherent_state)
        t_type = work.token_overrides.get(fragment_index, t_type)

        if t_type == TokenType.ABBREVIATION:
            context_dependent_state = ProperNounState.YES
        elif t_type == TokenType.NUMERAL:
            context_dependent_state = ProperNounState.NO

        context_dependent_state = work.proper_noun_overrides.get(fragment_index, context_dependent_state)

        current_word_idx = None
        if t_type <= 3:
            current_word_idx = word_idx
            word_idx += 1

        enclitic = None
        expansion = None
        if t_type == TokenType.WORD:
            enclitic = find_enclitic(segment, work.letter_convention)
        elif t_type in (TokenType.ABBREVIATION, TokenType.NUMERAL):
            expansion = work.expansions.get(fragment_index)

        work_contents_data.append([
            work_id, fragment_index, segment, source_ref, context_dependent_state,
            int(t_type), sentence_idx, current_word_idx, enclitic, expansion,
        ])

        if t_type == TokenType.WORD:
            inherent_states_map[segment.lower()] = inherent_state
        if t_type <= 3:
            prev_word_was_capitalized = segment[0].isupper()
            is_capitalization_forgivable = False
        else:
            prev_word_was_capitalized = False

        if t_type == TokenType.PUNCTUATION:
            if segment in CAPITALIZATION_RESET_PUNCTUATION:
                is_capitalization_forgivable = True
            if segment in SENTENCE_TERMINATORS:
                starts_new_sentence = True

        logging.info("Segment: %s, %s, ProperNounState: %s", fragment_index, segment, context_dependent_state)
        fragment_index += 1

    return fragment_index, sentence_idx, word_idx, is_capitalization_forgivable, starts_new_sentence


def _consume_clitic_tokens(word: str, api_tokens: List[TokenResult], cursor: int) -> Tuple[str, int, int]:
    """
    Greedily concatenates api_tokens starting at cursor until their combined
    surface form matches word. Undoes the macronizer's own clitic-splitting
    (e.g. "nullamque" comes back as two tokens, "nullam" + "que").
    Returns (macronized_word, uncertainty_mask, new_cursor).
    Raises if the tokens can't be made to match word — a desync here means
    everything after it is unreliable, so there's no safe way to continue.
    """
    if cursor == len(api_tokens):
        raise RuntimeError(f"The macronizer's results ran out before '{word}'.")
    reconstructed, macronized, mask = "", "", 0
    while cursor < len(api_tokens) and len(reconstructed) < len(word):
        token = api_tokens[cursor]
        reconstructed += token['word']
        macronized += token['macronized']
        mask |= token['uncertainty_mask']
        cursor += 1
    if reconstructed != word:
        raise RuntimeError(
            f"Clitic reassembly failed. Expected '{word}', reconstructed '{reconstructed}'."
        )
    return macronized, mask, cursor


def _raise_for_results_left_over(api_tokens: List[TokenResult], cursor: int):
    """Raises when api_tokens has results after cursor, where matching them with the text's tokens ended."""
    if cursor < len(api_tokens):
        raise RuntimeError(f"The macronizer returned {len(api_tokens) - cursor} more results than the text has tokens, "
                           f"from '{api_tokens[cursor]['word']}'.")


def _reassemble_clitic_tokens(target_words: List[str], api_tokens: List[TokenResult]) -> Dict[str, Tuple[str, int]]:
    """
    Maps each word in target_words to its (macronized_word, uncertainty_mask),
    reconstructing across clitic splits via _consume_clitic_tokens.
    """
    result: Dict[str, Tuple[str, int]] = {}
    cursor = 0
    for word in target_words:
        macronized, mask, cursor = _consume_clitic_tokens(word, api_tokens, cursor)
        result[word] = (macronized, mask)
    _raise_for_results_left_over(api_tokens, cursor)
    return result


def _get_macronization_data_from_api(words: Set[str]) -> Dict[str, Tuple[str, int]]:
    """
    Takes a set of words, calls the macronizer API, and returns a dictionary mapping
    each original word to a tuple of (macronized_word, uncertainty_mask).
    """
    if not words:
        return {}

    sorted_words = sorted(words)
    # The leading "et" provides context to avoid sentence-start capitalization logic for the first word.
    # It also never has status 2
    text_for_api = "et " + " et ".join(sorted_words)
    api_tokens = [res for res in macronize_text(text_for_api) if not res['word'].isspace()]
    macronizations = _reassemble_clitic_tokens(text_for_api.split(), api_tokens)
    return {word: macronizations[word] for word in sorted_words}


def _full_uncertainty_mask(word: str) -> int:
    """Calculates the full uncertainty mask for a word of given length."""
    if len(word) > 0:
        return (1 << len(word)) - 1
    return 0


def _different_macronizations_depending_on_status(words_state_2: Set[str]) -> Tuple[Set[str], Set[str]]:
    """
    Identifies words that have _specific_ different macronizations when capitalized vs. lowercase,
    ensuring that BOTH forms are actually known by the macronizer.
    Returns:
    - uncertain: set of lowercase words where both forms are known but macronize differently
    - cap_unknown: set of lowercase words where the capitalized form is unknown to the macronizer
    """
    if not words_state_2:
        return set(), set()

    # Create sets of capitalized and lowercase versions for the API calls
    cap_words = {word.capitalize() for word in words_state_2}
    lower_words = {word.lower() for word in words_state_2}

    logging.info("Batch analyzing %s macrons of potential proper nouns...", len(words_state_2))
    cap_macrons_data = _get_macronization_data_from_api(cap_words)
    lower_macrons_data = _get_macronization_data_from_api(lower_words)

    uncertain = set()
    cap_unknown = set()
    for word in words_state_2:
        cap_form = word.capitalize()
        lower_form = word.lower()

        # Get the macronization results for both forms
        macronized_cap, mask_cap = cap_macrons_data.get(cap_form, ("", 0))
        macronized_lower, mask_lower = lower_macrons_data.get(lower_form, ("", 0))

        # Calculate what a "completely unknown" mask would look like for each form
        full_mask_cap = _full_uncertainty_mask(cap_form)
        full_mask_lower = _full_uncertainty_mask(lower_form)

        # A word is "known" if its uncertainty mask is not the full mask
        cap_is_known = mask_cap != full_mask_cap
        lower_is_known = mask_lower != full_mask_lower

        if cap_is_known and lower_is_known:
            # Now that we know both are valid results, we can compare them.
            if macronized_cap.lower() != macronized_lower.lower():
                uncertain.add(lower_form)
        elif not cap_is_known and lower_is_known:
            # The macronizer doesn't know the capitalized form at all.
            # We can't safely fabricate a capitalized entry from the lowercase one.
            cap_unknown.add(lower_form)
        # If the lowercase form is unknown, we ignore it entirely — it's a case
        # of missing dictionary data, not proper-noun-based ambiguity.

    logging.info("Found %s words with uncertain macronization due to them maybe being proper nouns.", len(uncertain))
    logging.info("Found %s words where the capitalized form is unknown to the macronizer.", len(cap_unknown))
    return uncertain, cap_unknown


def generate_uuid():
    return str(uuid.uuid4())


def split_text_into_segments(text: str) -> list:
    # Normalize spaces and split text by words and punctuation
    text = text.strip()
    # Split text including em dash and other punctuation
    raw_segments = re.findall(_SEGMENT_PATTERN, text, re.UNICODE)

    # Put a known abbreviation back together with its period, ["M", "'", "."] -> ["M'."], so that get_token_type
    # finds it by the period
    segments = []
    i = 0
    while i < len(raw_segments):
        abbreviation = next((pieces for pieces in _ABBREVIATION_SEGMENTS
                             if raw_segments[i:i + len(pieces) + 1] == [*pieces, "."]), None)
        if abbreviation is not None:
            segments.append("".join(abbreviation) + ".")
            i += len(abbreviation) + 1
        else:
            segments.append(raw_segments[i])
            i += 1

    normalized_segments = [normalize_digraphs(s) for s in segments]

    return normalized_segments


@dataclass
class _Numbering:
    """The rows of a work's tokens, subdivisions and supplementary entries, numbered in reading order"""
    work_id: str
    work: WorkConfiguration
    contents: List[list] = field(default_factory=list)
    subdivisions: List[list] = field(default_factory=list)
    supplementary: List[list] = field(default_factory=list)
    #: The text of each block, as the macronizer gets it
    lines_for_macronizer: List[str] = field(default_factory=list)
    inherent_states: Dict[str, ProperNounState | None] = field(default_factory=dict)
    next_index: int = 0
    #: Tracks sentences across the whole work, incremented to 0 on the first real sentence
    sentence_idx: int = -1
    #: Tracks words within the current sentence
    word_idx: int = 0
    #: Whether the text so far ended a sentence
    starts_new_sentence: bool = True
    #: Whether the next block starts a sentence whatever the text before it: the first of a poem, prologue or
    #: epilogue, and the one after a speaker
    next_block_starts_sentence: bool = False
    supplementary_counts: Dict[str, int] = field(default_factory=lambda: {"NOTE": 0, "GAP": 0, "ABBR": 0})

    def add_parts(self, parts: Sequence[Division | TextBlock], parent: Division | None, parent_node: str | None):
        """Adds the rows of the parts of a division, or of the edition, each counted among its siblings of the same
        type"""
        counts: Dict[str, int] = defaultdict(int)
        for part in parts:
            cnt = counts[part.typ]
            counts[part.typ] += 1
            if isinstance(part, Division):
                self.add_division(part, cnt, parent_node)
            else:
                self.add_block(part, cnt, parent_node)
            if parent is not None and parent.typ == 'SPCH' and part.typ == 'TITL':
                self.next_block_starts_sentence = True  # the speaker isn't part of what is said

    def add_division(self, division: Division, cnt: int, parent_node: str | None):
        title = division.title
        node = generate_uuid()
        from_index = self.next_index
        row = [self.work_id, node, division.typ, cnt, title.printed_text if title else None, parent_node, from_index,
               None, division.edition_label]
        self.subdivisions.append(row)
        if division.typ in ('POEM', 'PROL', 'EPIL'):
            self.next_block_starts_sentence = True
        self.add_parts(division.parts, division, node)
        to_index = self.next_index - 1  # its last token
        row[7] = to_index
        for note in division.notes:
            self.add_supplementary("NOTE", from_index, to_index, note)
        print(f'Subdivision: {row}')

    def add_block(self, block: TextBlock, cnt: int, parent_node: str | None):
        segments: list = [segment for piece in block.pieces for segment in
                          ([None] if isinstance(piece, LostPassage) else split_text_into_segments(piece))]
        node = generate_uuid()
        first, last = self.next_index, self.next_index + len(segments) - 1
        if block.deleted:
            self.add_supplementary("NOTE", first, last, 'marked for deletion')
        for position, segment in enumerate(segments):
            if segment is None:
                self.add_supplementary("GAP", first + position, first + position, 'lost')
        self.subdivisions.append([self.work_id, node, block.typ, cnt, block.text or None, parent_node, first, last,
                                  block.edition_label])
        self.lines_for_macronizer.append(' '.join(segment for segment in segments if segment))
        starts_new_sentence = self.starts_new_sentence or self.next_block_starts_sentence or block.typ == 'TITL'
        self.next_block_starts_sentence = False
        self.next_index, self.sentence_idx, self.word_idx, _, self.starts_new_sentence = _process_text_segments(
            segments,
            self.work_id,
            first,
            self.sentence_idx,
            self.word_idx,
            block.reference,
            True,  # capitalization is forgivable at the start of a block
            starts_new_sentence,
            self.contents,
            self.inherent_states,
            self.work,
        )
        for note in block.notes:
            self.add_supplementary("NOTE", first, last, note)

    def add_supplementary(self, typ: str, from_index: int, to_index: int, val: str):
        self.supplementary.append([self.work_id, typ, self.supplementary_counts[typ], from_index, to_index, val])
        self.supplementary_counts[typ] += 1


def process_verse(xml_string, output_dir, work: WorkConfiguration):
    root = ET.fromstring(xml_string)
    namespaces = {'tei': TEI_NAMESPACE, 'xml': 'http://www.w3.org/XML/1998/namespace'}

    works_data = []
    authors_data = []
    author_abbreviations_data = []
    work_abbreviations_data = []
    authors_and_works_data = []

    work_id = generate_uuid()
    title_element = root.find('.//tei:title[@xml:lang="lat"]', namespaces)
    work_name = title_element.text if title_element is not None and title_element.text else 'Unknown Title'
    work_data = get_work_data(work_id, work_name, work)
    works_data.append(work_data)
    print(f'Work: {work_id}, {work_name}')

    author_element = root.find('.//tei:author', namespaces)
    author_name = author_element.text if author_element is not None and author_element.text else 'Unknown Author'
    author_id = generate_uuid()
    author_data = get_author_data(author_id, author_name, work)
    authors_data.append(author_data)
    print(f'Author: {author_id}, {author_name}')

    # Adding standard abbreviations for the author
    author_abbreviations_data.extend([author_id, i, abbreviation]
                                     for i, abbreviation in enumerate(work.author_abbreviations))

    # Linking author to work
    authors_and_works_data.append([author_id, work_id])

    numbering = _Numbering(work_id, work)
    numbering.add_parts(read_edition(root, work.cited_division_subtypes, work.poem_types_by_n), None, None)
    work_contents_data = numbering.contents
    work_content_subdivisions_data = numbering.subdivisions
    work_content_supplementary_data = numbering.supplementary
    lines_for_macronizer = numbering.lines_for_macronizer
    inherent_states = numbering.inherent_states

    # Titles repeat their tokens' text
    tokens_by_idx = {token[1]: token for token in work_contents_data}
    for subdivision in work_content_subdivisions_data:
        if subdivision[2] == 'TITL':
            title_tokens = [tokens_by_idx[idx] for idx in range(subdivision[6], subdivision[7] + 1) if idx in tokens_by_idx]
            subdivision[4] = _title_spelled_like_its_tokens(subdivision[4], title_tokens, work.letter_convention)

    works_df = pd.DataFrame(works_data, columns=['id', 'name', 'about', 'uvLowercase', 'uvCapitals', 'ijLowercase',
                                                 'ijCapitals'])
    work_contents_df = pd.DataFrame(work_contents_data,
                                    columns=['workId', 'idx', 'word', 'sourceReference', 'properNounState', 'tokenType',
                                             'sentenceIdx', 'wordIdx', 'enclitic', 'expansion']).astype(
        {'properNounState': 'Int64', 'wordIdx': 'Int64'})
    work_content_subdivisions_df = pd.DataFrame(work_content_subdivisions_data,
                                                columns=['workId', 'node', 'typ', 'cnt', 'name', 'parent', 'fromIndex',
                                                         'toIndex', 'editionLabel'])
    authors_df = pd.DataFrame(authors_data, columns=['id', 'name', 'about', 'image'])
    author_abbreviations_df = pd.DataFrame(author_abbreviations_data, columns=['authorId', 'id', 'val'])
    work_abbreviations_df = pd.DataFrame(work_abbreviations_data, columns=['workId', 'id', 'val'])
    authors_and_works_df = pd.DataFrame(authors_and_works_data, columns=['authorId', 'workId'])
    work_content_supplementary_df = pd.DataFrame(work_content_supplementary_data,
                                                 columns=['workId', 'typ', 'cnt', 'fromIndex', 'toIndex', 'val'])

    work_macronizations_data: List[WorkMacronization] = []
    certain_macronizations_by_key: Dict[str, Set[str]] = defaultdict(set)
    certain_tokens: List[CertainToken] = []

    if not work_contents_df.empty:

        # 1. Identify which word types have an INHERENT state of 2.
        words_with_inherent_state_2 = {word for word, state in inherent_states.items() if state == 2}

        # 2. Of those candidates, find which ones ACTUALLY have different macrons.
        uncertain_depending_on_proper_noun_state, cap_form_unknown = _different_macronizations_depending_on_status(words_with_inherent_state_2)

        # 3. Get contextual macronization for the entire work.
        full_text = '\n'.join(lines_for_macronizer)
        logging.info("Calling macronization API for the entire work to get contextual results...")
        api_tokens = [res for res in macronize_text(full_text) if not res['word'].isspace()]
        df_cursor = 0
        api_cursor = 0

        logging.info("Mapping macronization results and sorting into ambiguous/unambiguous tables...")
        while df_cursor < len(work_contents_df):
            original_row = work_contents_df.iloc[df_cursor]
            raw_word = original_row['word']
            if not isinstance(raw_word, str):
                df_cursor += 1
                continue
            original_word = raw_word
            content_idx = original_row['idx']
            token_type = int(original_row['tokenType'])
            proper_noun_state = (None if pd.isna(original_row['properNounState'])
                                 else int(original_row['properNounState']))

            # Skip processing for None
            if not original_word:
                df_cursor += 1
                continue

            # Reassemble clitics by greedily consuming API tokens
            combined_macronized, combined_mask, api_cursor = _consume_clitic_tokens(
                original_word, api_tokens, api_cursor
            )

            # 4a. Non-word tokens should be stored exactly as they appear (this includes punctuation, abbreviations, etc.)
            if token_type > 1:
                certain_macronizations_by_key[original_word].add(combined_macronized)
                certain_tokens.append(CertainToken(work_id, content_idx, original_word, token_type,
                                                   proper_noun_state, combined_macronized))
            else:
                # 4b. Decision logic: store in work-specific or global table
                lower_word = original_word.lower()

                respelled_word = spelled_with_morpheus_letters(original_word, work.letter_convention)
                respelled_macronized = respell_macronized(original_word, respelled_word, combined_macronized)
                #context_state = original_row['properNounState']
                is_macron_uncertain_by_pn_state = (
                        lower_word in uncertain_depending_on_proper_noun_state
                        and original_word[0].isupper()
                )
                is_macron_uncertain_always = combined_mask != 0

                if is_macron_uncertain_always:
                    work_macronizations_data.append(
                        WorkMacronization(work_id, content_idx, respelled_macronized, combined_mask))
                elif is_macron_uncertain_by_pn_state:
                    logging.warning("'%s' at '%s' has different macrons depending on whether it's a proper noun or not", original_word, content_idx)
                    work_macronizations_data.append(
                        WorkMacronization(work_id, content_idx, respelled_macronized, combined_mask))
                else:
                    # The macrons are stable. It's safe for the global unambiguous table.
                    # Get the inherent state to decide HOW to save it
                    inherent_state = inherent_states.get(lower_word) # default to None

                    if inherent_state == 0: # Common noun -> lowercase
                        certain_macronizations_by_key[respelled_word.lower()].add(respelled_macronized.lower())
                    elif inherent_state == 1: # Proper noun -> capitalized
                        certain_macronizations_by_key[respelled_word.capitalize()].add(
                            respelled_macronized.capitalize())
                    elif inherent_state == 2:
                        if lower_word in uncertain_depending_on_proper_noun_state or lower_word in cap_form_unknown:
                            # Only lowercase is globally safe — capitalized instances
                            # are always routed to WorkMacronizations above.
                            certain_macronizations_by_key[respelled_word.lower()].add(respelled_macronized.lower())
                        else:
                            # Both known, same macrons → store both
                            certain_macronizations_by_key[respelled_word.lower()].add(respelled_macronized.lower())
                            certain_macronizations_by_key[respelled_word.capitalize()].add(
                                respelled_macronized.capitalize())
                    else: # None: don't store as unambiguous as it is technically an unknown word
                        logging.warning("'%s' is morphologically un-analyzable but has a certain macronization. Storing as-is.", original_word)
                        work_macronizations_data.append(
                            WorkMacronization(work_id, content_idx, respelled_macronized, combined_mask))
                    if inherent_state is not None:
                        certain_tokens.append(CertainToken(work_id, content_idx, respelled_word, token_type,
                                                           proper_noun_state, respelled_macronized))

            df_cursor += 1
        _raise_for_results_left_over(api_tokens, api_cursor)

    unambiguous_macronizations_dict = agreed_macronizations(certain_macronizations_by_key)
    work_macronizations_data.extend(
        work_macronizations_where_lookup_differs(certain_macronizations_by_key, certain_tokens))

    # Respelled only now, because the loop above matches each word with a macronizer token
    # spelled as the source prints it
    is_word = work_contents_df['tokenType'] == int(TokenType.WORD)
    work_contents_df.loc[is_word, 'word'] = work_contents_df.loc[is_word, 'word'].map(
        lambda word: spelled_with_morpheus_letters(word, work.letter_convention))

    # Convert dictionary to list for DataFrame creation
    unambiguous_macronizations_data = list(unambiguous_macronizations_dict.items())
    work_macronizations_df = pd.DataFrame(
        work_macronizations_data,
        columns=['workId', 'idx', 'macronizedWord', 'uncertaintyBitMask']
    )
    unambiguous_macronizations_df = pd.DataFrame(
        unambiguous_macronizations_data,
        columns=['word', 'macronizedWord']
    )
    os.makedirs(output_dir, exist_ok=True)

    works_df.to_csv(os.path.join(output_dir, 'works.csv'), index=False)
    work_contents_df.to_csv(os.path.join(output_dir, 'work_contents.csv'), index=False)
    work_content_subdivisions_df.to_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'), index=False)
    authors_df.to_csv(os.path.join(output_dir, 'authors.csv'), index=False)
    author_abbreviations_df.to_csv(os.path.join(output_dir, 'author_abbreviations.csv'), index=False)
    work_abbreviations_df.to_csv(os.path.join(output_dir, 'work_abbreviations.csv'), index=False)
    authors_and_works_df.to_csv(os.path.join(output_dir, 'authors_and_works.csv'), index=False)
    work_content_supplementary_df.to_csv(os.path.join(output_dir, 'work_content_supplementary.csv'), index=False)
    work_macronizations_df.to_csv(os.path.join(output_dir, 'work_macronizations.csv'), index=False)
    unambiguous_macronizations_df.to_csv(os.path.join(output_dir, 'unambiguous_macronizations.csv'), index=False)


def get_work_data(work_id, work_name, work: WorkConfiguration):
    with open(work.work_about_file, 'r', encoding='utf-8') as about:
        about_text = about.read()
    work_data = [work_id, work_name, about_text, *work.letter_convention]
    return work_data


def get_author_data(author_id, author_name, work: WorkConfiguration):
    with open(work.author_about_file, 'r', encoding='utf-8') as about:
        about_text = about.read()
    with open(work.author_image_file, 'rb') as expanded:
        image_data = expanded.read()
        image_data = base64.b64encode(image_data).decode()  # Convert binary data to base64 string
    author_data = [author_id, author_name, about_text, image_data]
    return author_data


def publish_work(xml_string, output_dir, work: WorkConfiguration):
    """Writes the work's files to output_dir when they pass validation. Otherwise raises, and output_dir stays as it
    was."""
    with tempfile.TemporaryDirectory() as working_dir:
        process_verse(xml_string, working_dir, work)
        validate_csv_files(xml_string, working_dir, work)
        publish(Path(working_dir), Path(output_dir))


def validate_csv_files(xml_string, output_dir, work: WorkConfiguration):
    errors = []

    # Load the relevant CSV files
    work_contents_df = pd.read_csv(os.path.join(output_dir, 'work_contents.csv'))
    work_content_subdivisions_df = pd.read_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'),
                                               dtype={'editionLabel': str})
    work_content_supplementary_df = pd.read_csv(os.path.join(output_dir, 'work_content_supplementary.csv'))
    author_abbreviations_df = pd.read_csv(os.path.join(output_dir, 'author_abbreviations.csv'))
    work_macronizations_df = pd.read_csv(os.path.join(output_dir, 'work_macronizations.csv'))
    unambiguous_macronizations_df = pd.read_csv(os.path.join(output_dir, 'unambiguous_macronizations.csv'))

    check_seq_unique_ints_from_0(errors, author_abbreviations_df, 'author abbreviations', 'id', ['authorId'])
    check_subdivision_numbers(errors, work_content_subdivisions_df)
    check_edition_labels(errors, work_content_subdivisions_df)
    check_seq_unique_ints_from_0(errors, work_contents_df, 'contents', 'idx', ['workId'])
    check_seq_unique_ints_from_0(errors, work_content_supplementary_df, 'supplementary', 'cnt', ['workId', 'typ'])
    check_children_within_parent_range(errors, work_content_subdivisions_df)
    check_to_index_always_gt_from_index_in_sub(errors, work_content_subdivisions_df)
    check_to_index_always_gt_from_index_in_supp(errors, work_content_supplementary_df)
    check_contents_not_empty_when_supp_not_empty(errors, work_contents_df, work_content_supplementary_df)
    check_subdivisions_not_empty_when_contents_not_empty(errors, work_content_subdivisions_df, work_contents_df)
    validate_gap_tags(errors, xml_string, work_content_subdivisions_df.to_dict('records'),
                      work_contents_df.to_dict('records'),
                      work_content_supplementary_df.to_dict('records'))
    validate_p_tags(errors, xml_string, work_content_subdivisions_df.to_dict('records'))
    check_proper_noun_states(errors, work_contents_df)
    check_macronization_coverage(errors, work_contents_df, work_macronizations_df, unambiguous_macronizations_df)
    check_expansion_completeness(errors, work_contents_df)
    check_sentence_and_word_idx(errors, work_contents_df)
    check_letters_against_morpheus(errors, work_contents_df, work.letter_convention)

    if errors:
        raise ValueError("Validation errors found:\n" + "\n".join(f"    {error}" for error in errors))
    else:
        logging.info("All validations passed successfully.")


def check_seq_unique_ints_from_0(errors, df, f_name, column_name, group_columns=None):
    def check_sequence_and_uniqueness(series):
        expected_values = pd.Series(range(0, len(series)))
        # Ensure matching dtype before comparison
        try:
            fractional_parts = series.astype('float64').mod(1)
            series = series.astype('int64')
        except (ValueError, TypeError):
            return False  # contains NaN or non-integer → fail
        if fractional_parts.ne(0).any():
            return False  # a fraction, which astype cut to an integer
        is_sequential = series.equals(expected_values)
        is_unique = series.nunique() == len(series)
        return is_sequential and is_unique

    if group_columns:
        grouped = df.groupby(group_columns, dropna=False)
        for name, group in grouped:
            sorted_values = group[column_name].sort_values().reset_index(drop=True)
            if not check_sequence_and_uniqueness(sorted_values):
                group_name = ', '.join([f"{col}={val}" for col, val in zip(group_columns, name)])
                if sorted_values.nunique() != len(sorted_values):
                    errors.append(f"For {f_name}, column '{column_name}' in group ({group_name}) contains duplicate values.")
                else:
                    errors.append(f"For {f_name}, column '{column_name}' in group ({group_name}) does not contain sequential integers starting from 0.")
    else:
        sorted_values = df[column_name].sort_values().reset_index(drop=True)
        if not check_sequence_and_uniqueness(sorted_values):
            if sorted_values.nunique() != len(sorted_values):
                errors.append(f"Column '{column_name}' contains duplicate values.")
            else:
                errors.append(f"Column '{column_name}' does not contain sequential integers starting from 0.")


#: The subdivisions that have their TEI n as editionLabel
SUBDIVISION_TYPES_WITH_EDITION_LABELS = ('BOOK', 'POEM', 'PROL', 'EPIL', 'VERS')


def check_subdivision_numbers(errors, work_content_subdivisions_df):
    """Checks that each subdivision's cnt counts its siblings of the same type from 0 up, whatever the edition numbers
    them, and that a subdivision has one title at most, numbered 0, as the reader's unique index requires."""
    subdivisions = work_content_subdivisions_df
    titles = subdivisions[subdivisions['typ'] == 'TITL']
    for node in titles[titles['cnt'] != 0]['node']:
        errors.append(f"Title {node} isn't numbered 0.")
    for parent in sorted(set(titles[titles.duplicated(['workId', 'parent'])]['parent'])):
        errors.append(f"Subdivision {parent} has more than one title.")
    check_seq_unique_ints_from_0(errors, subdivisions[subdivisions['typ'] != 'TITL'], 'subs', 'cnt',
                                 ['workId', 'parent', 'typ'])


def check_edition_labels(errors, work_content_subdivisions_df):
    """Checks that books, poems, prologues, epilogues and verses have an editionLabel, and other subdivisions none."""
    subdivisions = work_content_subdivisions_df
    labelled = subdivisions['typ'].isin(SUBDIVISION_TYPES_WITH_EDITION_LABELS)
    has_label = subdivisions['editionLabel'].notnull()
    for typ, node in zip(subdivisions[labelled & ~has_label]['typ'], subdivisions[labelled & ~has_label]['node']):
        errors.append(f"{typ} {node} has no editionLabel.")
    for typ, node in zip(subdivisions[~labelled & has_label]['typ'], subdivisions[~labelled & has_label]['node']):
        errors.append(f"{typ} {node} has an editionLabel, which only "
                      f"{', '.join(SUBDIVISION_TYPES_WITH_EDITION_LABELS)} have.")


def check_to_index_always_gt_from_index_in_sub(errors, work_content_subdivisions_df):
    for _, row in work_content_subdivisions_df.iterrows():
        node = row['node']
        from_index = row['fromIndex']
        to_index = row['toIndex']
        if to_index < from_index:
            errors.append(f'Node {node} has toIndex {to_index} which is less than fromIndex {from_index}.')


def check_to_index_always_gt_from_index_in_supp(errors, work_content_supplementary_df):
    for _, row in work_content_supplementary_df.iterrows():
        from_index = row['fromIndex']
        to_index = row['toIndex']
        if to_index < from_index:
            errors.append(f'Supplementary entry {row["typ"]} {row["cnt"]} has toIndex {to_index} '
                          f'which is less than fromIndex {from_index}.')


def check_children_within_parent_range(errors, work_content_subdivisions_df):
    for _, parent_row in work_content_subdivisions_df.iterrows():
        parent_node = parent_row['node']
        parent_from = parent_row['fromIndex']
        parent_to = parent_row['toIndex']

        child_rows = work_content_subdivisions_df[work_content_subdivisions_df['parent'] == parent_node]
        for _, child_row in child_rows.iterrows():
            child_from = child_row['fromIndex']
            child_to = child_row['toIndex']
            if not (parent_from <= child_from <= parent_to and parent_from <= child_to <= parent_to):
                errors.append(f'Child node {child_row["node"]} indices [{child_from}, {child_to}] are out of range '
                              f'of parent node {parent_node} indices [{parent_from}, {parent_to}].')


def check_consecutive_integers_by_typ_in_sub(errors, work_content_subdivisions_df):
    work_content_subdivisions_df['cnt'] = pd.to_numeric(work_content_subdivisions_df['cnt'], errors='coerce')
    grouped = work_content_subdivisions_df.groupby(['parent', 'typ'])
    for (parent, typ), group in grouped:
        sorted_group = group.sort_values(by='cnt').reset_index(drop=True)
        expected_seq = pd.Series(range(1, len(group) + 1))
        if not pd.Series((sorted_group['cnt'].reset_index(drop=True) == expected_seq)).all():
            errors.append(
                f'Nodes under parent {parent} with type {typ} do not have consecutive integers starting from 1.')


def check_consecutive_integers_by_typ_in_supp(errors, work_content_supplementary_df):
    grouped = work_content_supplementary_df.groupby(['workId', 'typ'])
    for (work_id, typ), group in grouped:
        sorted_group = group.sort_values(by='cnt').reset_index(drop=True)
        expected_cnt = pd.Series(range(1, len(group) + 1))
        if not pd.Series((sorted_group['cnt'].reset_index(drop=True) == expected_cnt)).all():
            errors.append(
                f'Supplementary entries for workId {work_id} with type {typ} do '
                f'not have consecutive integers starting from 1.')


def check_subdivisions_not_empty_when_contents_not_empty(errors, work_content_subdivisions_df, work_contents_df):
    for _, row in work_content_subdivisions_df.iterrows():
        from_index = row['fromIndex']
        to_index = row['toIndex']
        if (not work_contents_df[(work_contents_df['idx'] >= from_index) & (work_contents_df['idx'] <= to_index)].empty
                and not row['name']):
            errors.append(f'Subdivision at node {row["node"]} is empty but it contains content.')


def check_contents_not_empty_when_supp_not_empty(errors, work_contents_df, work_content_supplementary_df):
    supp_ranges = []
    for _, row in work_content_supplementary_df.iterrows():
        supp_ranges.append(range(row['fromIndex'], row['toIndex'] + 1))
    supp_ranges = set().union(*supp_ranges)

    for _, row in work_contents_df.iterrows():
        if row['idx'] in supp_ranges and not row['word']:
            errors.append(f'Content at index {row["idx"]} is empty but it is part of a supplementary entry.')


def find_all_gap_tags(element, namespace, gap_tags=None):
    if gap_tags is None:
        gap_tags = []
    if element.tag == f'{namespace}gap':
        gap_tags.append(element)
    for child in element:
        find_all_gap_tags(child, namespace, gap_tags)
    return gap_tags


def find_all_p_tags(element, namespace, p_tags=None):
    if p_tags is None:
        p_tags = []
    if element.tag == f'{namespace}p' and not element.text.strip().startswith('This pointer pattern'):
        p_tags.append(element)
    for child in element:
        find_all_p_tags(child, namespace, p_tags)
    return p_tags


def validate_gap_tags(errors, xml_string, subdivisions, contents, supp_entries):
    # Parse the XML string
    root = ET.fromstring(xml_string)

    # Find all <gap> tags in the original XML using a recursive function
    namespace = "{" + TEI_NAMESPACE + "}"
    gap_tags = find_all_gap_tags(root, namespace)

    # Every empty content entry, each to check against the gap tags
    gap_indices = [content['idx'] for content in contents if pd.isnull(content['word'])]

    # Check if the number of gap tags is equal to the number of empty content entries
    if len(gap_tags) != len(gap_indices):
        errors.append("Mismatch between the number of <gap> tags and the number of empty content entries.")

    # Check for corresponding subdivision entries
    for idx in gap_indices:
        # the verse that holds it, which can have text before it or after it
        matching_subdivisions = [sub for sub in subdivisions if sub['typ'] == 'VERS' and
                                 sub['fromIndex'] <= idx <= sub['toIndex']]
        if len(matching_subdivisions) != 1:
            errors.append(
                f"Expected exactly one subdivision entry for gap tag at idx {idx}, found {len(matching_subdivisions)}")

    # Check for corresponding note entries
    for idx in gap_indices:
        matching_supp_entries = [entry for entry in supp_entries if entry['fromIndex'] == idx and
                                 entry['toIndex'] == idx and
                                 entry['typ'] == 'GAP']
        if len(matching_supp_entries) != 1:
            errors.append(
                f"Expected exactly one supplementary entry for gap tag at idx {idx}, "
                f"found {len(matching_supp_entries)}")


def validate_p_tags(errors, xml_string, subdivisions):
    # Parse the XML string
    root = ET.fromstring(xml_string)

    # Find all <p> tags in the original XML using a recursive function
    namespace = "{" + TEI_NAMESPACE + "}"
    p_tags = find_all_p_tags(root, namespace)

    # Count the number of elements in p_tags
    num_p_tags = len(p_tags)

    # Create a list to store the paragraphs
    paragraphs = []

    # Iterate over the contents list for as many times as there are elements in p_tags
    for i in range(num_p_tags):
        # For each iteration, find the corresponding entry in the subdivisions list
        for subdivision in subdivisions:
            # If a corresponding entry is found, add entry to the list
            if subdivision['typ'] == 'PARA' \
                    and subdivision['name'] == p_tags[i].text:
                paragraphs.append(subdivision)
                break

    # Check if the number of p tags is equal to the number of paragraph subdivisions
    if num_p_tags != len(paragraphs):
        errors.append("Mismatch between the number of <p> tags and the number of paragraph subdivisions.")


def check_proper_noun_states(errors, work_contents_df):
    """Every abbreviation must have the properNounState 1, every numeral 0, and punctuation, editorial marks and other
    tokens none. A word without one is a word that Morpheus has no analysis for, which the reader looks up in both
    cases: logged for review."""
    words = work_contents_df[work_contents_df['tokenType'] == int(TokenType.WORD)]
    unknown = words[words['properNounState'].isnull()]
    if not unknown.empty:
        logging.warning("Found %s words without a properNounState, which Morpheus has no analysis for: %s",
                        len(unknown),
                        ', '.join(f"'{word}' at index {idx}" for word, idx in zip(unknown['word'], unknown['idx'])))

    for token_type, state, tokens_name in ((TokenType.ABBREVIATION, ProperNounState.YES, 'abbreviations'),
                                           (TokenType.NUMERAL, ProperNounState.NO, 'numerals')):
        tokens = work_contents_df[work_contents_df['tokenType'] == int(token_type)]
        wrong = tokens[tokens['properNounState'].ne(int(state)).fillna(True).astype(bool)]
        if not wrong.empty:
            errors.append(f"Found {len(wrong)} {tokens_name} whose properNounState isn't {int(state)}: "
                          + ', '.join(f"'{word}' at index {idx}" for word, idx in zip(wrong['word'], wrong['idx'])))

    non_words = work_contents_df[work_contents_df['tokenType'] > 3]
    bad = non_words[non_words['properNounState'].notnull()]
    if not bad.empty:
        errors.append(
            f"Found {len(bad)} non-word tokens with a properNounState that should be NULL."
        )


def check_macronization_coverage(errors, work_contents_df, work_macronizations_df, unambiguous_macronizations_df):
    """
    Checks that every word has a valid macronization source.
    - A word in both tables isn't an error: an occurrence's own macronization comes before the stable one, as in the
      reader, such as a capitalized I's before a numeral I's.
    - Cross-case overlaps (e.g. 'aliis' stable vs 'Aliis' work-specific) are
      expected for state-2 words and logged as warnings, not errors.
    - Every word token must have its own macronization, or a stable one under the key that the reader looks it up by,
      which depends on its properNounState. The reader shows other tokens as printed when they have neither.
    """
    # 1. Check for word types appearing in both tables.
    stable_word_forms = set(unambiguous_macronizations_df['word'])

    if not work_macronizations_df.empty:
        work_specific_merged = pd.merge(work_macronizations_df, work_contents_df, on='idx') # no workId is safe, each script is for 1 work only
        work_specific_forms = set(work_specific_merged['word'])

        # Cross-case overlaps are expected (e.g. lowercase in stable, capitalized in work-specific).
        stable_types_lower = {w.lower() for w in stable_word_forms}
        work_specific_types_lower = {w.lower() for w in work_specific_forms}
        cross_case_overlaps = stable_types_lower.intersection(work_specific_types_lower)

        if cross_case_overlaps:
            stable_macron_by_lower = {
                w.lower(): m for w, m in
                zip(unambiguous_macronizations_df['word'], unambiguous_macronizations_df['macronizedWord'])
            }
            work_macron_by_lower: Dict[str, Set[str]] = {}
            for w, m in zip(work_specific_merged['word'], work_specific_merged['macronizedWord']):
                work_macron_by_lower.setdefault(w.lower(), set()).add(m)

            genuinely_ambiguous, case_only = set(), set()
            for w in cross_case_overlaps:
                stable_norm = strip_macrons(stable_macron_by_lower.get(w, '')).lower()
                work_norms = {strip_macrons(m).lower() for m in work_macron_by_lower.get(w, set())}
                if work_norms and work_norms == {stable_norm}:
                    case_only.add(w)
                else:
                    genuinely_ambiguous.add(w)

            if genuinely_ambiguous:
                logging.warning(
                    "Found %s word types with different macrons depending on case "
                    "(expected for proper-noun ambiguity). Examples: %s",
                    len(genuinely_ambiguous), ', '.join(sorted(genuinely_ambiguous)[:50])
                )
            if case_only:
                logging.warning(
                    "Found %s word types stored under both cases with IDENTICAL macrons"
                    "because of potential stylisic capitalization. Examples: %s",
                    len(case_only), ', '.join(sorted(case_only)[:50])
                )

    # 2. Check that every individual word INSTANCE is covered.
    work_specific_indices = set(work_macronizations_df['idx'])
    missing_instances = []

    word_df = work_contents_df[work_contents_df['tokenType'] == int(TokenType.WORD)]

    for _, row in word_df.iterrows():
        word = row['word']
        idx = row['idx']
        proper_noun_state = None if pd.isna(row['properNounState']) else int(row['properNounState'])

        is_in_stable_table = lookup_key(word, TokenType.WORD, proper_noun_state, stable_word_forms) is not None
        is_in_work_specific_table = idx in work_specific_indices

        if not is_in_stable_table and not is_in_work_specific_table:
            missing_instances.append(f"'{word}' (idx {idx})")

    if missing_instances:
        error_msg = (
            f"Found {len(missing_instances)} words missing a macronization entry entirely. "
            f"Examples: {', '.join(missing_instances[:50])}"
        )
        errors.append(error_msg)



def check_expansion_completeness(errors, work_contents_df):
    """Every abbreviation/numeral token must have a supplied expansion."""
    needs_expansion = work_contents_df[
        work_contents_df['tokenType'].isin([int(TokenType.ABBREVIATION), int(TokenType.NUMERAL)])
    ]
    missing = needs_expansion[needs_expansion['expansion'].isnull() | (needs_expansion['expansion'] == '')]
    if not missing.empty:
        examples = missing.head(50).apply(lambda row: f"'{row['word']}' at idx {row['idx']}", axis=1).tolist()
        errors.append(
            f"Found {len(missing)} abbreviation/numeral tokens missing an 'expansion'. "
            f"Add them to the work configuration's expansions: {', '.join(examples)}"
        )


def check_letters_against_morpheus(errors, work_contents_df, convention: LetterConvention):
    """Checks that every word has Morpheus's letter where the edition prints one letter for two.
    Logs for review the words that Morpheus also spells with the other letter of a pair that the edition tells apart,
    and the words that no analysis spells with the same letters.
    A word with a letter that the source didn't print, such as jam, is a new query to Morpheus."""
    words = work_contents_df[work_contents_df['tokenType'] == int(TokenType.WORD)]
    not_respelled, told_apart, unresolved = [], [], []
    for _, row in words.iterrows():
        word = row['word']
        enclitic: str | None = row['enclitic'] if isinstance(row['enclitic'], str) else None
        surfaces = morpheus_surfaces(word, convention)
        spellings = token_spellings_of(word, enclitic, surfaces, convention)
        if len(spellings) == 1 and word not in spellings:
            not_respelled.append(f"'{word}' (idx {row['idx']}) as '{next(iter(spellings))}'")
        elif len(spellings) != 1:
            unresolved.append(f"'{word}' (idx {row['idx']})" + (f" as {sorted(spellings)}" if spellings else ""))
        hosts = [word] if enclitic is None else [word, word[:-len(enclitic)]]
        if any(differs_in_told_apart_letters(host, surface, convention) for host in hosts for surface in surfaces):
            told_apart.append(f"'{word}' (idx {row['idx']})")

    if not_respelled:
        errors.append(f"Found {len(not_respelled)} words that Morpheus spells with other letters where the edition "
                      f"prints one for two. Examples: {', '.join(not_respelled[:50])}")
    if told_apart:
        logging.warning("Found %s words that Morpheus also spells with the other letter of a pair the edition tells "
                        "apart, as expected where the edition printed that letter: %s", len(told_apart), ', '.join(told_apart))
    if unresolved:
        logging.warning("Found %s words that keep the edition's letters because no analysis spells them with their "
                        "other letters, or analyses spell them in more than one way: %s",
                        len(unresolved), ', '.join(unresolved))


def check_sentence_and_word_idx(errors, work_contents_df):
    """sentenceIdx: sequential unique ints from 0 per workId.
    wordIdx: sequential unique ints from 0 per (workId, sentenceIdx), tokenType<=3 only;
    must be null everywhere else."""
    check_seq_unique_ints_from_0(
        errors, work_contents_df.drop_duplicates(['workId', 'sentenceIdx']),
        'sentence indices', 'sentenceIdx', ['workId']
    )
    word_rows = work_contents_df[work_contents_df['tokenType'] <= 3]
    check_seq_unique_ints_from_0(errors, word_rows, 'word indices', 'wordIdx', ['workId', 'sentenceIdx'])
    non_word_rows = work_contents_df[work_contents_df['tokenType'] > 3]
    bad = non_word_rows[non_word_rows['wordIdx'].notnull()]
    if not bad.empty:
        errors.append(f"Found {len(bad)} punctuation/editorial tokens with a non-null wordIdx.")
