import csv
import uuid
import os
import unicodedata
import re
from lxml import etree
import logging

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


def clean_content(content):
    """
    Clean up content by removing spaces after punctuation and normalizing whitespace.
    """
    # Remove spaces after punctuation
    content = re.sub(r'\s+([.,;:!?])', r'\1', content)

    # Normalize whitespace
    content = ' '.join(content.split())

    return content


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
    hi_tag = entry.xpath('.//hi[@rend="ital"]')
    if hi_tag and hi_tag[0].text in pos_tags:
        return pos_tags[hi_tag[0].text]
    return ""


def file():
    file_name = "lat.ls.perseus-eng2.xml"
    script_dir = os.path.dirname(__file__)
    script_parent_dir = os.path.dirname(script_dir)
    # noinspection SpellCheckingInspection
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


# noinspection SpellCheckingInspection
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
    inflection = ''
    itype = entry.find('.//itype')
    if itype is not None:
        inflection = itype.text
    pos = entry.find('.//pos')
    if pos is not None:
        pos_text = pos_tags.get(pos.text, pos.text)
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
        part_of_speech = pos_tags.get(mood.text, mood.text)
    pos = entry.find('.//pos')
    if pos is not None:
        pos_from_pos = pos_tags.get(pos.text, pos.text)
        if part_of_speech != 'participle' \
                or (part_of_speech == 'participle' and pos_from_pos.startswith('adjective')):
            part_of_speech += f'{", " if part_of_speech else ""}{pos_from_pos}'
    if not part_of_speech:
        itype = entry.find('.//itype')
        if itype is not None:
            part_of_speech = part_of_speech_from_itype(lemma, itype.text)
    if not part_of_speech:
        part_of_speech = part_of_speech_from_hi_tag(entry)
    return part_of_speech


def text_before_sense(parent, current, current_index):
    """
    Extract text directly under entryFree (excluding previous content within nested tags)
    that appears before the current sense tag and not part of any previous sense tag.
    Nested tags following the initial free text are included in their order of occurrence.
    """

    def clean(text):
        # remove leading punctuation signs
        while text and text[0] in ' .,':
            text = text.lstrip(' .,')
            # Normalize whitespace: replace any sequence of whitespace characters (including newlines) with a single space
        text = re.sub(r'\s+', ' ', text)
        # Remove spaces before certain punctuation marks
        text = re.sub(r'\s+([,.;:!?])', r'\1', text)
        # Ensure single space after punctuation marks (except for opening parentheses and quotes)
        text = re.sub(r'([,.;:!?])\s*', r'\1 ', text)
        # Remove trailing line breaks
        text = text.rstrip('\n\r')
        return text


    def extract_for_first_sense(p):
        r = ""
        # noinspection SpellCheckingInspection
        inflection_tags = ('orth', 'pos', 'itype', 'mood', 'gen')
        start_capture = False
        for element in p.getchildren():
            if element.tag == 'entryFree':
                continue
            if element.tag == 'sense':
                break
            if not start_capture and element.getnext().tag not in inflection_tags:
                start_capture = True
                if element.tail is not None:
                    r += element.tail
                continue
            if start_capture:
                r += ''.join(element.itertext())
                if element.tail is not None:
                    r += element.tail
        return r


    def extract_for_other_senses(p, c):
        r = ""
        # noinspection SpellCheckingInspection
        inflection_tags = ('orth', 'pos', 'itype', 'mood', 'gen')
        is_in_rage = False
        start_capture = False
        for element in p.getchildren():
            if element.getnext() == c:
                is_in_rage = True
            if is_in_rage and not (element.getnext() == c):
                break
            if is_in_rage and not start_capture and element.getnext().tag not in inflection_tags:
                start_capture = True
                if element.tail is not None:
                    r += element.tail
                continue
            if start_capture:
                r += ''.join(element.itertext())
                if element.tail is not None:
                    r += element.tail
        return r if r.strip() else ''


    extracted = extract_for_first_sense(parent) if current_index == 1 else extract_for_other_senses(parent, current)
    return clean(extracted)


def concatenate_prefix(prefix, content):
    def needs_space(last_char, first_char):
        if (re.match(r".*[a-zA-Z0-9]$", prefix) and re.match(r"^[.,!?)}\]\"']", content)) or \
                (re.match(r".*[.,!?)}\]\"']$", prefix) and re.match(r"^[a-zA-Z0-9]", content)):
            return not (prefix.endswith(" ") or content.startswith(" "))
        return False

    if not prefix:
        return content
    if content and needs_space(prefix, content):
            return prefix + ' ' + content
    return prefix + content


