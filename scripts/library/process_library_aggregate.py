import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple, cast

import pandas as pd
from tqdm import tqdm

from scripts.library.util.unambiguous_macronizations import (
    CertainToken, agreed_macronizations, lookup_key, work_macronizations_where_lookup_differs,
)

TYPE_BY_FILE_AND_COLUMN = {
    'work_contents.csv': {
        'properNounState': 'Int64',
        'wordIdx': 'Int64'
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
    (those containing work_contents.csv)
    """
    valid_work_dirs = []
    base_path = Path(base_dir)

    # Only look through actual subdirectories, no symlinks or junctions
    for current_path in base_path.rglob('work_contents.csv'):
        if current_path.is_file():
            work_dir = current_path.parent
            valid_work_dirs.append(work_dir)
            logging.info(f"Found valid work directory: {work_dir}")

    return valid_work_dirs


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
                         columns=['word', 'macronizedWord']),
            pd.concat([work_macronizations, pd.DataFrame(added, columns=work_macronizations.columns)],
                      ignore_index=True))


def validate_aggregation(existing_df, original_dfs, aggregated_df, file_name):
    """
    Validates the aggregation process for a specific file type.
    Checks that the number of newly added rows matches the sum of rows from found folders.
    Returns (is_valid, message)
    """
    # Get the number of rows we're trying to add from the found folders for this file
    rows_to_add = sum(len(df) for df in original_dfs)

    # Calculate expected total rows
    expected_total = len(existing_df) + rows_to_add

    # Check if these rows were actually added to the aggregated file
    if len(aggregated_df) != expected_total:
        return False, f"Row mismatch in {file_name}: Expected {expected_total} rows, got {len(aggregated_df)}"

    # Column consistency check
    base_columns = set(original_dfs[0].columns)
    for df in original_dfs:
        if set(df.columns) != base_columns:
            return False, f"Column mismatch in {file_name}: Inconsistent columns across source files"

    return True, ""


def aggregate(base_dir: Path, output_dir: Path = OUTPUT_DIR):
    """Adds every work found under base_dir to the aggregate files in output_dir"""
    output_dir.mkdir(parents=True, exist_ok=True)  # Ensure output directory exists

    valid_work_dirs = find_valid_work_dirs(base_dir)
    if not valid_work_dirs:
        logging.warning("No valid work directories found (containing work_contents.csv). Exiting...")
        return

    # Dictionary to store original DataFrames for validation
    original_dfs = {}
    # Dictionary to store aggregated DataFrames
    aggregated_dfs: Dict[str, pd.DataFrame] = {}
    # Dictionary to store existing DataFrames
    existing_dfs = {}

    # Collect all unique CSV filenames across all work directories
    template_files = set()
    for work_dir in valid_work_dirs:
        template_files.update(f.name for f in work_dir.glob("*.csv"))
    template_files = list(template_files)

    logging.info(f"CSV files to process: {template_files}")

    # Initialize aggregated_dfs and existing_dfs with existing files
    for file_name in template_files:
        output_path = output_dir / file_name
        if output_path.exists():
            try:
                existing_df = pd.read_csv(output_path, dtype=TYPE_BY_FILE_AND_COLUMN.get(file_name))
                existing_dfs[file_name] = existing_df.copy()
                aggregated_dfs[file_name] = existing_df.copy()
                logging.info(f"Loaded existing aggregated file: {output_path} with {len(existing_df)} rows.")
            except Exception as e:
                logging.error(f"Error reading existing {output_path}: {str(e)}")
                continue
        else:
            aggregated_dfs[file_name] = pd.DataFrame()
            logging.info(f"Initialized new aggregated file: {output_path}")

    # Library files by source, to find works aggregated twice
    dfs_by_source = [existing_dfs]

    # Process each valid work directory
    for work_dir in tqdm(valid_work_dirs, desc="Processing directories"):
        logging.info(f"Processing directory: {work_dir}")
        dfs_by_source.append({})

        for file_name in template_files:
            file_path = work_dir / file_name

            if file_path.exists():
                try:
                    # Read the current CSV file
                    df = pd.read_csv(file_path, dtype=TYPE_BY_FILE_AND_COLUMN.get(file_name))
                    dfs_by_source[-1][file_name] = df

                    # Store original DataFrame for validation
                    if file_name not in original_dfs:
                        original_dfs[file_name] = []
                    original_dfs[file_name].append(df)

                    # Add to aggregated DataFrame
                    if aggregated_dfs[file_name].empty and file_name not in existing_dfs:
                        aggregated_dfs[file_name] = df.copy()
                    else:
                        aggregated_dfs[file_name] = pd.concat(
                            [aggregated_dfs[file_name], df],
                            ignore_index=True
                        )
                    logging.info(f"Appended {len(df)} rows from {file_path}")

                except Exception as e:
                    logging.error(f"Error processing {file_path}: {str(e)}")

        logging.info(f"Finished processing directory: {work_dir}")

    # check necessary because every run of a work script creates new ids
    repeated_works = find_repeated_works(dfs_by_source)
    if repeated_works:
        logging.error(f"Works found more than once: {repeated_works}. Nothing was saved. To process a work again, "
                      f"delete the aggregate files in {output_dir} and aggregate every work")
        return

    authors_that_differ = find_authors_that_differ(dfs_by_source)
    if authors_that_differ:
        logging.error(f"Authors whose rows differ from one work to another: {authors_that_differ}. Nothing was saved. "
                      f"Give each of them the same about, image and abbreviations in every work")
        return
    authors, authors_and_works, author_abbreviations = merge_authors(aggregated_dfs['authors.csv'],
                                                                     aggregated_dfs['authors_and_works.csv'],
                                                                     aggregated_dfs['author_abbreviations.csv'])
    unambiguous_macronizations, work_macronizations = merge_macronizations(
        dfs_by_source, aggregated_dfs['work_macronizations.csv'])
    merged_dfs = {'authors.csv': authors, 'authors_and_works.csv': authors_and_works,
                  'author_abbreviations.csv': author_abbreviations,
                  'unambiguous_macronizations.csv': unambiguous_macronizations,
                  'work_macronizations.csv': work_macronizations}

    # Save all aggregated files with validation
    for file_name, df in aggregated_dfs.items():
        output_path = output_dir / file_name
        existing_df = existing_dfs.get(file_name, pd.DataFrame())
        is_valid, message = validate_aggregation(
            existing_df,
            original_dfs.get(file_name, []),
            df,
            file_name
        )
        if is_valid:
            try:
                merged_dfs.get(file_name, df).to_csv(output_path, index=False, lineterminator="\n")
                logging.info(f"Successfully saved aggregated file: {output_path}")
            except Exception as e:
                logging.error(f"Error saving {output_path}: {str(e)}")
        else:
            logging.error(f"Validation failed for {file_name}: {message}")


if __name__ == "__main__":
    selected_dir = select_directory()
    if selected_dir:
        aggregate(selected_dir)
    else:
        logging.warning("No directory selected. Exiting...")
