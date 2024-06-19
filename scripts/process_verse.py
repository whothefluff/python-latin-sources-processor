import xml.etree.ElementTree as ET
import pandas as pd
import os
import tkinter as tk
from tkinter import filedialog


def choose_file():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    file_path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml")])
    return file_path


def process_verse(xml_file, output_dir):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    works_data = []
    work_contents_data = []
    work_content_subdivisions_data = []
    work_notes_data = []

    for work in root.findall('.//div[@subtype="book"]'):
        work_id = work.get('n')
        work_name = work.find('head').text if work.find('head') is not None else None
        works_data.append([work_id, work_name])

        for poem in work.findall('.//div[@subtype="poem"]'):
            poem_id = poem.get('n')  # unique ID for the poem
            poem_name = poem.find('head').text if poem.find('head') is not None else None

            for line in poem.findall('l'):
                line_number = line.get('n')
                line_text = line.text
                work_contents_data.append([work_id, line_number, line_text, 'sourceReference'])

            typ = 'poem'  # Example type, adjust as needed
            seq = poem.get('n')
            name = poem.find('head').text if poem.find('head') is not None else None
            node = poem.get('n')
            parent = None  # Set parent as needed
            from_index = 1  # Example index, adjust as needed
            to_index = len(poem.findall('l'))

            work_content_subdivisions_data.append([work_id, typ, seq, name, node, parent, from_index, to_index])

        for note in work.findall('.//note'):
            note_id = note.get('n')
            from_index = 1
            to_index = len(note.findall('.//p'))
            note_text = ''.join(note.itertext())
            work_notes_data.append([work_id, note_id, from_index, to_index, note_text])

    works_df = pd.DataFrame(works_data, columns=['id', 'name'])
    work_contents_df = pd.DataFrame(work_contents_data, columns=['workId', 'idx', 'word', 'sourceReference'])
    work_content_subdivisions_df = pd.DataFrame(work_content_subdivisions_data,
                                                columns=['workId', 'typ', 'seq', 'name', 'node', 'parent', 'fromIndex',
                                                         'toIndex'])
    work_notes_df = pd.DataFrame(work_notes_data, columns=['workId', 'id', 'fromIndex', 'toIndex', 'val'])

    os.makedirs(output_dir, exist_ok=True)

    works_df.to_csv(os.path.join(output_dir, 'works.csv'), index=False)
    work_contents_df.to_csv(os.path.join(output_dir, 'work_contents.csv'), index=False)
    work_content_subdivisions_df.to_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'), index=False)
    work_notes_df.to_csv(os.path.join(output_dir, 'work_notes.csv'), index=False)


if __name__ == "__main__":
    xml_file = choose_file()
    output_dir = '../output'
    process_verse(xml_file, output_dir)
    print(f"Data has been successfully exported to CSV files in {output_dir}.")
