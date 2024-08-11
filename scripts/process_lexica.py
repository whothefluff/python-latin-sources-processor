# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
import csv
import uuid
import os
from collections import defaultdict
import unicodedata
import re

from scripts.process_lexica_aux.abbreviations import abbreviations
from scripts.process_lexica_aux.fake_itypes import fake_itypes
from scripts.process_lexica_aux.broken_itypes import broken_itypes
from scripts.process_lexica_aux.pos_tags import pos_tags

SUBSTITUTE_ABBREVIATIONS = False

# noinspection SpellCheckingInspection
part_of_speech_by_lemmas = {
    "Itys": "noun",
    "iste": "demonstrative pronoun",
    "duo": "numeral",
    "istic1": "demonstrative pronoun",
    "cujas": "adjective",
    "ambo": "adjective",
    "Umber": "adjective",
    "segnitia": "noun",
    "volo1": "verb",
}


# noinspection SpellCheckingInspection
def delete_fake_itypes(xml_string):
    """
    Replace all occurrences of specified <itype> tags with their corresponding values in the XML string.
    """
    # noinspection PyTypeChecker
    for e in fake_itypes:
        xml_string = xml_string.replace(f'<itype>{e}</itype>', e)
    return xml_string


def fix_itypes(xml_string):
    """
    Replace all occurrences of broken tags
    """
    for old, new in broken_itypes.items():
        xml_string = xml_string.replace(old, new)
    return xml_string


# noinspection SpellCheckingInspection
def clean_itypes(xml_string):
    xml_string = delete_fake_itypes(xml_string)
    xml_string = fix_itypes(xml_string)
    return xml_string


def clean_data(xml_string):
    """
    Apply all data cleaning functions to the XML string.
    """
    xml_string = clean_itypes(xml_string)

    # Add more cleaning functions here as needed

    return xml_string


# noinspection SpellCheckingInspection
def part_of_speech_from_itype(lemma, itype):
    if lemma in part_of_speech_by_lemmas:
        return part_of_speech_by_lemmas[lemma]

    lemma_base = re.sub(r'\d+$', '', lemma)

    # Helper functions for common checks
    def ends_with(suffix):
        return lemma_base.endswith(suffix)

    def itype_starts_with(prefix):
        return itype.startswith(prefix)

    # Rules for determining part of speech
    rules = [
        (lambda: (itype_starts_with("āre") or itype_starts_with("āvī")) and ends_with("o"), "verb"),
        (lambda: (itype_starts_with("ārī") or itype_starts_with("ātus")) and ends_with("or"), "verb"),
        (lambda: itype_starts_with("ēre") and ends_with("eo"), "verb"),
        (lambda: itype_starts_with("ērī") and ends_with("eor"), "verb"),
        (lambda: itype_starts_with("ĕre") and ends_with("o"), "verb"),
        (lambda: itype_starts_with("īre") and (ends_with("io") or ends_with("eo")), "verb"),
        (lambda: itype_starts_with("īrī") and ends_with("ior"), "verb"),
        (lambda: (itype_starts_with("factus")
                  or itype_starts_with("fĭĕri")
                  or itype_starts_with("fieri")) and ends_with("fio"), "verb"),
        (lambda: itype_starts_with("ae") and ends_with("a"), "noun"),
        (lambda: itype in ["adis", "atis"] and ends_with("as"), "noun"),
        (lambda: itype_starts_with("i") and ends_with(("us", "um", "os", "on")), "noun"),
        (lambda: itype in ["ĭum", "ium"] and ends_with("es"), "noun"),
        (lambda: itype in ["ii", "ĭi"] and ends_with(("ium", "ius", "ion", "ios")), "noun"),
        (lambda: itype in ["onis", "ōnis"] and ends_with("io"), "noun"),
        (lambda: itype in ["oris", "ōris"] and ends_with("or"), "noun"),
        (lambda: itype in ["us", "ūs"] and ends_with("us"), "noun"),
        (lambda: itype in ['em, ē', "ontis", 'um', 'ārum', 'ātis', 'ădis', "ēs", "īcis", "ĭdis", "ōrum", "ŏris", "ōris",
                           "ŏpis", "ŏnis", "ōnis", "ōtis", "ĭtis", "ĭnis"], "noun"),
        (lambda: itype_starts_with("ae") or itype_starts_with("antis"), "noun"),
        (lambda: itype_starts_with("is") and (ends_with("is") or ends_with("es")), "noun"),
        (lambda: itype_starts_with("ēi") and ends_with("ies"), "noun"),
        (lambda: itype_starts_with("tri") and ends_with("ter"), "noun"),
        (lambda: itype in ["ĭum", "ium"] and ends_with("ia"), "noun"),
        (lambda: itype_starts_with("ĭcis") and ends_with("x"), "noun"),
        (lambda: itype in ["ācis", "ăcis"] and ends_with("ax"), "noun"),
        (lambda: itype in ["ālis", "ălis"] and ends_with("al"), "noun"),
        (lambda: itype_starts_with("ānis") and ends_with("an"), "noun"),
        (lambda: itype in ["āris", "ăris"] and ends_with("ar"), "noun"),
        (lambda: itype_starts_with("ătis") and ends_with("ma"), "noun"),
        (lambda: itype in ["ĕris", "ĕri"] and ends_with("er"), "noun"),
        (lambda: itype_starts_with("ĕi") and ends_with("eus"), "noun"),
        (lambda: itype_starts_with("ētis") and ends_with("es"), "noun"),
        (lambda: (itype_starts_with("a, um") or itype_starts_with("a, um, and i")
                  or itype_starts_with("ae, a")), "adjective"),
        (lambda: itype_starts_with("is") and ends_with('e'), "noun"),
        (lambda: itype_starts_with("e") and ends_with("lis"), "adjective"),
        (lambda: itype_starts_with("us") and ends_with("ior"), "adjective"),
    ]

    for condition, pos in rules:
        if condition():
            return pos

    return ""


