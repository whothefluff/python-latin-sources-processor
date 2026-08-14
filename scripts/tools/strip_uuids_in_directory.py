#!/usr/bin/env python
# -*- coding: utf-8 -*-

import csv
import os
import re
import sys

# Increase CSV field size limit to handle large text fields (like author bios or long chunks)
maxInt = sys.maxsize
while True:
    try:
        csv.field_size_limit(maxInt)
        break
    except OverflowError:
        maxInt = int(maxInt/10)

# Matches standard 36-character UUIDs
UUID_PATTERN = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')

class UuidStripper:
    def __init__(self):
        self.uuid_map = {}
        self.next_id = 1

    def _replace_match(self, match):
        uuid_str = match.group(0)
        # Assign a simple sequential ID to each unique UUID encountered
        if uuid_str not in self.uuid_map:
            self.uuid_map[uuid_str] = f"ID_{self.next_id}"
            self.next_id += 1
        return self.uuid_map[uuid_str]

    def process_directory(self, input_dir: str, output_dir: str):
        if not os.path.exists(input_dir):
            print(f"Error: Input directory '{input_dir}' does not exist.")
            sys.exit(1)

        # Walk the directory tree recursively
        for root, dirs, files in os.walk(input_dir):
            # Sort directories and files to ensure consistent ID assignment across runs
            dirs.sort()
            files.sort()

            for filename in files:
                if not filename.endswith('.csv'):
                    continue

                input_path = os.path.join(root, filename)

                # Calculate relative path to maintain folder structure in output
                rel_path = os.path.relpath(input_path, input_dir)
                output_path = os.path.join(output_dir, rel_path)

                # Create output subdirectories if needed
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                with open(input_path, 'r', encoding='utf-8') as fin, \
                        open(output_path, 'w', encoding='utf-8', newline='') as fout:

                    reader = csv.reader(fin)
                    writer = csv.writer(fout)

                    for row in reader:
                        new_row = []
                        for cell in row:
                            if cell:
                                # Replace any UUIDs found in the cell string
                                new_cell = UUID_PATTERN.sub(self._replace_match, cell)
                                new_row.append(new_cell)
                            else:
                                new_row.append(cell)
                        writer.writerow(new_row)
                print(f"Stripped UUIDs from {rel_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python strip_uuids_in_directory.py <input_dir> <output_dir>")
        sys.exit(1)

    input_directory = sys.argv[1]
    output_directory = sys.argv[2]

    stripper = UuidStripper()
    stripper.process_directory(input_directory, output_directory)
    print(f"\nDone! Stripped files saved to: {output_directory}")