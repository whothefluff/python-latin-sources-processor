# "Ambiguous"/"ambiguity" is and should always be reserved exclusively for doubtful macronizations,
# both in comments and code. Any other kind of uncertainty should be described with different words

# noinspection PyPep8Naming
import base64
import json
import logging
import os
import re
import uuid
import xml.etree.ElementTree as ET
from functools import cache
from typing import Dict, List, Optional, Set, Tuple, TypedDict

import pandas as pd
import requests

TEI_NAMESPACE = 'http://www.tei-c.org/ns/1.0'
# Defines the clitics that are commented out in Morpheus 'checkstring.c' (and make sense)
COMMENTED_OUT_CLITICS = ["que", "ne", "ve", "ue", "dum"]

logging.basicConfig(level=logging.INFO)


def _extract_lemmas_from_morpheus_xml(xml_string: str) -> List[str]:
    """Parses the XML output from the morpheus endpoint to extract lemmas."""
    lemmas = []
    try:
        # The XML is often wrapped in a <words> tag.
        # An empty or error response should not cause a crash.
        if not xml_string or "<words/>" in xml_string or "<error>" in xml_string:
            return []
        root = ET.fromstring(xml_string)
        # Find all headwords (hdwd), which contain the lemma
        for hdwd_element in root.findall('.//hdwd'):
            if hdwd_element.text:
                lemmas.append(hdwd_element.text.strip())
        return list(set(lemmas)) # Return unique lemmas
    except ET.ParseError:
        logging.exception("XML Parse Error for morpheus '%s'", xml_string)
        return []


def _is_valid_dum_stem(xml_string: str) -> bool:
    """
    Parses Morpheus XML to check if a word is an imperative, interjection, or adverb.
    This is used to validate if 'dum' is acting as a clitic.
    """
    try:
        # The XML is often wrapped in a <words> tag.
        # An empty or error response should not cause a crash.
        if not xml_string or "<words/>" in xml_string or "<error>" in xml_string:
            return False
        root = ET.fromstring(xml_string)
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
    except ET.ParseError:
        logging.exception("XML Parse Error while checking for DUM clitic stem from response: '%s'", xml_string)
        return False


@cache
def find_potential_lemmas(word_to_analyze: str) -> List[str]:
    """
    Calls the local morpheus/cruncher endpoint. If the initial analysis is empty,
    it attempts to strip a known enclitic and re-queries the API with the stem.
    Returns a list of potential lemmas.
    """
    if not word_to_analyze or not word_to_analyze.isalpha():
        return []

    url = "http://localhost:1501/analysis/word"
    headers = { "Accept": "application/xml" }

    try:
        # 1. Primary API Call (with the full word)
        params = { "lang": "lat", "engine": "morpheuslat", "word": word_to_analyze, "strictCase": str(int(True)) }
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        lemmas = _extract_lemmas_from_morpheus_xml(response.text)

        # 2. Fallback Logic (if primary call returned nothing)
        if not lemmas:
            for clitic in COMMENTED_OUT_CLITICS:
                # Check if the word ends with one of the special clitics
                if word_to_analyze.endswith(clitic):
                    stem = word_to_analyze[:-len(clitic)]

                    # Ensure the stem is not empty (e.g., for a word that is just "que")
                    if stem:
                        logging.warning("Analysis for '%s' was empty. Retrying with stem '%s'.", word_to_analyze, stem)

                        # 3. Secondary API Call (with the stripped stem)
                        params['word'] = stem
                        response_stem = requests.get(url, params=params, headers=headers, timeout=10)
                        response_stem.raise_for_status()
                        stem_xml = response_stem.text

                        # For 'dum', only consider it a clitic if attached to an imperative, interjection, or adverb.
                        if clitic == "dum":
                            if _is_valid_dum_stem(stem_xml):
                                logging.warning("'%s'-'%s' found", stem, clitic)
                                lemmas = _extract_lemmas_from_morpheus_xml(stem_xml)
                        else:
                            # For other clitics, we accept the analysis of the stem.
                            logging.warning("'%s'-'%s' found", stem, clitic)
                            lemmas = _extract_lemmas_from_morpheus_xml(stem_xml)

                        # Once we've found a matching clitic and tried again, stop the loop.
                        break

        return lemmas

    except requests.exceptions.RequestException:
        logging.exception("Error calling morpheus API for word '%s'", word_to_analyze)
        return []