def part_of_speech_from_hi_tag(entry):
    hi_tag = entry.find('.//hi[@rend="ital"]')
    if hi_tag is not None and hi_tag.text in pos_tags:
        return pos_tags[hi_tag.text]
    return ""


def file():
    file_name = "lat.ls.perseus-eng2.xml"
    script_dir = os.path.dirname(__file__)
    script_parent_dir = os.path.dirname(script_dir)
    file_path = os.path.join(script_parent_dir, "data", "lexica", file_name)
    return file_path


def create_level_notation(levels):
    """
    Create a hierarchical level notation based on the given levels.
    """
    return '.'.join(f"{level:03d}" for level in levels)


def clean_text(text):
    """
    Clean and normalize text, removing control characters and normalizing whitespace.
    """
    # Remove control characters
    text = ''.join(ch for ch in text if unicodedata.category(ch)[0] != 'C')

    # Normalize whitespace
    text = ' '.join(text.split())

    return text


def substitute_abbreviations(text):
    """
    Substitute abbreviations in the text, avoiding substitutions within <bibl> tags
    and giving precedence to longer abbreviations.
    """
    if not SUBSTITUTE_ABBREVIATIONS:
        return text
    # Sort abbreviations by length (longest first) to ensure longer matches take precedence
    sorted_abbrevs = sorted(abbreviations.keys(), key=len, reverse=True)

    # Split the text by <bibl> tags
    parts = re.split(r'(<bibl>.*?</bibl>)', text, flags=re.DOTALL)

    for i in range(0, len(parts), 2):
        # Only process parts outside <bibl> tags
        for abbr in sorted_abbrevs:
            parts[i] = re.sub(r'\b' + re.escape(abbr) + r'\b',
                              lambda m: abbreviations[m.group(0)], parts[i])

    return ''.join(parts)


def escape_csv_field(field):
    """
    Escape special characters in CSV fields and enclose in quotes if necessary.
    """
    if re.search(r'[,"\n\r]', field):
        return f'"{field.replace('"', '""')}"'
    return field


def write_csv_row(writer, row):
    """
    Write a row to the CSV file, properly escaping and encoding each field.
    """
    escaped_row = [escape_csv_field(str(field)) for field in row]
    writer.writerow(escaped_row)


def inflection_of(entry):
    """
    Extract inflection information from the entry.
    """
    inflection = ''
    itype = entry.find('.//itype')
    if itype is not None:
        inflection = itype.text
    # Only add gender information if the part of speech is not an adjective
    pos = entry.find('.//pos')
    if pos is not None:
        pos_text = pos_tags[pos.text] if pos.text in pos_tags else pos.text
        if (not pos_text.startswith('adjective') and not pos_text.startswith('participle')
                and not pos_text.startswith('verb')):
            gen = entry.find('.//gen')
            if gen is not None:
                inflection += f'{", " if inflection else ""}{gen.text}'

    return inflection


def part_of_speech_of(entry, lemma):
    part_of_speech = ''
    mood = entry.find('.//mood')
    if mood is not None:
        part_of_speech = pos_tags[mood.text] if mood.text in pos_tags else mood.text
    pos = entry.find('.//pos')
    if pos is not None:
        pos_from_pos = pos_tags[pos.text] if pos.text in pos_tags else pos.text
        if part_of_speech != 'participle' \
                or (part_of_speech == 'participle' and pos_from_pos.startswith('adjective')):
            part_of_speech += f'{", " if part_of_speech else ""}{pos_from_pos}'
    # If both mood and pos are empty, determine part of speech using fallback logic
    if not part_of_speech:
        # noinspection SpellCheckingInspection
        itype = entry.find('.//itype')
        # noinspection SpellCheckingInspection
        if itype is not None:
            part_of_speech = part_of_speech_from_itype(lemma, itype.text)
    # If still empty, check for error-prone <hi rend="ital"> tags (sometimes they refer to other words)
    if not part_of_speech:
        part_of_speech = part_of_speech_from_hi_tag(entry)
    return part_of_speech


