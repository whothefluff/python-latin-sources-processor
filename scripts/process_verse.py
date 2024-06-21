import xml.etree.ElementTree as ET
import pandas as pd
import os
import uuid
import tkinter as tk
from tkinter import filedialog
import re


def choose_file():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    file_path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml")])
    return file_path


def generate_uuid():
    return str(uuid.uuid4())


def is_numeric(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def split_text_into_segments(text):
    if text is None:
        return [None]
    # Normalize spaces and split text by words and punctuation
    text = text.strip()
    # Adjust regex to properly split text including em dash and other punctuation
    segments = re.findall(r'\w+|[^\w\s]', text, re.UNICODE)
    return segments


def process_verse(xml_file, output_dir):
    # Parse the XML file as a string
    with open(xml_file, 'r', encoding='utf-8') as file:
        xml_string = file.read()

    # Replace <del> and </del> tags with a unique string
    xml_string = xml_string.replace('<del>', 'UNIQUE_STRING_FOR_DEL_START').replace('</del>',
                                                                                    'UNIQUE_STRING_FOR_DEL_END')
    xml_string = xml_string.replace('<gap reason="lost"/>', 'UNIQUE_STRING_FOR_GAP_LOST')

    # Parse the modified XML string
    root = ET.fromstring(xml_string)

    namespaces = {'tei': 'http://www.tei-c.org/ns/1.0', 'xml': 'http://www.w3.org/XML/1998/namespace'}

    works_data = []
    work_contents_data = []
    work_content_subdivisions_data = []
    work_notes_data = []
    authors_data = []
    author_abbreviations_data = []
    work_abbreviations_data = []
    authors_and_works_data = []
    work_content_notes_data = []

    work_id = generate_uuid()
    title_element = root.find('.//tei:title[@xml:lang="lat"]', namespaces)
    work_name = title_element.text if title_element is not None else 'Unknown Title'
    works_data.append([work_id, work_name])
    print(f'Work: {work_id}, {work_name}')

    author_element = root.find('.//tei:author', namespaces)
    author_name = author_element.text if author_element is not None else 'Unknown Author'
    author_id = generate_uuid()
    authors_data.append([author_id, author_name, '', None])
    print(f'Author: {author_id}, {author_name}')

    # Adding standard abbreviation for the author
    author_abbreviation = 'Phdr.'
    author_abbreviations_data.append([author_id, 1, author_abbreviation])

    # Linking author to work
    authors_and_works_data.append([author_id, work_id])

    fragment_index = 1  # Global index counter for fragments
    note_index = 1  # Note index counter

    for work in root.findall('.//tei:div[@subtype="book"]', namespaces):
        book_node = generate_uuid()
        book_name = work.find('tei:head', namespaces).text if work.find('tei:head', namespaces) is not None else None
        book_seq = work.get('n')
        if not is_numeric(book_seq):
            book_seq = 'book'
        # Track the fromIndex for the book
        book_from_index = fragment_index

        type_counters = {}

        for poem in work.findall('.//tei:div[@subtype="poem"]', namespaces):
            poem_id = poem.get('n')
            poem_name = poem.find('tei:head', namespaces).text if poem.find('tei:head',
                                                                            namespaces) is not None else None

            poem_node = generate_uuid()
            typ = poem_id if not is_numeric(poem_id) else 'poem'

            if typ not in type_counters:
                type_counters[typ] = 1
            else:
                type_counters[typ] += 1

            seq = type_counters[typ]
            parent_node = book_node

            poem_lines = poem.findall('tei:l', namespaces)
            to_index = fragment_index + sum(
                len(split_text_into_segments(line.text)) for line in poem_lines if line.text) - 1

            work_content_subdivisions_data.append(
                [work_id, typ, seq, poem_name, poem_node, parent_node, fragment_index, to_index])
            print(
                f'Subdivision: {work_id, typ, seq, poem_name, poem_node, parent_node, fragment_index, to_index}')

            for line in poem_lines:
                verse_node = generate_uuid()
                verse_seq = line.get('n')  # Replace the unique strings with <del> and </del> tags
                line_text = line.text.replace('UNIQUE_STRING_FOR_DEL_START', '').replace('UNIQUE_STRING_FOR_DEL_END',
                                                                                         '').strip() if line.text else ''
                line_text = line_text.replace('UNIQUE_STRING_FOR_GAP_LOST', '').strip() if line.text else ''

                # Add to work_content_notes_data if <del> tag was found
                if 'UNIQUE_STRING_FOR_DEL_START' in line.text and 'UNIQUE_STRING_FOR_DEL_END' in line.text:
                    work_content_notes_data.append([work_id, note_index, fragment_index,
                                                    fragment_index + len(split_text_into_segments(line_text)) - 1,
                                                    'marked for deletion'])
                    note_index += 1

                # Add to work_content_notes_data if <gap> tag was found
                if 'UNIQUE_STRING_FOR_GAP_LOST' in line.text:
                    work_content_notes_data.append([work_id, note_index, fragment_index,
                                                    fragment_index + len(split_text_into_segments(line_text)),
                                                    'gap: lost'])
                    note_index += 1

                if line_text:
                    to_index = fragment_index + len(split_text_into_segments(line_text)) - 1
                else:
                    to_index = fragment_index

                work_content_subdivisions_data.append(
                    [work_id, 'verse', verse_seq, line_text, verse_node, poem_node, fragment_index, to_index])

                for segment in split_text_into_segments(line_text):
                    work_contents_data.append([work_id, fragment_index, segment, 'sourceReference'])
                    print(f'Segment: {fragment_index}, {segment}')
                    fragment_index += 1

        for note in work.findall('.//tei:note', namespaces):
            note_id = note.get('n')
            from_index = fragment_index
            note_text = ''.join(note.itertext())
            to_index = fragment_index + len(note_text.split()) - 1
            work_notes_data.append([work_id, note_index, from_index, to_index, note_text])
            print(f'Note: {note_id}, {from_index}, {to_index}, {note_text}')
            note_index += 1
            fragment_index = to_index + 1

        # Set the toIndex for the book after processing all its content
        book_to_index = fragment_index - 1
        work_content_subdivisions_data.append(
            [work_id, 'book', book_seq, book_name, book_node, None, book_from_index, book_to_index])

    works_df = pd.DataFrame(works_data, columns=['id', 'name'])
    work_contents_df = pd.DataFrame(work_contents_data, columns=['workId', 'idx', 'word', 'sourceReference'])
    work_content_subdivisions_df = pd.DataFrame(work_content_subdivisions_data,
                                                columns=['workId', 'typ', 'seq', 'name', 'node', 'parent', 'fromIndex',
                                                         'toIndex'])
    work_notes_df = pd.DataFrame(work_notes_data, columns=['workId', 'id', 'fromIndex', 'toIndex', 'val'])
    authors_df = pd.DataFrame(authors_data, columns=['id', 'name', 'about', 'image'])
    author_abbreviations_df = pd.DataFrame(author_abbreviations_data, columns=['authorId', 'id', 'val'])
    work_abbreviations_df = pd.DataFrame(work_abbreviations_data, columns=['workId', 'id', 'val'])
    authors_and_works_df = pd.DataFrame(authors_and_works_data, columns=['authorId', 'workId'])
    work_content_notes_df = pd.DataFrame(work_content_notes_data,
                                         columns=['workId', 'id', 'fromIndex', 'toIndex', 'val'])

    os.makedirs(output_dir, exist_ok=True)

    works_df.to_csv(os.path.join(output_dir, 'works.csv'), index=False)
    work_contents_df.to_csv(os.path.join(output_dir, 'work_contents.csv'), index=False)
    work_content_subdivisions_df.to_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'), index=False)
    work_notes_df.to_csv(os.path.join(output_dir, 'work_notes.csv'), index=False)
    authors_df.to_csv(os.path.join(output_dir, 'authors.csv'), index=False)
    author_abbreviations_df.to_csv(os.path.join(output_dir, 'author_abbreviations.csv'), index=False)
    work_abbreviations_df.to_csv(os.path.join(output_dir, 'work_abbreviations.csv'), index=False)
    authors_and_works_df.to_csv(os.path.join(output_dir, 'authors_and_works.csv'), index=False)
    work_content_notes_df.to_csv(os.path.join(output_dir, 'work_content_notes.csv'), index=False)


def validate_csv_files(output_dir):
    errors = []

    # Load the relevant CSV files
    work_contents_df = pd.read_csv(os.path.join(output_dir, 'work_contents.csv'))
    work_content_subdivisions_df = pd.read_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'))
    work_content_notes_df = pd.read_csv(os.path.join(output_dir, 'work_content_notes.csv'))

    check_unique_consecutive_idx_in_contents(errors, work_contents_df)

    check_unique_consecutive_id_in_notes(errors, work_content_notes_df)

    check_children_within_parent_range(errors, work_content_subdivisions_df)

    check_to_index_always_gt_from_index_in_sub(errors, work_content_subdivisions_df)

    check_to_index_always_gt_from_index_in_notes(errors, work_content_notes_df)

    if errors:
        print("Validation errors found:")
        for error in errors:
            print(error)
    else:
        print("All validations passed successfully.")


def check_to_index_always_gt_from_index_in_sub(errors, work_content_subdivisions_df):
    for _, row in work_content_subdivisions_df.iterrows():
        node = row['node']
        from_index = row['fromIndex']
        to_index = row['toIndex']
        if to_index < from_index:
            errors.append(f'Node {node} has toIndex {to_index} which is less than fromIndex {from_index}.')


def check_to_index_always_gt_from_index_in_notes(errors, work_content_notes_df):
    for _, row in work_content_notes_df.iterrows():
        from_index = row['fromIndex']
        to_index = row['toIndex']
        if to_index < from_index:
            errors.append(f'Note {row["id"]} has toIndex {to_index} which is less than fromIndex {from_index}.')


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
                errors.append(
                    f'Child node {child_row["node"]} indices [{child_from}, {child_to}] are out of range of parent node {parent_node} indices [{parent_from}, {parent_to}].')


def check_unique_consecutive_idx_in_contents(errors, work_contents_df):
    if not work_contents_df['idx'].is_unique:
        errors.append('idx values in work_contents.csv are not unique.')
    if not (work_contents_df['idx'].sort_values().reset_index(drop=True) == pd.Series(
            range(1, len(work_contents_df) + 1))).all():
        errors.append('idx values in work_contents.csv are not consecutive starting from 1.')


def check_unique_consecutive_id_in_notes(errors, work_content_notes_df):
    if not work_content_notes_df['id'].is_unique:
        errors.append('id values in work_content_notes.csv are not unique.')
    if not (work_content_notes_df['id'].sort_values().reset_index(drop=True) == pd.Series(
            range(1, len(work_content_notes_df) + 1))).all():
        errors.append('id values in work_content_notes.csv are not consecutive starting from 1.')


if __name__ == "__main__":
    xml_file = choose_file()
    output_dir = '../output'
    process_verse(xml_file, output_dir)
    validate_csv_files(output_dir)  # Call the validation function here
    print(f"Data has been successfully exported to CSV files in {output_dir}.")
