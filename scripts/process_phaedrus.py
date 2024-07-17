# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
import pandas as pd
import os
import uuid
# import tkinter as tk
# from tkinter import filedialog
import re
import base64


def choose_file():
    # root = tk.Tk()
    # root.withdraw()  # Hide the main window
    # file_path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml")])
    file_name = "phi0975.phi001.perseus-lat2_modified.xml"
    script_dir = os.path.dirname(__file__)
    script_parent_dir = os.path.dirname(script_dir)
    file_path = os.path.join(script_parent_dir, "data", "phaedrus", file_name)
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


def process_verse(xml_string, output_dir):
    # Replace <del> and </del> tags with a unique string
    xml_string = xml_string.replace('<del>', 'UNIQUE_STRING_FOR_DEL_START').replace('</del>',
                                                                                    'UNIQUE_STRING_FOR_DEL_END')
    xml_string = xml_string.replace('<gap reason="lost"/>', 'UNIQUE_STRING_FOR_GAP_LOST')

    # Parse the modified XML string
    root = ET.fromstring(xml_string)
    namespaces = {'tei': tei_namespace, 'xml': 'http://www.w3.org/XML/1998/namespace'}

    works_data = []
    work_contents_data = []
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
            to_index = fragment_index + len(book_head_segments) - 1

            # noinspection SpellCheckingInspection
            book_head_sub = [work_id, generate_uuid(), 'TITL', 0, book_head_text, book_node, fragment_index, to_index]
            work_content_subdivisions_data.append(book_head_sub)
            print(f'Book Head Subdivision: {book_head_sub}')

            for segment in book_head_segments:
                work_contents_data.append([work_id, fragment_index, segment, 'sourceReference'])
                print(f'Segment: {fragment_index}, {segment}')
                fragment_index += 1

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

                if line_text:
                    to_index = fragment_index + len(split_text_into_segments(line_text)) - 1
                else:
                    to_index = fragment_index

                work_content_subdivisions_data.append(
                    [work_id, poem_line_node, typ, poem_line_seq, line_text, poem_node,
                     fragment_index, to_index])

                for segment in split_text_into_segments(line_text):
                    work_contents_data.append([work_id, fragment_index, segment, 'sourceReference'])
                    print(f'Segment: {fragment_index}, {segment}')
                    fragment_index += 1

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
    work_contents_df = pd.DataFrame(work_contents_data, columns=['workId', 'idx', 'word', 'sourceReference'])
    work_content_subdivisions_df = pd.DataFrame(work_content_subdivisions_data,
                                                columns=['workId', 'node', 'typ', 'cnt', 'name', 'parent', 'fromIndex',
                                                         'toIndex'])
    authors_df = pd.DataFrame(authors_data, columns=['id', 'name', 'about', 'image'])
    author_abbreviations_df = pd.DataFrame(author_abbreviations_data, columns=['authorId', 'id', 'val'])
    work_abbreviations_df = pd.DataFrame(work_abbreviations_data, columns=['workId', 'id', 'val'])
    authors_and_works_df = pd.DataFrame(authors_and_works_data, columns=['authorId', 'workId'])
    work_content_supplementary_df = pd.DataFrame(work_content_supplementary_data,
                                                 columns=['workId', 'typ', 'cnt', 'fromIndex', 'toIndex', 'val'])

    os.makedirs(output_dir, exist_ok=True)

    works_df.to_csv(os.path.join(output_dir, 'works.csv'), index=False)
    work_contents_df.to_csv(os.path.join(output_dir, 'work_contents.csv'), index=False)
    work_content_subdivisions_df.to_csv(os.path.join(output_dir, 'work_content_subdivisions.csv'), index=False)
    authors_df.to_csv(os.path.join(output_dir, 'authors.csv'), index=False)
    author_abbreviations_df.to_csv(os.path.join(output_dir, 'author_abbreviations.csv'), index=False)
    work_abbreviations_df.to_csv(os.path.join(output_dir, 'work_abbreviations.csv'), index=False)
    authors_and_works_df.to_csv(os.path.join(output_dir, 'authors_and_works.csv'), index=False)
    work_content_supplementary_df.to_csv(os.path.join(output_dir, 'work_content_supplementary.csv'), index=False)


def get_work_data(work_id, work_name):
    script_dir = os.path.dirname(__file__)
    script_parent_dir = os.path.dirname(script_dir)
    about_file = os.path.join(script_parent_dir, "data", "phaedrus", 'about_phi0975_phi001.txt')
    with open(about_file, 'r', encoding='utf-8') as about:
        about_text = about.read()
    work_data = [work_id, work_name, about_text]
    return work_data


def get_author_data(author_id, author_name):
    script_dir = os.path.dirname(__file__)
    script_parent_dir = os.path.dirname(script_dir)
    about_file = os.path.join(script_parent_dir, "data", "phaedrus", 'about.txt')
    with open(about_file, 'r', encoding='utf-8') as about:
        about_text = about.read()
    image_file = os.path.join(script_parent_dir, "data", "phaedrus", 'expanded.webp')
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

    if errors:
        print("Validation errors found:")
        for error in errors:
            print(error)
    else:
        print("All validations passed successfully.")


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
    namespace = "{" + tei_namespace + "}"
    gap_tags = find_all_gap_tags(root, namespace)

    # Count the number of elements in gap_tags
    num_gap_tags = len(gap_tags)

    # Create a list to store the idx values
    gap_indices = []

    # Iterate over the contents list for as many times as there are elements in gap_tags
    for i in range(num_gap_tags):
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
    namespace = "{" + tei_namespace + "}"
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


if __name__ == "__main__":
    # noinspection HttpUrlsUsage
    tei_namespace = 'http://www.tei-c.org/ns/1.0'
    xml_file = choose_file()
    output_dir_outer = '../output/phaedrus/'
    with open(xml_file, 'r', encoding='utf-8') as file:
        xml_string_outer = file.read()  # Parse the XML file as a string
    process_verse(xml_string_outer, output_dir_outer)
    print(f"Data has been successfully exported to CSV files in {output_dir_outer}.")
    validate_csv_files(xml_string_outer, output_dir_outer)  # Call the validation function here