def parse_xml_and_write_csv(input_file, output_dir):
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Define output CSV files
    dictionaries_file = os.path.join(output_dir, 'dictionaries.csv')
    entries_file = os.path.join(output_dir, 'dictionary_entries.csv')
    senses_file = os.path.join(output_dir, 'dict_entry_senses.csv')
    quotes_file = os.path.join(output_dir, 'dic_entry_sense_quotes.csv')

    # Create a unique ID for the dictionary
    dictionary_id = str(uuid.uuid4())

    # Write to Dictionaries CSV
    with open(dictionaries_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        write_csv_row(writer, ['ID', 'name', 'language', 'publisher', 'publicationDate'])
        write_csv_row(writer, [dictionary_id, 'Lewis & Short', 'EN', 'Perseus Digital Library', ''])

    # Read and clean XML data
    with open(input_file, 'r', encoding='utf-8') as f:
        xml_string = f.read()
    cleaned_xml_string = clean_data(xml_string)

    # Parse cleaned XML
    root = ET.fromstring(cleaned_xml_string)

    with open(entries_file, 'w', newline='', encoding='utf-8') as entries_csv, \
            open(senses_file, 'w', newline='', encoding='utf-8') as senses_csv, \
            open(quotes_file, 'w', newline='', encoding='utf-8') as quotes_csv:

        entries_writer = csv.writer(entries_csv)
        senses_writer = csv.writer(senses_csv)
        quotes_writer = csv.writer(quotes_csv)

        # Write headers
        write_csv_row(entries_writer, ['dictionary', 'lemma', 'partOfSpeech', 'inflection'])
        write_csv_row(senses_writer, ['dictionary', 'lemma', 'level', 'prettyLevel', 'content'])
        write_csv_row(quotes_writer, ['dictionary', 'lemma', 'level', 'seq', 'content', 'translation'])

        for entry in root.findall('.//entryFree'):

            lemma = entry.get('key', '')

            # Check for <pos>adverb</pos> directly inside entryFree
            same_level_pos = entry.find('./pos')
            any_pos = entry.find('.//pos')
            # noinspection SpellCheckingInspection
            if lemma == 'volo1':
                part_of_speech = 'verb'
                inflection = 'irregular'
            elif same_level_pos is not None and same_level_pos.text in pos_tags and pos_tags[
                    same_level_pos.text] == 'adverb':
                part_of_speech = 'adverb'
                inflection = 'indeclinable'
            elif any_pos is not None and any_pos.text in pos_tags and pos_tags[any_pos.text].startswith('verb'):
                part_of_speech = 'verb'
                inflection = inflection_of(entry)
            else:
                part_of_speech = part_of_speech_of(entry, lemma)
                inflection = inflection_of(entry)

            # Write to DictionaryEntries CSV
            write_csv_row(entries_writer, [dictionary_id, lemma, part_of_speech, inflection])

            # Process senses
            senses = entry.findall('.//sense')
            level_map = defaultdict(lambda: defaultdict(int))

            # First pass: map levels and n values
            for sense in senses:
                level = int(sense.get('level', '1'))
                n = sense.get('n', '')
                if n:
                    level_map[level][n] += 1

            # Second pass: create level notations and write to CSV
            for sense in senses:
                level = int(sense.get('level', '1'))
                n = sense.get('n', '')

                # Generate level notation
                levels = []
                for i in range(1, level + 1):
                    if i in level_map:
                        if n and i == level:
                            levels.append(sorted(level_map[i].keys()).index(n) + 1)
                        else:
                            levels.append(len(level_map[i]))
                    else:
                        levels.append(1)

                level_notation = create_level_notation(levels)
                pretty_level = '.'.join(str(level) for level in levels)

                # Get sense content and substitute abbreviations
                content = ' '.join(sense.itertext()).strip()
                content = substitute_abbreviations(content)

                # Write to DictEntrySenses CSV
                write_csv_row(senses_writer, [dictionary_id, lemma, level_notation, pretty_level, content])

                # Process quotes
                for seq, quote in enumerate(sense.findall('.//quote'), 1):
                    quote_content = ' '.join(quote.itertext()).strip()
                    quote_content = substitute_abbreviations(quote_content)
                    translation = quote.find('trans')
                    trans_content = ' '.join(translation.itertext()).strip() if translation is not None else ''
                    trans_content = substitute_abbreviations(trans_content)

                    # Write to DicEntrySenseQuotes CSV
                    write_csv_row(quotes_writer,
                                  [dictionary_id, lemma, level_notation, seq, quote_content, trans_content])


if __name__ == "__main__":
    parse_xml_and_write_csv(file(), '../output/lexica/')
    print("XML parsing and CSV writing completed successfully.")
