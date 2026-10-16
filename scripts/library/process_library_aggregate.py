import argparse
import logging
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Hashable, List, Mapping, Set, Tuple, cast

import pandas as pd
from tqdm import tqdm

from scripts.common.publishing import publish, raise_for_publication_leftovers
from scripts.library.util.unambiguous_macronizations import (
    CertainToken, agreed_macronizations, lookup_key, work_macronizations_where_lookup_differs,
)

#: The files that every work's script writes, and their columns in the order that the reader imports them by position
COLUMNS_BY_LIBRARY_FILE: Dict[str, List[str]] = {
    'works.csv': ['id', 'name', 'about', 'uvLowercase', 'uvCapitals', 'ijLowercase', 'ijCapitals'],
    'work_contents.csv': ['workId', 'idx', 'word', 'sourceReference', 'properNounState', 'tokenType', 'sentenceIdx',
                          'wordIdx', 'enclitic', 'expansion'],
    'work_content_subdivisions.csv': ['workId', 'node', 'typ', 'cnt', 'name', 'parent', 'fromIndex', 'toIndex',
                                      'editionLabel'],
    'work_content_supplementary.csv': ['workId', 'typ', 'cnt', 'fromIndex', 'toIndex', 'val'],
    'work_abbreviations.csv': ['workId', 'id', 'val'],
    'authors.csv': ['id', 'name', 'about', 'image'],
    'author_abbreviations.csv': ['authorId', 'id', 'val'],
    'authors_and_works.csv': ['authorId', 'workId'],
    'work_macronizations.csv': ['workId', 'idx', 'macronizedWord', 'uncertaintyBitMask'],
    'unambiguous_macronizations.csv': ['word', 'macronizedWord'],
}
#: The library files that have rows for every work. Any of the others can have only a header
FILES_WITH_ROWS_FOR_EVERY_WORK = ('works.csv', 'work_contents.csv', 'work_content_subdivisions.csv', 'authors.csv',
                                  'authors_and_works.csv')

TYPE_BY_FILE_AND_COLUMN: Dict[str, Mapping[Hashable, str]] = {
    'work_contents.csv': {
        'properNounState': 'Int64',
        'wordIdx': 'Int64'
    },
    'work_content_subdivisions.csv': {
        'editionLabel': 'str'
    },
}

#: Where the aggregate files go, whatever directory the script runs from
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "library"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def select_directory():
    """
    Opens a dialog for the user to select a directory.
    Returns a Path object of the selected directory.
    """
    # Imported here so that the rest of the module works without a display (tests, CI)
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # Hide the main window

    logging.info("Please select the directory you want to process.")
    logging.info("The script will search through all subdirectories.")

    # Open directory selection dialog
    initial_dir = OUTPUT_DIR
    directory = filedialog.askdirectory(
        title="Select directory to process",
        mustexist=True,
        initialdir=initial_dir
    )

    return Path(directory) if directory else None


def find_valid_work_dirs(base_dir):
    """
    Recursively searches through directories to find valid work directories
    (those containing any of the library files, so that a work without work_contents.csv is found too), in path order,
    which decides whose author id a merged author keeps
    """
    valid_work_dirs = []
    base_path = Path(base_dir)

    # Only look through actual subdirectories, no symlinks or junctions
    for current_path in base_path.rglob('*.csv'):
        is_library_file = current_path.is_file() and current_path.name in COLUMNS_BY_LIBRARY_FILE
        if is_library_file and current_path.parent not in valid_work_dirs:
            work_dir = current_path.parent
            valid_work_dirs.append(work_dir)
            logging.info(f"Found valid work directory: {work_dir}")

    return sorted(valid_work_dirs)


def works_of(works_df, authors_df, authors_and_works_df):
    """Return each work as (its author names, its name).
    ID not used because it changes on every run."""
    author_names = dict(zip(authors_df['id'], authors_df['name']))
    authors_by_work = {}
    for author_id, work_id in zip(authors_and_works_df['authorId'], authors_and_works_df['workId']):
        authors_by_work.setdefault(work_id, []).append(author_names.get(author_id, ''))
    return [(', '.join(sorted(authors_by_work.get(work_id, []))), name)
            for work_id, name in zip(works_df['id'], works_df['name'])]


def find_repeated_works(dfs_by_source):
    """Return the works found more than once across the library files"""
    file_names = ('works.csv', 'authors.csv', 'authors_and_works.csv')
    works = [work
             for dfs in dfs_by_source if all(f in dfs for f in file_names)
             for work in works_of(*(dfs[f] for f in file_names))]
    return sorted({work for work in works if works.count(work) > 1})