def is_proper_noun_lemma(lemma: str) -> bool:
    """Checks if a lemma from cruncher indicates a proper noun (i.e., is capitalized)."""
    return bool(lemma) and lemma[0].isupper()


@cache
def determine_proper_noun_state(word_in_text: str, is_sentence_start: bool, prev_word_was_capitalized: bool) -> Tuple[int | None, int | None]:
    """
    Determines both the inherent and context-aware proper noun states for a word.
    Returns None for non-alphabetic tokens or words that cannot be analyzed at all.
    - Inherent State: Based only on dictionary lookups (is this word type not clear?).
    - Context-Aware State: Uses sentence start and capitalization sequences to refine the state for this specific instance.
    
    It handles consecutive capitalized words as a sequence, aligning with *macronizer* logic.

    Returns: A tuple of (inherent_state, context_aware_state).
    States: 0 (NO), 1 (YES), 2 (EITHER), or None (UNKNOWN/NA).
    """
    if not word_in_text or not word_in_text.isalpha():
        return None, None

    word_is_capitalized = word_in_text[0].isupper()

    # Step 1-3: Calculate the INHERENT STATE. This logic is PURE and based only on
    # dictionary lookups of word forms, completely independent of context.
    # Step 1: Perform dictionary lookups.
    analyses_lower = find_potential_lemmas(word_in_text.lower())
    analyses_upper = find_potential_lemmas(word_in_text.capitalize())

    # Step 2: Determine if common and proper forms exist.
    # A word has a common form if its lowercase analysis returns anything,
    # OR if its capitalized analysis contains a lowercase lemma.
    # Check analysis for 'hercle' which has lemma Hercules
    has_common_word_analysis = bool(analyses_lower) or any(not is_proper_noun_lemma(lemma) for lemma in analyses_upper)

    # A word has a proper form if its capitalized analysis contains a capitalized lemma.
    has_proper_noun_analysis = any(is_proper_noun_lemma(lemma) for lemma in analyses_upper)

    # Step 3: Determine Inherent State (Context-Independent)
    inherent_state: int | None
    if has_proper_noun_analysis and has_common_word_analysis:
        inherent_state = 2  # Inherently doubtful (e.g., "Venere", "Hercle")
    elif has_proper_noun_analysis:
        inherent_state = 1  # Inherently proper noun (e.g., "Caesar")
    elif has_common_word_analysis:
        inherent_state = 0
    else:
        inherent_state = None

    # Step 4: Determine Context-Aware State
    context_aware_state: int | None
    
    # Capitalization is "forgivable" if it's at the start of a sentence OR part of a capitalized sequence.
    is_forgivable_context = is_sentence_start or prev_word_was_capitalized

    if word_is_capitalized:
        if inherent_state == 0: # Common word like "Fabula"
            # Titles and such are editorial choice; otherwise typo or similar
            context_aware_state = 0 if is_forgivable_context else None
        elif inherent_state == 1: # Proper word like "Caesar"
            context_aware_state = 1
        elif inherent_state == 2: # Dubious word like "Venere"
            # Capitalized mid-sentence is a proper noun; at start it's uncertain.
            context_aware_state = 2 if is_forgivable_context else 1
        else: # Word is unknown
            context_aware_state = None
    else: # word is lowercase
        if inherent_state == 0: # "fabula"
            context_aware_state = 0
        elif inherent_state == 1: # "caesar"
            # Probably a typo or similar
            context_aware_state = None
        elif inherent_state == 2: # "venere"
            context_aware_state = 0
        else:
            context_aware_state = None

    return inherent_state, context_aware_state


class TokenResult(TypedDict):
    word: str
    is_word: bool
    macronized: str
    uncertainty_mask: int
    candidates: list[str]


def macronize_text(text: str) -> Optional[List[TokenResult]]:
    """
    Calls the local macronization API to get macronization data for a given text.
    """
    url = "http://localhost:8001/macronize-text"
    payload = {"text": text, "clean": False}
    headers = {"Content-Type": "application/json"}
    try:
        # Set a generous timeout as macronizing a large text can take time
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=300)
        response.raise_for_status()
        return response.json().get('results', [])
    except requests.exceptions.RequestException:
        logging.exception("Error calling macronization API")
        return None


