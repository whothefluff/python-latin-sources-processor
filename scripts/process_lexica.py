import csv
import io
import logging
import os
import re
import uuid

from lxml import etree

from scripts.process_lexica_aux.abbreviations import abbreviations
from scripts.process_lexica_aux.broken_itypes import broken_itypes
from scripts.process_lexica_aux.cites import cites
from scripts.process_lexica_aux.fake_itypes import fake_itypes
from scripts.process_lexica_aux.pos_tags import pos_tags

SUBSTITUTE_ABBREVIATIONS = True

# noinspection SpellCheckingInspection
PART_OF_SPEECH_BY_LEMMAS = {
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

ABBR_LEAD_CHARS = r"—([,.?!;:"

# Create filtered copies of cites and abbreviations
filtered_cites = { k: v for k, v in cites.items( ) if k not in abbreviations }
filtered_abbreviations = { k: v for k, v in abbreviations.items( ) if k not in cites }


# Sort both cites and abbreviations using the same sorting logic
def sort_key( item ):
    key, _ = item
    spaces = key.count( " " )
    return -spaces, -len( key )


sorted_cites = sorted( filtered_cites.items( ), key = sort_key )
sorted_abbreviations = sorted( filtered_abbreviations.items( ), key = sort_key )

# Aggregate cites substitutions
cite_patterns = []
cite_replacements = { }
for cite, replacement in sorted_cites:
    cite_patterns.append( re.escape( cite ) )
    cite_replacements[cite] = replacement
combined_cite_pattern = "|".join( cite_patterns )
COMBINED_CITES = re.compile( combined_cite_pattern )

# Aggregate abbreviations substitutions
abbr_patterns = []
abbr_replacements = { }
for abbr, replacement in sorted_abbreviations:
    full_abbr_pat = r"(^|\s|[" + ABBR_LEAD_CHARS + r"])" + re.escape( abbr )
    abbr_patterns.append( full_abbr_pat )
    abbr_replacements[abbr] = replacement
combined_abbr_pattern = "|".join( abbr_patterns )
COMBINED_ABBREVIATIONS = re.compile( combined_abbr_pattern )

CS_LEADING_CHARS = re.compile( r"^[,;:.]\s*" )
CS_EMPTY_PARENTHESES = re.compile( r"\s*\(\s*\)" )
CS_LOWERCASE_START = re.compile( r"^[a-z]" )
CS_TRAILING_CHARS = re.compile( r"[—,;:](?=\s?$)" )
CS_PUNC_WO_PREV_SPACE = re.compile( r"\s+([,.;:!?])" )
CS_PUNC_WO_NEXT_SPACE = re.compile( r"([,;:!?])\s*" )

ITYPE_POS_NO_DIGITS_END = re.compile( r"\d+$" )

ETYM_CONTENT = re.compile( r"<etym>(.*?)</etym>" )

UNAMBIGUOUS_VIDE = re.compile( r"<lbl>v.</lbl>" )


def clean_sense( t ):

    def clean_unmatched_parentheses( s ):
        stack = []
        to_remove = set( )
        # Find unmatched parentheses
        for i, char in enumerate( s ):
            if char == "(":
                stack.append( i )
            elif char == ")":
                if stack:
                    stack.pop( )
                else:
                    to_remove.add( i )
        # Add remaining open parentheses to remove set
        to_remove.update( stack )
        # Build the result string
        return "".join( char for i, char in enumerate( s ) if i not in to_remove )

    t = clean_unmatched_parentheses( t )
    # remove leading spaces, dots, and commas
    t = t.lstrip( " .," )
    # delete any of the following leading strings ", " ". " "; " ": ", including the spaces
    t = CS_LEADING_CHARS.sub( "", t )
    # delete empty parentheses
    t = CS_EMPTY_PARENTHESES.sub( "", t )
    # change first lowercase letter to uppercase
    t = CS_LOWERCASE_START.sub( lambda m: m.group( 0 ).upper( ), t )
    # delete any of the following trailing chars "—" "," ";" ":", even if followed by a space
    t = CS_TRAILING_CHARS.sub( "", t )
    # Remove spaces before certain punctuation marks
    t = CS_PUNC_WO_PREV_SPACE.sub( r"\1", t )
    # Ensure single space after punctuation marks (except for opening parentheses and quotes)
    t = CS_PUNC_WO_NEXT_SPACE.sub( r"\1 ", t )
    # Normalize whitespace
    t = " ".join( t.split( ) )
    return t


# noinspection SpellCheckingInspection
def delete_fake_itypes( xml_string ):
    """
    Replace all occurrences of specified <itype> tags with their corresponding values in the XML string.
    """
    # noinspection PyTypeChecker
    for e in fake_itypes:
        xml_string = xml_string.replace( f"<itype>{e}</itype>", e )
    return xml_string


def fix_itypes( xml_string ):
    """
    Replace all occurrences of broken tags
    """
    for old, new in broken_itypes.items( ):
        xml_string = xml_string.replace( old, new )
    return xml_string


# noinspection SpellCheckingInspection
def clean_itypes( xml_string ):
    xml_string = delete_fake_itypes( xml_string )
    xml_string = fix_itypes( xml_string )
    return xml_string


def clean_data( xml_string ):
    """
    Apply all data cleaning functions to the XML string.
    """
    logging.info( "Deleting fake itypes..." )
    xml_string = clean_itypes( xml_string )
    logging.info( "Substituting etym..." )
    xml_string = substitute_etym( xml_string )
    logging.info( "Substituting vide..." )
    xml_string = substitute_vide( xml_string )

    return xml_string


# noinspection SpellCheckingInspection
def part_of_speech_from_itype( lemma, itype ):

    def ends_with( suffix ):
        lemma_base = ITYPE_POS_NO_DIGITS_END.sub( "", lemma )
        return lemma_base.endswith( suffix )

    def itype_starts_with( prefix ):
        return itype.startswith( prefix )

    pos_from_itypes = [
        (lambda: (itype_starts_with("āre") or itype_starts_with("āvī"))
                 and ends_with("o"), "verb"),
        (lambda: (itype_starts_with("ārī") or itype_starts_with("ātus"))
                 and ends_with("or"), "verb"),
        (lambda: itype_starts_with("ēre") and ends_with("eo"), "verb"),
        (lambda: itype_starts_with("ērī") and ends_with("eor"), "verb"),
        (lambda: itype_starts_with("ĕre") and ends_with("o"), "verb"),
        (lambda: itype_starts_with("īre")
                 and (ends_with("io") or ends_with("eo")), "verb"),
        (lambda: itype_starts_with("īrī") and ends_with("ior"), "verb"),
        (lambda: (itype_starts_with("factus") or itype_starts_with("fĭĕri") or itype_starts_with("fieri"))
                 and ends_with("fio"), "verb"),
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
        (lambda: itype_starts_with("is")
                 and (ends_with("is") or ends_with("es")), "noun"),
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
        (lambda: (itype_starts_with("a, um") or itype_starts_with("a, um, and i") or itype_starts_with("ae, a")),
         "adjective"),
        (lambda: itype_starts_with("is") and ends_with('e'), "noun"),
        (lambda: itype_starts_with("e") and ends_with("lis"), "adjective"),
        (lambda: itype_starts_with("us") and ends_with("ior"), "adjective"),
    ]

    if lemma in PART_OF_SPEECH_BY_LEMMAS:
        return PART_OF_SPEECH_BY_LEMMAS[lemma]
    for condition, pos in pos_from_itypes:
        if condition( ):
            return pos
    return ""


def part_of_speech_from_hi_tag( entry ):
    hi_tag = entry.xpath( './/hi[@rend="ital"]' )
    if hi_tag and hi_tag[0].text in pos_tags:
        return pos_tags[hi_tag[0].text]
    return ""


def file( ):
    file_name = "lat.ls.perseus-eng2.xml"
    script_dir = os.path.dirname( __file__ )
    script_parent_dir = os.path.dirname( script_dir )
    # noinspection SpellCheckingInspection
    file_path = os.path.join( script_parent_dir, "data", "lexica", file_name )
    return file_path


# noinspection SpellCheckingInspection
def substitute_abbreviations( text ):
    """
    Perform advanced substitution on the text using cites and abbreviations dictionaries.
    Aggregates substitutions separately for cites and abbreviations.
    """

    def cite_replace( match ):
        m_content = match.group( 0 )
        return cite_replacements.get( m_content, m_content )

    def abbr_replace( match ):
        m_content = match.group( 0 )
        first_char = m_content[0]
        if first_char in ABBR_LEAD_CHARS + " ":
            return first_char + abbr_replacements.get( m_content[1:], m_content )
        else:
            return abbr_replacements.get( m_content, m_content )

    if SUBSTITUTE_ABBREVIATIONS:
        no_cites = COMBINED_CITES.sub( cite_replace, text )
        no_cites_nor_abbrs = COMBINED_ABBREVIATIONS.sub( abbr_replace, no_cites )
        return no_cites_nor_abbrs
    else:
        return text


def substitute_etym( text ):
    text = ETYM_CONTENT.sub( r"from \1", text )
    return text


def substitute_vide( text ):
    text = UNAMBIGUOUS_VIDE.sub( "see", text )
    return text


def write_csv_row( writer, row ):
    """
    Write a row to the CSV file, properly escaping and encoding each field.
    """
    writer.writerow( row )


def inflection_of( entry ):
    inflection = ""
    itype = entry.find( ".//itype" )
    if itype is not None:
        inflection = itype.text
    pos = entry.find( ".//pos" )
    if pos is not None:
        pos_text = pos_tags.get( pos.text, pos.text )
        if (not pos_text.startswith( "adjective" )
                and not pos_text.startswith( "participle" )
                and not pos_text.startswith( "verb" )):
            gen = entry.find( ".//gen" )
            if gen is not None:
                inflection += f'{", " if inflection else ""}{gen.text}'
    return inflection


def part_of_speech_of( entry, lemma ):
    part_of_speech = ""
    mood = entry.find( ".//mood" )
    if mood is not None:
        part_of_speech = pos_tags.get( mood.text, mood.text )
    pos = entry.find( ".//pos" )
    if pos is not None:
        pos_from_pos = pos_tags.get( pos.text, pos.text )
        if (part_of_speech != "participle"
                or (part_of_speech == "participle"
                    and pos_from_pos.startswith( "adjective" ))):
            part_of_speech += f'{", " if part_of_speech else ""}{pos_from_pos}'
    if not part_of_speech:
        itype = entry.find( ".//itype" )
        if itype is not None:
            part_of_speech = part_of_speech_from_itype( lemma, itype.text )
    if not part_of_speech:
        part_of_speech = part_of_speech_from_hi_tag( entry )
    return part_of_speech


def text_before_sense( parent, current, current_index ):
    """
    Extract text directly under entryFree (excluding previous content within nested tags)
    that appears before the current sense tag and not part of any previous sense tag.
    Nested tags following the initial free text are included in their order of occurrence.
    """

    def next_tag_is_first_not_excluded( prefix_started, element ):
        # noinspection SpellCheckingInspection
        inflection_tags = ("orth", "pos", "itype", "mood", "gen")
        return not prefix_started and element.getnext( ).tag not in inflection_tags

    def extract_for_first_sense( p, c ):
        r = ""
        start_capture = False
        for element in p.getchildren( ):
            if element.tag == "entryFree":
                continue
            if element.tag == "sense":
                break
            if next_tag_is_first_not_excluded( start_capture, element ):
                start_capture = True
                if element.tail is not None:
                    r += element.tail
                continue
            if start_capture:
                r += "".join( element.itertext( ) )
                if element.tail is not None:
                    r += element.tail
        if re.match( r"^[^(]*\)", r ):
            text_content = "".join( p.itertext( ) )
            op_par_index = text_content.find( "(" )
            sense_index = text_content.find( "".join( c.itertext( ) ) )
            if op_par_index != -1:
                r = text_content[op_par_index:sense_index]
        return r

    def extract_for_other_senses( p, c ):
        r = ""
        is_in_rage = False
        start_capture = False
        for element in p.getchildren( ):
            if element.getnext( ) == c:
                is_in_rage = True
            if is_in_rage and not (element.getnext( ) == c):
                break
            if is_in_rage and next_tag_is_first_not_excluded( start_capture, element ):
                start_capture = True
                if element.tail is not None:
                    r += element.tail
                continue
            if start_capture:
                r += "".join( element.itertext( ) )
                if element.tail is not None:
                    r += element.tail
        return r if r.strip( ) else ""

    extracted = (extract_for_first_sense( parent, current )
                 if current_index == 1
                 else extract_for_other_senses( parent, current ))
    return extracted


def concatenate_prefix( prefix, content ):

    def needs_space( ):
        if ((re.match( r".*[a-zA-Z0-9]$", prefix )
             and re.match( r"^[.,!?)}\]\"']", content ))
                or (re.match( r".*[.,!?)}\]\"']$", prefix )
                    and re.match( r"^[a-zA-Z0-9]", content ))):
            return not (prefix.endswith( " " ) or content.startswith( " " ))
        return False

    if not prefix:
        return content
    if content and needs_space( ):
        return prefix + " " + content
    return prefix + content


def text_without_nested( element ):
    """
    Get all text content from an element that is not inside nested tags,
    preserving the order of appearance.
    """
    # Start with the initial text content (if any)
    pieces = []
    if element.text:
        pieces.append( element.text )

    # Add the tail of each child in order
    for child in element:
        if child.tail:
            pieces.append( child.tail )

    return ''.join( pieces )


def parse_xml_and_write_csv( input_file, output_dir ):
    logging.basicConfig( level = logging.INFO )
    os.makedirs( output_dir, exist_ok = True )

    dictionaries_file = os.path.join( output_dir, "dictionaries.csv" )
    entries_file = os.path.join( output_dir, "dictionary_entries.csv" )
    senses_file = os.path.join( output_dir, "dict_entry_senses.csv" )
    quotes_file = os.path.join(output_dir, "dict_entry_sense_quotes.csv")

    # Read the entire XML file
    with open( input_file, "r", encoding = "utf-8" ) as f:
        logging.info( "Reading XML file..." )
        xml_content = f.read( )
    logging.info( "Cleaning XML data..." )
    xml_content = clean_data( xml_content )
    logging.info( "Creating BytesIO object..." )
    xml_bytes = xml_content.encode( "utf-8" )
    xml_file = io.BytesIO( xml_bytes )

    dictionary_id = str( uuid.uuid4( ) )

    with open( dictionaries_file, "w", newline = "", encoding = "utf-8" ) as f:
        writer = csv.writer( f )
        write_csv_row( writer, ["ID", "name", "language", "publisher", "publicationDate"] )
        write_csv_row( writer, [dictionary_id, "Lewis & Short", "EN", "Harper and Brothers", "1879-07-01 00:00:00.000Z"], )

    with (open( entries_file, "w", newline = "", encoding = "utf-8" ) as entries_csv,
          open( senses_file, "w", newline = "", encoding = "utf-8" ) as senses_csv,
          open( quotes_file, "w", newline = "", encoding = "utf-8" )):

        entries_writer = csv.writer( entries_csv )
        senses_writer = csv.writer( senses_csv )

        write_csv_row( entries_writer, ["dictionary", "lemma", "partOfSpeech", "inflection", "index"] )
        write_csv_row( senses_writer, ["dictionary", "lemma", "level", "prettyLevel", "content"] )
        # write_csv_row( quotes_writer, ["dictionary", "lemma", "level", "seq", "content", "translation"], )

        try:
            context = etree.iterparse( xml_file, events = ("end",), tag = "entryFree" )
            entry_counter = 0
            for event, entry in context:
                try:
                    lemma = entry.get( "key", "" )
                    logging.info( f"Processing entry: {lemma}" )

                    same_level_pos = entry.xpath( "./pos" )
                    any_pos = entry.xpath( ".//pos" )
                    # noinspection SpellCheckingInspection
                    if lemma == "volo1":
                        part_of_speech = "verb"
                        inflection = "irregular"
                    elif (same_level_pos
                          and same_level_pos[0].text in pos_tags
                          and pos_tags[same_level_pos[0].text] == "adverb"):
                        part_of_speech = "adverb"
                        inflection = "indeclinable"
                    elif (any_pos
                          and any_pos[0].text in pos_tags
                          and pos_tags[any_pos[0].text].startswith( "verb" )):
                        part_of_speech = "verb"
                        inflection = inflection_of( entry )
                    else:
                        part_of_speech = part_of_speech_of( entry, lemma )
                        inflection = inflection_of( entry )

                    write_csv_row( entries_writer, [dictionary_id, lemma, part_of_speech, inflection, entry_counter], )
                    entry_counter += 1

                    senses = entry.xpath( ".//sense" )

                    if not senses:
                        # Handle entries without sense tags
                        content = text_without_nested( entry )
                        content = substitute_abbreviations( content )
                        content = clean_sense( content )
                        if content:
                            write_csv_row( senses_writer,
                                           [dictionary_id, lemma, "001", "1", content] )

                    else:
                        level_stack = []
                        current_level = 0
                        for i, sense in enumerate( senses, 1 ):
                            level = int( sense.get( "level", "1" ) )

                            if level > current_level:
                                level_stack.append( 1 )
                            elif level < current_level:
                                level_stack = level_stack[:level]
                                level_stack[-1] += 1
                            else:
                                level_stack[-1] += 1

                            current_level = level

                            level_notation = ".".join( f"{l1:03d}" for l1 in level_stack )
                            pretty_level = ".".join( str( l2 ) for l2 in level_stack )

                            prefix_text = text_before_sense( entry, sense, i )
                            content = "".join( sense.itertext( ) )
                            if prefix_text:
                                content = concatenate_prefix( prefix_text, content )

                            content = substitute_abbreviations( content )
                            content = clean_sense( content )

                            write_csv_row( senses_writer,
                                           [dictionary_id, lemma, level_notation, pretty_level, content, ], )

                    # Clear the element to free memory
                    entry.clear( )
                    while entry.getprevious( ) is not None:
                        del entry.getparent( )[0]
                except Exception as e:
                    raise e
                    # logging.error(f"Error processing entry {lemma}: {str(e)}")
                    # continue

        except Exception as e:
            raise e
            # logging.error(f"Error parsing XML: {str(e)}")

    logging.info( "XML parsing and CSV writing completed successfully." )


if __name__ == "__main__":
    # noinspection SpellCheckingInspection
    parse_xml_and_write_csv( file( ), "../output/lexica/" )
    print( "XML parsing and CSV writing completed successfully." )