def merge_authors(authors: pd.DataFrame, authors_and_works: pd.DataFrame,
                  author_abbreviations: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns the three files with every author of one name under the id of its first row, and identical rows once"""
    merged_ids = dict(zip(authors['id'], authors.groupby('name', sort=False)['id'].transform('first')))
    return (authors.assign(id=authors['id'].map(merged_ids)).drop_duplicates(),
            authors_and_works.assign(authorId=authors_and_works['authorId'].map(merged_ids)).drop_duplicates(),
            author_abbreviations.assign(authorId=author_abbreviations['authorId'].map(merged_ids)).drop_duplicates())


def _authors_with_their_abbreviations(authors: pd.DataFrame, author_abbreviations: pd.DataFrame) -> pd.DataFrame:
    abbreviations_by_author_id = {cast(str, author_id): frozenset(zip(abbreviations['id'], abbreviations['val']))
                                  for author_id, abbreviations in author_abbreviations.groupby('authorId')}
    abbreviations = pd.Series([abbreviations_by_author_id.get(author_id, frozenset()) for author_id in authors['id']],
                              index=authors.index)
    return authors.assign(abbreviations=abbreviations)


def find_authors_that_differ(dfs_by_source: List[Dict[str, pd.DataFrame]]) -> List[str]:
    """Returns the names of the authors that the sources give a different about, image or abbreviations"""
    file_names = ('authors.csv', 'author_abbreviations.csv')
    authors = pd.concat([_authors_with_their_abbreviations(dfs['authors.csv'], dfs['author_abbreviations.csv'])
                         for dfs in dfs_by_source if all(f in dfs for f in file_names)])
    names = authors.drop(columns='id').drop_duplicates()['name']
    return sorted(set(names[names.duplicated()]))


def find_author_ids_with_several_names(dfs_by_source: List[Dict[str, pd.DataFrame]]) -> List[str]:
    """Returns the author ids that the sources give more than one name"""
    authors = pd.concat([dfs['authors.csv'] for dfs in dfs_by_source if 'authors.csv' in dfs])
    name_counts = authors.groupby('id')['name'].nunique()
    return sorted(cast(str, author_id) for author_id, count in name_counts.items() if count > 1)


def _in_case_of(word: str, macronized: str) -> str:
    return ''.join(letter.upper() if original.isupper() else letter.lower()
                   for original, letter in zip(word, macronized, strict=True))


def _certain_tokens_of(dfs: Dict[str, pd.DataFrame], unambiguous_macronizations: Dict[str, str]) -> List[CertainToken]:
    """Returns the tokens of one source that have no work macronization and that its unambiguous macronizations
    cover"""
    work_macronizations = dfs['work_macronizations.csv']
    with_work_macronization = set(zip(work_macronizations['workId'], work_macronizations['idx']))
    contents = dfs['work_contents.csv']
    certain_tokens = []
    for work_id, idx, word, token_type, state in zip(contents['workId'], contents['idx'], contents['word'],
                                                     contents['tokenType'], contents['properNounState']):
        proper_noun_state = None if pd.isna(state) else int(state)
        key = lookup_key(word, token_type, proper_noun_state, unambiguous_macronizations)
        if key is not None and (work_id, idx) not in with_work_macronization:
            certain_tokens.append(CertainToken(work_id, idx, word, token_type, proper_noun_state,
                                               _in_case_of(word, unambiguous_macronizations[key])))
    return certain_tokens


def merge_macronizations(dfs_by_source: List[Dict[str, pd.DataFrame]],
                         work_macronizations: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Returns the unambiguous macronizations that the sources agree on, and the work macronizations with one more for
    each certain token whose key they disagree on"""
    file_names = ('work_contents.csv', 'work_macronizations.csv', 'unambiguous_macronizations.csv')
    sources = [dfs for dfs in dfs_by_source if all(f in dfs for f in file_names)]
    unambiguous_by_source = [dict(zip(dfs['unambiguous_macronizations.csv']['word'],
                                      dfs['unambiguous_macronizations.csv']['macronizedWord'])) for dfs in sources]
    certain_macronizations_by_key: Dict[str, Set[str]] = defaultdict(set)
    for unambiguous_macronizations in unambiguous_by_source:
        for key, macronized in unambiguous_macronizations.items():
            certain_macronizations_by_key[key].add(macronized)
    certain_tokens = [token for dfs, unambiguous_macronizations in zip(sources, unambiguous_by_source)
                      for token in _certain_tokens_of(dfs, unambiguous_macronizations)]
    added = work_macronizations_where_lookup_differs(certain_macronizations_by_key, certain_tokens)
    return (pd.DataFrame(list(agreed_macronizations(certain_macronizations_by_key).items()),
                         columns=COLUMNS_BY_LIBRARY_FILE['unambiguous_macronizations.csv']),
            pd.concat([work_macronizations,
                       pd.DataFrame(added, columns=COLUMNS_BY_LIBRARY_FILE['work_macronizations.csv'])],
                      ignore_index=True))


def read_library_files(output_dir: Path, work_dirs: List[Path]) -> List[Dict[str, pd.DataFrame]]:
    """Returns the library files of the aggregate in output_dir, when it has any, and of each work directory, by file
    name. Raises when a publication into a directory didn't finish or left a file it replaced, when a file is missing
    or can't be read, when a file that has rows for every work has none, or when a file's columns aren't the ones that
    COLUMNS_BY_LIBRARY_FILE gives it, in any order."""
    has_aggregate = any((output_dir / name).exists() for name in COLUMNS_BY_LIBRARY_FILE)
    directories = ([output_dir] if has_aggregate else []) + work_dirs
    for directory in directories:
        raise_for_publication_leftovers(directory)
    problems: List[str] = []
    dfs_by_source: List[Dict[str, pd.DataFrame]] = []
    for directory in tqdm(directories, desc="Reading directories"):
        dfs: Dict[str, pd.DataFrame] = {}
        for file_name, columns in COLUMNS_BY_LIBRARY_FILE.items():
            path = directory / file_name
            if not path.exists():
                problems.append(f"{path} is missing")
                continue
            try:
                df = pd.read_csv(path, dtype=TYPE_BY_FILE_AND_COLUMN.get(file_name))
            except Exception as e:
                problems.append(f"{path} can't be read: {e}")
                continue
            if df.empty and file_name in FILES_WITH_ROWS_FOR_EVERY_WORK:
                problems.append(f"{path} has no rows")
            if set(df.columns) != set(columns):
                problems.append(f"{path} has the columns {list(df.columns)} instead of {columns}")
            dfs[file_name] = df
        dfs_by_source.append(dfs)
        logging.info(f"Read {directory}")
    if problems:
        raise ValueError("Nothing was saved, because of these files:\n" + "\n".join(f"    {p}" for p in problems))
    return dfs_by_source


def aggregate(base_dir: Path, output_dir: Path = OUTPUT_DIR):
    """Adds every work found under base_dir to the aggregate files in output_dir, with each file's columns in the order
    that the reader imports them. Raises, and saves nothing, when the files can't be aggregated."""
    output_dir.mkdir(parents=True, exist_ok=True)  # Ensure output directory exists

    valid_work_dirs = find_valid_work_dirs(base_dir)
    if not valid_work_dirs:
        logging.warning("No valid work directories found (containing any of the library files). Exiting...")
        return

    # Library files by source, to find works aggregated twice
    dfs_by_source = read_library_files(output_dir, valid_work_dirs)

    # check necessary because every run of a work script creates new ids
    repeated_works = find_repeated_works(dfs_by_source)
    if repeated_works:
        raise ValueError(f"Works found more than once: {repeated_works}. Nothing was saved. To process a work again, "
                         f"delete the aggregate files in {output_dir} and aggregate every work")

    authors_that_differ = find_authors_that_differ(dfs_by_source)
    if authors_that_differ:
        raise ValueError(f"Authors whose rows differ from one work to another: {authors_that_differ}. Nothing was "
                         f"saved. Give each of them the same about, image and abbreviations in every work")

    author_ids_with_several_names = find_author_ids_with_several_names(dfs_by_source)
    if author_ids_with_several_names:
        raise ValueError(f"Author ids with more than one name: {author_ids_with_several_names}. Nothing was saved. "
                         f"Give each of those authors one name in every work, or each name its own id")
    aggregated_dfs = {file_name: pd.concat([dfs[file_name] for dfs in dfs_by_source], ignore_index=True)
                      for file_name in COLUMNS_BY_LIBRARY_FILE}
    authors, authors_and_works, author_abbreviations = merge_authors(aggregated_dfs['authors.csv'],
                                                                     aggregated_dfs['authors_and_works.csv'],
                                                                     aggregated_dfs['author_abbreviations.csv'])
    unambiguous_macronizations, work_macronizations = merge_macronizations(
        dfs_by_source, aggregated_dfs['work_macronizations.csv'])
    merged_dfs = {'authors.csv': authors, 'authors_and_works.csv': authors_and_works,
                  'author_abbreviations.csv': author_abbreviations,
                  'unambiguous_macronizations.csv': unambiguous_macronizations,
                  'work_macronizations.csv': work_macronizations}

    with tempfile.TemporaryDirectory() as working_dir:
        for file_name, df in aggregated_dfs.items():
            merged_dfs.get(file_name, df)[COLUMNS_BY_LIBRARY_FILE[file_name]].to_csv(Path(working_dir) / file_name,
                                                                                    index=False, lineterminator="\n")
        publish(Path(working_dir), output_dir)
    logging.info(f"Saved the aggregate files in {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combines the works' CSV files into the project's output/library/.")
    parser.add_argument("directory", nargs="?", type=Path, help="where to look for works; a dialog asks if left out")
    selected_dir = parser.parse_args().directory or select_directory()
    if selected_dir:
        aggregate(selected_dir)
    else:
        logging.warning("No directory selected. Exiting...")
