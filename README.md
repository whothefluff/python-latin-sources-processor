# Python Latin Sources Processor

This project processes Latin source texts and dictionaries, converting XML files into structured CSV data and performing morphological analysis.

## Core Scripts

### Dictionary Processing
#### `dictionary/process_lexica.py`
- Processes dictionary XML files into CSV format
- Outputs multiple CSV files to `output/lexica/`
- **Overwrites** existing files in the output path

### Library Processing
#### `library/item/XXX.py`
- Processes related XML source texts
- Creates CSV files in `output/library/item/XXX/`
- **Overwrites** existing files in the output path

#### `library/process_library_aggregate.py`
- Combines CSV files from `output/library/` into single aggregated files
- Additive process - new data is appended to existing files (useful when adding new works)
- **Deleting** the aggregate files is necessary for reprocessing old entries without adding duplicates

### Morphological Analysis
#### `morphological_analysis/process_morph.py`
- Analyzes unique word formations from the aggregated library files
- Creates entries in CSV files under `output/morphological_analysis/`
- Never overwrites - only adds new word formations
- **Deleting** the output files is necessary if full reprocessing is needed

## Processing Flow
- Run `process_lexica.py` to establish dictionary data (independent)


- For library data and morphological analysis:
  - Run for relevant individual works (e.g., `process_phaedrus.py`)
  - Run `process_library_aggregate.py` to combine all processed works
  - Run `process_morph.py` for morphological analysis of the aggregated library data
