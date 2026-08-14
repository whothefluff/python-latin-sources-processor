import os
import re
import sys
import xml.etree.ElementTree as ET

def extract_text_from_xml(xml_string):
    """Extracts raw text from XML, ignoring tags and namespaces."""
    # Strip out the xmlns declarations to make parsing easier
    xml_string = re.sub(r'\sxmlns="[^"]+"', '', xml_string, count=1)
    root = ET.fromstring(xml_string)
    return "".join(root.itertext())

def find_latin_entities(text):
    """Finds Roman numerals and Latin name abbreviations."""
    # Roman Numerals: Strictly uppercase MDCLXVI bounded by word edges
    roman_regex = r'\b[MDCLXVI]+\b'

    # Abbreviations: Matches M., Cn., T. optionally followed by a capitalized name
    abbrev_regex = r'\b(?:[A-Z][a-z]{0,2}\.\s*)+(?:[A-Z][a-z]+)?'

    numerals = re.findall(roman_regex, text)
    abbreviations = re.findall(abbrev_regex, text)

    # Clean up whitespace and remove duplicates
    abbreviations = list(dict.fromkeys(abbr.strip() for abbr in abbreviations))
    numerals = list(dict.fromkeys(numerals))

    return numerals, abbreviations

def process_file(filepath):
    """Processes a single XML file."""
    filename = os.path.basename(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            xml_content = file.read()
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return

    try:

        raw_text = extract_text_from_xml(xml_content)
        numerals, abbreviations = find_latin_entities(raw_text)

        print(f"\n📄 File: {filename}")
        if numerals or abbreviations:
            if abbreviations:
                print("   Abbreviations found:")
                for abbr in abbreviations:
                    print(f"      - {abbr}")

            if numerals:
                print("   Roman Numerals found:")
                for num in numerals:
                    print(f"      - {num}")
        else:
            print("   No Roman numerals or abbreviations found.")

    except ET.ParseError as e:
        print(f"❌ {filename}: invalid XML ({e})")
        return

def process_path(target_path):
    """Determines if the path is a file or directory and processes accordingly."""
    # Check if the user passed a specific FILE
    if os.path.isfile(target_path):
        if target_path.lower().endswith('.xml'):
            print(f"Processing single file...\n" + "="*50)
            process_file(target_path)
        else:
            print(f"❌ Error: The file '{target_path}' is not an .xml file.")

    # Check if the user passed a DIRECTORY (folder)
    elif os.path.isdir(target_path):
        xml_files = [f for f in os.listdir(target_path) if f.lower().endswith('.xml')]

        if not xml_files:
            print(f"⚠️ No .xml files found in '{target_path}'.")
            return

        print(f"Found {len(xml_files)} XML file(s) in directory. Beginning scan...\n" + "="*50)
        for filename in xml_files:
            filepath = os.path.join(target_path, filename)
            process_file(filepath)

    # Path doesn't exist at all
    else:
        print(f"❌ Error: The path '{target_path}' does not exist.")

if __name__ == "__main__":
    # Check if the user provided a path as a command-line argument
    if len(sys.argv) > 1:
        target_input = sys.argv[1]
    else:
        # Prompt user if they just ran the script normally
        print("Please enter the path to an XML file OR a directory containing XML files:")
        target_input = input("Path: ").strip()

        # Remove quotes if the user copy/pasted a path with quotes around it
        if target_input.startswith(('"', "'")) and target_input.endswith(('"', "'")):
            target_input = target_input[1:-1]

    process_path(target_input)