def parse_xml_and_write_csv(input_file, output_dir):
    logging.basicConfig(level=logging.INFO)
    os.makedirs(output_dir, exist_ok=True)

    dictionaries_file = os.path.join(output_dir, 'dictionaries.csv')
    entries_file = os.path.join(output_dir, 'dictionary_entries.csv')
    senses_file = os.path.join(output_dir, 'dict_entry_senses.csv')
    quotes_file = os.path.join(output_dir, 'dic_entry_sense_quotes.csv')

    dictionary_id = str(uuid.uuid4())

    with open(dictionaries_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        write_csv_row(writer, ['ID', 'name', 'language', 'publisher', 'publicationDate'])
        write_csv_row(writer, [dictionary_id, 'Lewis & Short', 'EN', 'Perseus Digital Library', ''])

    with open(entries_file, 'w', newline='', encoding='utf-8') as entries_csv, \
            open(senses_file, 'w', newline='', encoding='utf-8') as senses_csv, \
            open(quotes_file, 'w', newline='', encoding='utf-8') as quotes_csv:

        entries_writer = csv.writer(entries_csv)
        senses_writer = csv.writer(senses_csv)
        quotes_writer = csv.writer(quotes_csv)

        write_csv_row(entries_writer, ['dictionary', 'lemma', 'partOfSpeech', 'inflection'])
        write_csv_row(senses_writer, ['dictionary', 'lemma', 'level', 'prettyLevel', 'content'])
        write_csv_row(quotes_writer, ['dictionary', 'lemma', 'level', 'seq', 'content', 'translation'])

        try:
            context = etree.iterparse(input_file, events=('end',), tag='entryFree')
            for event, entry in context:
                try:
                    lemma = entry.get('key', '')
                    logging.info(f"Processing entry: {lemma}")

                    same_level_pos = entry.xpath('./pos')
                    any_pos = entry.xpath('.//pos')
                    if lemma == 'volo1':
                        part_of_speech = 'verb'
                        inflection = 'irregular'
                    elif (same_level_pos and same_level_pos[0].text in pos_tags and
                          pos_tags[same_level_pos[0].text] == 'adverb'):
                        part_of_speech = 'adverb'
                        inflection = 'indeclinable'
                    elif any_pos and any_pos[0].text in pos_tags and pos_tags[any_pos[0].text].startswith('verb'):
                        part_of_speech = 'verb'
                        inflection = inflection_of(entry)
                    else:
                        part_of_speech = part_of_speech_of(entry, lemma)
                        inflection = inflection_of(entry)

                    write_csv_row(entries_writer, [dictionary_id, lemma, part_of_speech, inflection])

                    senses = entry.xpath('.//sense')
                    level_stack = []
                    current_level = 0

                    for i, sense in enumerate(senses, 1):
                        level = int(sense.get('level', '1'))

                        if level > current_level:
                            level_stack.append(1)
                        elif level < current_level:
                            level_stack = level_stack[:level]
                            level_stack[-1] += 1
                        else:
                            level_stack[-1] += 1

                        current_level = level

                        level_notation = '.'.join(f"{l1:03d}" for l1 in level_stack)
                        pretty_level = '.'.join(str(l2) for l2 in level_stack)

                        prefix_text = text_before_sense(entry, sense, i)
                        content = ' '.join(sense.xpath('.//text()'))
                        if prefix_text:
                            content = concatenate_prefix(prefix_text, content)

                        content = substitute_abbreviations(content)
                        content = clean_content(content)

                        write_csv_row(senses_writer, [dictionary_id, lemma, level_notation, pretty_level, content])

                        for seq, quote in enumerate(sense.xpath('.//quote'), 1):
                            quote_content = ' '.join(quote.xpath('.//text()'))
                            quote_content = clean_content(quote_content)
                            translation = quote.xpath('.//trans')
                            trans_content = ' '.join(translation[0].xpath('.//text()')) if translation else ''
                            trans_content = clean_content(trans_content)

                            write_csv_row(quotes_writer,
                                          [dictionary_id, lemma, level_notation, seq, quote_content, trans_content])

                    # Clear the element to free memory
                    entry.clear()
                    while entry.getprevious() is not None:
                        del entry.getparent()[0]
                except Exception as e:
                    logging.error(f"Error processing entry {lemma}: {str(e)}")
                    continue

        except Exception as e:
            logging.error(f"Error parsing XML: {str(e)}")

    logging.info("XML parsing and CSV writing completed successfully.")


if __name__ == "__main__":
    # noinspection SpellCheckingInspection
    parse_xml_and_write_csv(file(), '../output/lexica/')
    print("XML parsing and CSV writing completed successfully.")
