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
#### `morphological_analysis/process_XXX.py`
- Analyzes unique (case-insensitive) word formations from the aggregated library files
- Creates entries in CSV files under `output/morphological_analysis/`
- Never overwrites - only adds new word formations
- **Deleting** the output files is necessary if full reprocessing is needed

Theoretically you can create multiple scripts that use different services for morphological analysis, 
but only one version will be used with the current db schema

The script `morphological_analysis/process_morpheus_perseids_api.py` is an example of using the Perseids API for morphological analysis,
which doesn't analyze proper nouns and is case-insensitive. The reader handles case-sensitive queries so having duplicates provides no benefit.

## Processing Flow
- Run `process_lexica.py` to establish dictionary data (independent)


- For library data and morphological analysis:
  - Run for relevant individual works (e.g., `process_phaedrus.py`)
  - Run `process_library_aggregate.py` to combine all processed works
  - Run `process_morpheus_perseids_api.py` (if you have the endpoint running locally) for morphological analysis of the aggregated library data

## Third-Party Resources

This project makes use of the following repositories from the Perseus Digital Library and Perseids Project:

### Perseus Treebank Data
[PerseusDL/treebank_data](https://github.com/PerseusDL/treebank_data) - Contains published Perseus Treebank Data (v2.0) with syntactic annotations for Ancient Greek and Latin texts. Licensed under Creative Commons Attribution-ShareAlike 3.0.

### Perseus Digital Library Lexica
[PerseusDL/lexica](https://github.com/PerseusDL/lexica) - Contains lexical resources and dictionaries for ancient languages. Licensed under Creative Commons Attribution-ShareAlike 4.0 International.

### Morpheus Perseids API
[perseids-tools/morpheus-perseids-api](https://github.com/perseids-tools/morpheus-perseids-api) - API interface for the Morpheus morphological parsing tool for Ancient Greek and Latin text analysis. Licensed under MIT License.

## License and Attribution

This repository contains modified versions of resources from:
- Perseus Treebank Data
- Perseus Digital Library Lexica
- Morpheus Perseids API

Modified Perseus resources remain under their original Creative Commons licenses. 
Modified Morpheus API components remain under MIT license.
Original contributions are released under the Unlicense.
