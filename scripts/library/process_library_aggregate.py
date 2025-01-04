import os
import pandas as pd
from pathlib import Path
from tqdm import tqdm
import tkinter as tk
from tkinter import filedialog
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def select_directory():
    """
    Opens a dialog for the user to select a directory.
    Returns a Path object of the selected directory.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window

    logging.info("Please select the directory you want to process.")
    logging.info("The script will search through all subdirectories.")

    # Open directory selection dialog
    initial_dir = os.path.join(os.getcwd(), "output", "library")
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


def aggregate_csv_files():
    output_dir = Path("../../output/library")
    output_dir.mkdir(parents=True, exist_ok=True)  # Ensure output directory exists

    base_dir = select_directory()
    if not base_dir:
        logging.warning("No directory selected. Exiting...")
        return

    valid_work_dirs = find_valid_work_dirs(base_dir)
    if not valid_work_dirs:
        logging.warning("No valid work directories found (containing work_contents.csv). Exiting...")
        return

    # Dictionary to store original DataFrames for validation
    original_dfs = {}
    # Dictionary to store aggregated DataFrames
    aggregated_dfs = {}
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
                existing_df = pd.read_csv(output_path)
                existing_dfs[file_name] = existing_df.copy()
                aggregated_dfs[file_name] = existing_df.copy()
                logging.info(f"Loaded existing aggregated file: {output_path} with {len(existing_df)} rows.")
            except Exception as e:
                logging.error(f"Error reading existing {output_path}: {str(e)}")
                continue
        else:
            aggregated_dfs[file_name] = pd.DataFrame()
            logging.info(f"Initialized new aggregated file: {output_path}")

    # Process each valid work directory
    for work_dir in tqdm(valid_work_dirs, desc="Processing directories"):
        logging.info(f"Processing directory: {work_dir}")

        for file_name in template_files:
            file_path = work_dir / file_name

            if file_path.exists():
                try:
                    # Read the current CSV file
                    df = pd.read_csv(file_path)

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
                df.to_csv(output_path, index=False)
                logging.info(f"Successfully saved aggregated file: {output_path}")
            except Exception as e:
                logging.error(f"Error saving {output_path}: {str(e)}")
        else:
            logging.error(f"Validation failed for {file_name}: {message}")


if __name__ == "__main__":
    aggregate_csv_files()