def _process_text_segments(
    segments: List[str],
    work_id: str,
    fragment_index: int,
    is_next_word_sentence_start: bool,
    work_contents_data: List,
    inherent_states_map: Dict[str, int | None],
) -> Tuple[int, bool]:
    """
    Helper function to process a list of text segments (words/punctuation).

    It determines the proper noun state for each segment, updates the sentence start flag,
    and appends the processed data to the work_contents_data list. It includes tracking
    sequences of capitalized words to align with macronizer logic.

    Returns: A tuple containing the updated fragment_index and is_next_word_sentence_start flag.
    """
    prev_word_was_capitalized = False
    for segment in segments:
        # Determine the state for the current word based on the *previous* word's status.
        inherent_state, context_dependent_state = determine_proper_noun_state(
            segment, is_next_word_sentence_start, prev_word_was_capitalized
        )
        work_contents_data.append([work_id, fragment_index, segment, 'sourceReference', context_dependent_state])

        # Store the inherent state for the word type, to be used for macronization sorting
        if segment and segment.isalpha():
            inherent_states_map[segment.lower()] = inherent_state

        # Update context flags for the *next* word.
        if segment and segment.isalpha():
            is_next_word_sentence_start = False
            prev_word_was_capitalized = segment[0].isupper()
        else: # Punctuation or non-alphabetic tokens reset the capitalization sequence.
            prev_word_was_capitalized = False

        if segment and any(p in segment for p in ".!?:"):
            is_next_word_sentence_start = True

        logging.info("Segment: %s, %s, ProperNounState: %s", fragment_index, segment, context_dependent_state)
        fragment_index += 1
    return fragment_index, is_next_word_sentence_start


def _get_macronization_data_from_api(words: Set[str]) -> Dict[str, Tuple[str, int]]:
    """
    Takes a set of words, calls the macronizer API, and returns a dictionary mapping
    each original word to a tuple of (macronized_word, uncertainty_mask).
    """
    if not words:
        return {}

    # The leading "et" provides context to avoid sentence-start capitalization logic for the first word.
    text_for_api = "et " + " et ".join(sorted(list(words)))
    results = macronize_text(text_for_api)
    macron_map: Dict[str, Tuple[str, int]] = {}

    if results:
        # Filter out the "et" tokens and spaces
        word_tokens = [res for res in results if res['is_word'] and res['word'] != 'et']
        for token in word_tokens:
            word = token['word']
            # Store both the macronized form and its mask.
            macron_map[word] = (token['macronized'], token['uncertainty_mask'])
            
    return macron_map


def _full_uncertainty_mask(word: str) -> int:
    """Calculates the full uncertainty mask for a word of given length."""
    if len(word) > 0:
        return (1 << len(word)) - 1
    return 0


def _different_macronizations_depending_on_status(words_state_2: Set[str]) -> Set[str]:
    """
    Identifies words that have _specific_ different macronizations when capitalized vs. lowercase,
    ensuring that BOTH forms are actually known by the macronizer.
    Returns a set of these words in their canonical lowercase form.
    """
    if not words_state_2:
        return set()

    # Create sets of capitalized and lowercase versions for the API calls
    cap_words = {word.capitalize() for word in words_state_2}
    lower_words = {word.lower() for word in words_state_2}

    logging.info("Batch analyzing %s macrons of potential proper nouns...", len(words_state_2))
    cap_macrons_data = _get_macronization_data_from_api(cap_words)
    lower_macrons_data = _get_macronization_data_from_api(lower_words)

    uncertain = set()
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
        # If one or both are not known, we ignore this pair. It's not a case of
        # proper-noun-based ambiguity; it's a case of missing dictionary data.

    logging.info("Found %s words with uncertain macronization due to them maybe being proper nouns.", len(uncertain))
    return uncertain


def asset_path(asset_name):
    file_path = os.path.join(project_root( ), "data", "library", "item", "phaedrus", asset_name)
    return file_path


def project_root( ):
    script_dir = os.path.dirname( __file__ )
    root = os.path.dirname( os.path.dirname( os.path.dirname( script_dir ) ) )
    return root


def generate_uuid():
    return str(uuid.uuid4())


