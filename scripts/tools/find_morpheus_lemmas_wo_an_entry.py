"""
find_morpheus_lemmas_wo_an_entry.py

This script cross-checks a list of lemmas from a formatted text file against a large
dictionary CSV to verify which lemmas exist in the database.

It specifically targets lines in the text file starting with the ':le:' tag (e.g., ':le:acer').
It also handles homograph disambiguators by stripping the '#' character before matching
(e.g., ':le:acer#2' is searched as 'acer2' in the CSV).

Usage:
    python -m scripts.tools.find_morpheus_lemmas_without_an_entry <path_to_txt_file> <path_to_csv_file>

    for example a stemsrc file of the Morpheus fork, such as stemlib/Latin/stemsrc/vbs.latin.irreg, and the
    dictionary_entries.csv that scripts/dictionary/process_lexica.py writes.

Expected CSV format:
    Must contain a header row with a column exactly named 'lemma'.
"""

import argparse
import csv
import sys


def main():
    parser = argparse.ArgumentParser(description="Match :le: lemmas against a huge CSV.")
    parser.add_argument("txt_file", help="Path to the text file with :le: patterns")
    parser.add_argument("csv_file", help="Path to the huge CSV file")
    args = parser.parse_args()

    # Increase CSV field size limit just in case the huge CSV has unusually long lines
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2147483647 else 2147483647)

    print("Loading CSV and building lemma index (this might take a moment)...")

    csv_lemmas = set()
    with open(args.csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Safely get the lemma column
            lemma = row.get('lemma')
            if lemma:
                # Add to set as lowercase for case-insensitive matching
                csv_lemmas.add(lemma.strip().lower())

    print(f"Loaded {len(csv_lemmas)} unique lemmas from CSV.\n")
    print("-" * 40)

    # ANSI Color codes for terminal visuals
    BLUE = "\033[38;2;0;170;255m"
    RED = "\033[91m"
    RESET = "\033[0m"

    with open(args.txt_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith(":le:"):
                # Extract string after ':le:'
                original_lemma = line[4:].strip()

                # Remove the '#' character so 'acer#2' becomes 'acer2', then lowercase
                search_lemma = original_lemma.replace('#', '').lower()

                # Only append the "searched as" string if the original lemma contained a '#'
                extra_info = f" (searched as {search_lemma})" if '#' in original_lemma else ""

                if search_lemma in csv_lemmas:
                    print(f"{BLUE}🔷 MATCH:      {original_lemma}{extra_info}{RESET}")
                else:
                    print(f"{RED}❌ NO MATCH:  {original_lemma}{extra_info}{RESET}")


if __name__ == "__main__":
    main()
