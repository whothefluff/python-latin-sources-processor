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
        return []
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
    xml_string = xml_string.replace('<del>', 'UNIQUE_STRING_FOR_DEL_START').replace('</del>', 'UNIQUE_STRING_FOR_DEL_END')

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

    for work in root.findall('.//tei:div[@subtype="book"]', namespaces):
        book_node = generate_uuid()
        book_name = work.find('tei:head', namespaces).text if work.find('tei:head', namespaces) is not None else None
        book_seq = work.get('n')
        if not is_numeric(book_seq):
            book_seq = 'book'
        work_content_subdivisions_data.append(
            [work_id, 'book', book_seq, book_name, book_node, None, fragment_index, fragment_index])

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

                # Add to work_content_notes_data if <del> tag was found
                if 'UNIQUE_STRING_FOR_DEL_START' in line.text and 'UNIQUE_STRING_FOR_DEL_END' in line.text:
                    work_content_notes_data.append([work_id, verse_seq, fragment_index,
                                                    fragment_index + len(split_text_into_segments(line_text)) - 1,
                                                    'marked for deletion'])

                work_content_subdivisions_data.append(
                    [work_id, 'verse', verse_seq, line_text, verse_node, poem_node, fragment_index,
                     fragment_index + len(split_text_into_segments(line_text)) - 1])

                for segment in split_text_into_segments(line_text):
                    work_contents_data.append([work_id, fragment_index, segment, 'sourceReference'])
                    print(f'Segment: {fragment_index}, {segment}')
                    fragment_index += 1

        for note in work.findall('.//tei:note', namespaces):
            note_id = note.get('n')
            from_index = fragment_index
            note_text = ''.join(note.itertext())
            to_index = fragment_index + len(note_text.split()) - 1
            work_notes_data.append([work_id, note_id, from_index, to_index, note_text])
            print(f'Note: {note_id}, {from_index}, {to_index}, {note_text}')
            fragment_index = to_index + 1

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


if __name__ == "__main__":
    xml_file = choose_file()
    output_dir = '../output'
    process_verse(xml_file, output_dir)
    print(f"Data has been successfully exported to CSV files in {output_dir}.")