def is_numeric(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def split_text_into_segments(text: str | None) -> list:
    if text is None:
        return [None] # This null is needed to preserve the indices when anomalous parts (like gaps) are found
    # Normalize spaces and split text by words and punctuation
    text = text.strip()
    # Adjust regex to properly split text including em dash and other punctuation
    segments = re.findall(r'\w+|[^\w\s]', text, re.UNICODE)
    return segments


def process_verse(xml_string, output_dir):
    # Replace <del> and </del> tags with a unique string
    xml_string = xml_string.replace('<del>', 'UNIQUE_STRING_FOR_DEL_START').replace('</del>',
                                                                                    'UNIQUE_STRING_FOR_DEL_END')
    xml_string = xml_string.replace('<gap reason="lost"/>', 'UNIQUE_STRING_FOR_GAP_LOST')

    # Parse the modified XML string
    root = ET.fromstring(xml_string)
    namespaces = {'tei': TEI_NAMESPACE, 'xml': 'http://www.w3.org/XML/1998/namespace'}

    works_data = []
    work_contents_data = []
    lines_for_macronizer = []
    work_content_subdivisions_data = []
    authors_data = []
    author_abbreviations_data = []
    work_abbreviations_data = []
    authors_and_works_data = []
    work_content_supplementary_data = []

    work_id = generate_uuid()
    title_element = root.find('.//tei:title[@xml:lang="lat"]', namespaces)
    work_name = title_element.text if title_element is not None else 'Unknown Title'
    work_data = get_work_data(work_id, work_name)
    works_data.append(work_data)
    print(f'Work: {work_id}, {work_name}')

    author_element = root.find('.//tei:author', namespaces)
    author_name = author_element.text if author_element is not None else 'Unknown Author'
    author_id = generate_uuid()
    author_data = get_author_data(author_id, author_name)
    authors_data.append(author_data)
    print(f'Author: {author_id}, {author_name}')

    # Adding standard abbreviation for the author
    # noinspection SpellCheckingInspection
    author_abbreviation = 'Phdr.'
    author_abbreviations_data.append([author_id, 0, author_abbreviation])

    # Linking author to work
    authors_and_works_data.append([author_id, work_id])

    fragment_index = 0  # Global index counter for fragments
    supplementary_index = {"NOTE": 0, "GAP": 0, "ABBR": 0}  # Note index counter

    # Flag to track sentence starts for context
    is_next_word_sentence_start = True
    
    inherent_states: Dict[str, int | None] = {}

    for work in root.findall('.//tei:div[@subtype="book"]', namespaces):
        book_node = generate_uuid()
        book_name = work.find('tei:head', namespaces).text if work.find('tei:head', namespaces) is not None else None
        book_head_text = ''.join(work.find('tei:head', namespaces).itertext()) \
            if work.find('tei:head', namespaces) is not None else None

        # Track the fromIndex for the book
        book_from_index = fragment_index

        # Add book head text to work_contents_data
        if book_head_text:
            book_head_segments = split_text_into_segments(book_head_text)
            line_str_for_api = ' '.join(s for s in book_head_segments if s)
            lines_for_macronizer.append(line_str_for_api)

            to_index = fragment_index + len(book_head_segments) - 1

            # noinspection SpellCheckingInspection
            book_head_sub = [work_id, generate_uuid(), 'TITL', 0, book_head_text, book_node, fragment_index, to_index]
            work_content_subdivisions_data.append(book_head_sub)
            print(f'Book Head Subdivision: {book_head_sub}')

            fragment_index, is_next_word_sentence_start = _process_text_segments(
                book_head_segments, work_id, fragment_index, is_next_word_sentence_start, work_contents_data, inherent_states
            )

        type_counters = {}

        for poem in work.findall('.//tei:div[@subtype="poem"]', namespaces):
            poem_id = poem.get('n')
            poem_name = poem.find('tei:head', namespaces).text if poem.find('tei:head',
                                                                            namespaces) is not None else None
            poem_node = generate_uuid()
            # noinspection SpellCheckingInspection
            typ = {"epilogus": "EPIL", "prologus": "PROL"}.get(poem_id, 'POEM' if str(poem_id).isdigit() else poem_id)

            if typ not in type_counters:
                type_counters[typ] = 0
            else:
                type_counters[typ] += 1

            seq = type_counters[typ]
            parent_node = book_node

            poem_lines = list(poem)
            to_index = fragment_index + sum(
                len(split_text_into_segments(line.text)) for line in poem_lines if line.text) - 1

            poem_sub = [work_id, poem_node, typ, seq, poem_name, parent_node, fragment_index, to_index]
            work_content_subdivisions_data.append(poem_sub)
            print(f'Subdivision: {poem_sub}')

            for line in poem_lines:

                is_next_word_sentence_start = True

                poem_line_node = generate_uuid()
                line_tag = line.tag.split('}')[-1]
                if line_tag == 'l':
                    typ = 'VERS'
                    poem_line_seq = int(line.get('n')) - 1
                elif line_tag == 'p':
                    typ = 'PARA'
                    poem_line_seq = 0
                elif line_tag == 'head':
                    # noinspection SpellCheckingInspection
                    typ = 'TITL'
                    poem_line_seq = 0
                else:
                    raise ValueError(f'Unknown tag {line_tag} found in poem.')
                # Replace the unique strings with <del> and </del> tags
                line_text = (line.text.replace('UNIQUE_STRING_FOR_DEL_START', '')
                             .replace('UNIQUE_STRING_FOR_DEL_END', '').strip()) if line.text else ''
                line_text = line_text.replace('UNIQUE_STRING_FOR_GAP_LOST', '').strip() if line.text else ''

                # Add to work_content_supplementary_data if <del> tag was found
                if 'UNIQUE_STRING_FOR_DEL_START' in line.text and 'UNIQUE_STRING_FOR_DEL_END' in line.text:
                    work_content_supplementary_data.append(
                        [work_id, "NOTE", supplementary_index["NOTE"], fragment_index,
                         fragment_index + len(split_text_into_segments(line_text)) - 1,
                         'marked for deletion'])
                    supplementary_index["NOTE"] += 1

                if 'UNIQUE_STRING_FOR_GAP_LOST' in line.text:
                    work_content_supplementary_data.append([work_id, "GAP", supplementary_index["GAP"], fragment_index,
                                                            fragment_index + len(split_text_into_segments(line_text)),
                                                            'lost'])
                    supplementary_index["GAP"] += 1
                    line_text = None

                to_index = fragment_index + len(split_text_into_segments(line_text)) - 1 if line_text else fragment_index

                work_content_subdivisions_data.append(
                    [work_id, poem_line_node, typ, poem_line_seq, line_text, poem_node,
                     fragment_index, to_index])

                line_segments = split_text_into_segments(line_text)
                line_str_for_api = ' '.join(s for s in line_segments if s)
                lines_for_macronizer.append(line_str_for_api)

                fragment_index, is_next_word_sentence_start = _process_text_segments(
                    line_segments, work_id, fragment_index, is_next_word_sentence_start, work_contents_data, inherent_states
                )

        for note in work.findall('.//tei:note', namespaces):
            note_id = note.get('n')
            from_index = fragment_index
            note_text = ''.join(note.itertext())
            to_index = fragment_index + len(note_text.split()) - 1
            work_content_supplementary_data.append(
                [work_id, "NOTE", supplementary_index["NOTE"], from_index, to_index, note_text])
            print(f'Note: {note_id}, {from_index}, {to_index}, {note_text}')
            supplementary_index["NOTE"] += 1
            fragment_index = to_index + 1

        book_seq = int(work.get('n')) - 1 if is_numeric(work.get('n')) else None
        if book_seq is None:
            # Find the maximum book_seq in the current work_content_subdivisions_data
            existing_book_seqs = [x[3] for x in work_content_subdivisions_data if x[2] == 'BOOK']
            book_seq = max(existing_book_seqs) + 1 if existing_book_seqs else 0

        # Set the toIndex for the book after processing all its content
        book_to_index = fragment_index - 1
        work_content_subdivisions_data.append(
            [work_id, book_node, 'BOOK', book_seq, book_name, None, book_from_index, book_to_index])

    works_df = pd.DataFrame(works_data, columns=['id', 'name', 'about'])
    work_contents_df = pd.DataFrame(work_contents_data, columns=['workId', 'idx', 'word', 'sourceReference', 'properNounState'])
    work_content_subdivisions_df = pd.DataFrame(work_content_subdivisions_data,
                                                columns=['workId', 'node', 'typ', 'cnt', 'name', 'parent', 'fromIndex',
                                                         'toIndex'])
    authors_df = pd.DataFrame(authors_data, columns=['id', 'name', 'about', 'image'])
    author_abbreviations_df = pd.DataFrame(author_abbreviations_data, columns=['authorId', 'id', 'val'])
    work_abbreviations_df = pd.DataFrame(work_abbreviations_data, columns=['workId', 'id', 'val'])
    authors_and_works_df = pd.DataFrame(authors_and_works_data, columns=['authorId', 'workId'])
    work_content_supplementary_df = pd.DataFrame(work_content_supplementary_data,
                                                 columns=['workId', 'typ', 'cnt', 'fromIndex', 'toIndex', 'val'])

    work_macronizations_data = []
    unambiguous_macronizations_dict = {}

    if not work_contents_df.empty:
        
        # 1. Identify which word types have an INHERENT state of 2.
        words_with_inherent_state_2 = {word for word, state in inherent_states.items() if state == 2}
        
        # 2. Of those candidates, find which ones ACTUALLY have different macrons.
        uncertain_depending_on_proper_noun_state = _different_macronizations_depending_on_status(words_with_inherent_state_2)

        # 3. Get contextual macronization for the entire work.
        full_text = '\n'.join(lines_for_macronizer)
        logging.info("Calling macronization API for the entire work to get contextual results...")
        api_results = macronize_text(full_text)

        if api_results:
            api_tokens = [res for res in api_results if not res['word'].isspace()]
            df_cursor = 0
            api_cursor = 0

            logging.info("Mapping macronization results and sorting into ambiguous/unambiguous tables...")
            while df_cursor < len(work_contents_df) and api_cursor < len(api_tokens):
                original_row = work_contents_df.iloc[df_cursor]
                original_word = original_row['word']
                word_idx = original_row['idx']

                # Skip processing for None
                if not original_word:
                    df_cursor += 1
                    continue

                # Reassemble clitics by greedily consuming API tokens
                reconstructed_word, combined_macronized, combined_mask = "", "", 0

                while api_cursor < len(api_tokens) and len(reconstructed_word) < len(original_word):
                    current_api_token = api_tokens[api_cursor]
                    reconstructed_word += current_api_token['word']
                    combined_macronized += current_api_token['macronized']
                    combined_mask |= current_api_token['uncertainty_mask']
                    api_cursor += 1

                if reconstructed_word != original_word:
                    logging.critical(
                        "Token synchronization failed at index %s. Expected '%s', reconstructed '%s'.",
                        word_idx,
                        original_word,
                        reconstructed_word
                    )
                    break # Stop processing to avoid cascading errors

                # 4. Decision logic: store in work-specific or global table
                lower_word = original_word.lower()
                is_macron_uncertain_by_pn_state = lower_word in uncertain_depending_on_proper_noun_state
                is_macron_uncertain_always = combined_mask != 0

                if is_macron_uncertain_always:
                    work_macronizations_data.append([work_id, word_idx, combined_macronized, combined_mask])
                elif is_macron_uncertain_by_pn_state:
                    logging.warning("'%s' at '%s' has different macrons depending on whether it's a proper noun or not", original_word, word_idx)
                    work_macronizations_data.append([work_id, word_idx, combined_macronized, combined_mask])
                else:
                    # The macrons are stable. It's safe for the global unambiguous table.
                    # Get the inherent state to decide HOW to save it
                    inherent_state = inherent_states.get(lower_word, 0)

                    if inherent_state == 0: # Common noun -> lowercase
                        unambiguous_macronizations_dict[original_word.lower()] = combined_macronized.lower()
                    elif inherent_state == 1: # Proper noun -> capitalized
                        unambiguous_macronizations_dict[original_word.capitalize()] = combined_macronized.capitalize()
                    elif inherent_state == 2: # Ambiguous, but only one possible macronization for each lemma -> store both
                        unambiguous_macronizations_dict[original_word.lower()] = combined_macronized.lower()
                        unambiguous_macronizations_dict[original_word.capitalize()] = combined_macronized.capitalize()
                    else: # None: don't store as unambiguous as it is technically an unknown word
                        logging.warning("'%s' is morphologically un-analyzable but has a certain macronization. Storing as-is.", original_word)
                        work_macronizations_data.append([work_id, word_idx, combined_macronized, combined_mask])

                df_cursor += 1

    # Convert dictionary to list for DataFrame creation
    unambiguous_macronizations_data = list(unambiguous_macronizations_dict.items())
    work_macronizations_df = pd.DataFrame(
        work_macronizations_data,
        columns=['workId', 'wordIdx', 'macronizedWord', 'uncertaintyBitMask']
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


def get_work_data(work_id, work_name):
    about_file = asset_path('about_phi0975_phi001.txt')
    with open(about_file, 'r', encoding='utf-8') as about:
        about_text = about.read()
    work_data = [work_id, work_name, about_text]
    return work_data


def get_author_data(author_id, author_name):
    about_file = asset_path('about.txt')
    with open(about_file, 'r', encoding='utf-8') as about:
        about_text = about.read()
    image_file = asset_path('expanded.webp')
    with open(image_file, 'rb') as expanded:
        image_data = expanded.read()
        image_data = base64.b64encode(image_data).decode()  # Convert binary data to base64 string
    author_data = [author_id, author_name, about_text, image_data]
    return author_data


def validate_csv_files(xml_string, output_dir):
    errors = []

    # Load the relevant CSV files
    work_contents_df = pd.read_csv(os.path.join(output_dir, 'work_contents.csv'))
    work_content_subdivisions_df = pd.read_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'))
    work_content_supplementary_df = pd.read_csv(os.path.join(output_dir, 'work_content_supplementary.csv'))
    author_abbreviations_df = pd.read_csv(os.path.join(output_dir, 'author_abbreviations.csv'))
    work_macronizations_df = pd.read_csv(os.path.join(output_dir, 'work_macronizations.csv'))
    unambiguous_macronizations_df = pd.read_csv(os.path.join(output_dir, 'unambiguous_macronizations.csv'))

    check_seq_unique_ints_from_0(errors, author_abbreviations_df, 'author abbreviations', 'id', ['authorId'])
    check_seq_unique_ints_from_0(errors, work_content_subdivisions_df, 'subs', 'cnt', ['workId', 'parent', 'typ'])
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
    check_proper_noun_completeness(errors, work_contents_df)
    check_macronization_coverage(errors, work_contents_df, work_macronizations_df, unambiguous_macronizations_df)

    if errors:
        logging.error("Validation errors found:")
        for error in errors:
            logging.error("    %s", error)
    else:
        logging.info("All validations passed successfully.")


def check_seq_unique_ints_from_0(errors, df, f_name, column_name, group_columns=None):
    def check_sequence_and_uniqueness(series):
        expected_values = pd.Series(range(0, len(series)))
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
                    errors.append(f"For {f_name}, column '{column_name}' in group ({group_name}) contains duplicate "
                                  f"values.")
                else:
                    errors.append(f"For {f_name}, column '{column_name}' in group ({group_name}) does not contain "
                                  f"sequential integers starting from 0.")
    else:
        sorted_values = df[column_name].sort_values().reset_index(drop=True)
        if not check_sequence_and_uniqueness(sorted_values):
            if sorted_values.nunique() != len(sorted_values):
                errors.append(f"Column '{column_name}' contains duplicate values.")
            else:
                errors.append(f"Column '{column_name}' does not contain sequential integers starting from 0.")


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

    # Count the number of elements in gap_tags
    num_gap_tags = len(gap_tags)

    # Create a list to store the idx values
    gap_indices = []

    # Iterate over the contents list for as many times as there are elements in gap_tags
    for _ in range(num_gap_tags):
        # For each iteration, find the corresponding entry in the contents list
        for content in contents:
            # If a corresponding entry is found, add the idx value to the list
            if pd.isnull(content['word']):
                gap_indices.append(content['idx'])
                break

    # Check if the number of gap tags is equal to the number of empty content entries
    if num_gap_tags != len(gap_indices):
        errors.append("Mismatch between the number of <gap> tags and the number of empty content entries.")

    # Check for corresponding subdivision entries
    for idx in gap_indices:
        matching_subdivisions = [sub for sub in subdivisions if sub['typ'] == 'VERS' and
                                 pd.isnull(sub['name']) and
                                 sub['fromIndex'] == idx and
                                 sub['toIndex'] == idx]
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


def check_proper_noun_completeness(errors, work_contents_df):
    """Checks that every alphabetic word has a proper noun state."""
    # Filter for rows that should be words (alphabetic strings)
    word_df = work_contents_df[work_contents_df['word'].fillna('').str.isalpha()]

    # Find words where the proper noun state is missing (null/NaN)
    missing_state = word_df[word_df['properNounState'].isnull()]

    if not missing_state.empty:
        # Report the first 5 problematic words for brevity
        examples = missing_state.head(50).apply(lambda row: f"'{row['word']}' at index {row['idx']}", axis=1).tolist()
        error_msg = (f"Found {len(missing_state)} words with a missing 'properNounState'. "
                     f"Examples: {', '.join(examples)}")
        errors.append(error_msg)


def check_macronization_coverage(errors, work_contents_df, work_macronizations_df, unambiguous_macronizations_df):
    """
    Checks that every word has a single, valid macronization source.
    - A word TYPE must not exist in both the stable and work-specific tables.
    - Every word INSTANCE must have a source in one of the tables.
    """
    # 1. Check any word TYPE appearing in both tables.
    # Get all unique word types (case-insensitive) from the stable, global table.
    stable_types = set(unambiguous_macronizations_df['word'].str.lower())

    # Get all unique word types (case-insensitive) from the work-specific table.
    # This requires merging with work_contents to get the actual word from the index.
    if not work_macronizations_df.empty:
        work_specific_merged = pd.merge(work_macronizations_df, work_contents_df, left_on='wordIdx', right_on='idx')
        work_specific_types = set(work_specific_merged['word'].str.lower())

        # Find the intersection of the two sets. Any overlap is a potential error.
        # This often happens when the script finds a normal use of a word AND a capitalized instance
        # that is not usually capitalized mid-sentence, in which cases the macronizer returns an unknown mask
        duplicate_types = stable_types.intersection(work_specific_types)
        if duplicate_types:
            examples = sorted(list(duplicate_types))[:50]
            error_msg = (
                f"Found {len(duplicate_types)} word types defined in BOTH the stable and work-specific "
                f"macronization tables. "
                f"Examples: {', '.join(examples)}"
            )
            errors.append(error_msg)
            # This is a fatal error; further checks for missing words are misleading.
            return

    # 2. If no types are duplicated, check that every individual word INSTANCE is covered.
    stable_word_forms = set(unambiguous_macronizations_df['word'])
    work_specific_indices = set(work_macronizations_df['wordIdx'])
    missing_instances = []

    # Filter for actual alphabetic words that need checking.
    word_df = work_contents_df[work_contents_df['word'].fillna('').str.isalpha()]

    for _, row in word_df.iterrows():
        word = row['word']
        idx = row['idx']

        # An instance is covered if its index is in the work-specific table
        # OR its specific form (respecting case) is in the stable table.
        # We also check case variations for the stable table as a fallback,
        # though ideally the stored form should match exactly.
        is_in_stable_table = (
            word in stable_word_forms or
            word.lower() in stable_word_forms or
            word.capitalize() in stable_word_forms
        )
        is_in_work_specific_table = idx in work_specific_indices

        if not is_in_stable_table and not is_in_work_specific_table:
            missing_instances.append(f"'{word}' (idx {idx})")

    if missing_instances:
        error_msg = (
            f"Found {len(missing_instances)} words missing a macronization entry entirely. "
            f"Examples: {', '.join(missing_instances[:50])}"
        )
        errors.append(error_msg)


if __name__ == "__main__":
    # noinspection HttpUrlsUsage
    xml_file = asset_path("phi0975.phi001.perseus-lat2_modified.xml")
    output_dir_outer = project_root( ) + '/output/library/item/phaedrus/'
    with open(xml_file, 'r', encoding='utf-8') as file:
        xml_string_outer = file.read()  # Parse the XML file as a string
    process_verse(xml_string_outer, output_dir_outer)
    print(f"Data has been successfully exported to CSV files in {output_dir_outer}.")
    validate_csv_files(xml_string_outer, output_dir_outer)  # Call the validation function here
