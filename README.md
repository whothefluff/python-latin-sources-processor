# Python Latin Sources Processor

This project processes Latin source texts and dictionaries, converting XML files into structured CSV data and performing
morphological analysis.

## Setup

Python 3.11 or later. `process_library_aggregate.py` and `compare_csv.py` use tkinter, which Debian and Ubuntu install
separately (`apt install python3-tk`).

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The scripts reach Morpheus (port 1500) and the macronizer (port 8001) on `localhost`, or on the host named in
`SERVICES_HOST`.

The dev container (`.devcontainer/`) installs the requirements and points `SERVICES_HOST` at your machine, where
Morpheus and the macronizer keep running. It has no display: pass the aggregate script its directory, and run
`compare_csv.py` outside it.

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
- **Overwrites** existing files in the output path, once the new ones pass its validation. When Morpheus or the
  macronizer fails, or validation finds errors, it raises and leaves them as they were
- Replaces all of the files or none. While it moves them, `.unfinished-publication.txt` says what it replaces and
  adds; when it fails and can't undo every step, that file stays, with what's left to undo, and every later run into
  that directory refuses to start until the files are restored and it's removed. An old file that a finished
  publication couldn't remove stays as `.<name>.old`, the only copy of that version, and also stops later runs until
  it's removed. The aggregate and the morphology script publish the same way

#### `library/process_library_aggregate.py`

- Combines CSV files from `output/library/` into single aggregated files
- Searches the directory given as an argument, or one picked in a dialog, and writes to the project's `output/library/`
  from any working directory: `python -m scripts.library.process_library_aggregate output/library/item`
- Additive process - new data is appended to existing files (useful when adding new works)
- **Deleting** the aggregate files is necessary for reprocessing old entries without adding duplicates
- Raises and saves nothing when a work's directory, or the aggregate when there is one, has a publication into it that
  didn't finish or a `.<name>.old` file that one left, is missing one of the ten files that a work's script writes, has
  one that can't be read or that has other columns than the reader's, or has no rows in `works.csv`,
  `work_contents.csv`, `work_content_subdivisions.csv`, `authors.csv` or `authors_and_works.csv`. A directory with any
  of the ten files is a work's. Otherwise it saves all of the files or none, with their columns in the order that the
  reader imports them by position
- Refuses to save when a work is found twice (already aggregated, or in two directories), since every run of a work's
  script gives it new ids
- Lists an author of several works once, taking authors with the same name as one, under the id of the first work in
  path order. Refuses to save when that author's about, image or abbreviations differ from one work to another, or when
  an author id has more than one name
- Gives a certain token its own macronization in `work_macronizations.csv`, with mask 0, when the reader would look it
  up under an unambiguous macronization that isn't its own: a word that works are certain of but macronize
  differently, or another token's, such as a numeral I's for a capitalized I

### Morphological Analysis

#### `morphological_analysis/process_XXX.py`

- Analyzes unique (case-insensitive) word formations from the aggregated library files
- Creates entries in CSV files under `output/morphological_analysis/`
- Never overwrites - only adds new word formations
- Drops the inflections spelled with v where the form has u, j where it has i, or the reverse, such as volvo's `volv-it`
  for `voluit`, and drops an analysis left without inflections
- **Deleting** the output files is necessary if full reprocessing is needed
- Refuses to run if `morphological_details.csv` has forms that `work_contents.csv` doesn't have anymore (`iam` after the text
  changed it to `jam`). It means the output files were made from an older text: delete them and run again
- Fails after the last word when a word got no analysis written: Morpheus couldn't be asked, its answer has no
  annotation or an analysis without a headword, or every analysis was dropped. A word that Morpheus doesn't know is
  written as unknown
- Adds to a copy of the output files, validates it and moves it to `output/morphological_analysis/` only when every
  word got an analysis and validation finds no issue. Otherwise it raises and leaves the output files as they were, so
  the next run analyzes all the new words again
- Doesn't start while a publication of the aggregate into `output/library/` didn't finish, or left a `.<name>.old`
  file

Theoretically you can create multiple scripts that use different services for morphological analysis,
but only one version will be used with the current db schema

The script `morphological_analysis/process_morpheus_perseids_api.py` is an example of using the Perseids API for
morphological analysis,
which doesn't analyze proper nouns and is case-insensitive. The reader handles case-sensitive queries so having
duplicates provides no benefit.

## Processing Flow

*(Note: All CSV outputs generated by this flow must strictly adhere to the data invariants defined
in `PIPELINE_CONTRACT.md`).*

- Run `process_lexica.py` to establish dictionary data (independent)


- For library data and morphological analysis:
    - Run for relevant individual works (e.g., `process_phaedrus.py`)
    - Run `process_library_aggregate.py` to combine all processed works
    - Run `process_morpheus_perseids_api.py` (if you have the endpoint running locally) for morphological analysis of
      the aggregated library data

### Checking regenerated data

`tools/compare_reader_databases.py` compares two databases built by the reader's importer (the `data.db` its CI
uploads as `latin-reader-database-<run number>`): the reader's `main` before the new CSVs, and a branch with them.
It reports, per work and token, what the reader would show differently: text and reading order, macrons and masks,
proper-noun states, enclitics, expansions, sentences and word indices, candidate lemmas, and subdivisions. Works are
paired by their authors and name, or with `--same-work`, one to one. Adding a work must leave the others without
differences:

```bash
python -m scripts.tools.compare_reader_databases old.db new.db --allow-added-works
```

It exits with 0 when nothing differs, 1 when something does, and 2 when the databases can't be compared.

### Morpheus flow

In general, we seek improvements to original API, without introducing new mistakes.  
New mistakes should be purposefully avoided in the python script

1) Run [original](https://github.com/whothefluff/morpheus-perseids-api/releases/tag/v1.0-archived)
2) Run [fork](https://github.com/whothefluff/morpheus-perseids-api)
3) Compare differences (almost always new is better, but not always: e.g. 'ascribo' not found)
   > many of these new errors are found in these two commits  
   https://github.com/Alatius/morpheus/commit/e5f83b5627f2588ef3cb2f55c9b9f751334afba0  
   https://github.com/Alatius/morpheus/commit/b3cead6d43ddfef5e75d962e52298cbd6d2bcd9a
4) Fix source in [this fork](https://github.com/whothefluff/morpheus-alatius-xml) if possible (better re-runs AND less
   manual fixes) and create a new version of the [API fork](https://github.com/whothefluff/morpheus-perseids-api)  
   (for use in step 2)
5) "Manually" fix rest by updating the script overrides
6) Check for "new combination, check" in the inflections .csv. If there are any, update the script
7) Can now update reader sources

## Third-Party Resources

This project makes use of the following repositories from the Perseus Digital Library and Perseids Project:

### Perseus Treebank Data

[PerseusDL/treebank_data](https://github.com/PerseusDL/treebank_data) - Contains published Perseus Treebank Data (v2.0)
with syntactic annotations for Ancient Greek and Latin texts. Licensed under Creative Commons Attribution-ShareAlike
3.0.

### Perseus Digital Library Lexica

[PerseusDL/lexica](https://github.com/PerseusDL/lexica) - Contains lexical resources and dictionaries for ancient
languages. Licensed under Creative Commons Attribution-ShareAlike 4.0 International.

### Morpheus Perseids API

[perseids-tools/morpheus-perseids-api](https://github.com/perseids-tools/morpheus-perseids-api) - API interface for the
Morpheus morphological parsing tool for Ancient Greek and Latin text analysis. Licensed under MIT License.

## License and Attribution

This repository contains modified versions of resources from:

- Perseus Treebank Data
- Perseus Digital Library Lexica
- Morpheus Perseids API

Modified Perseus resources remain under their original Creative Commons licenses.   
Modified Morpheus API components remain under MIT license.
Original contributions are released under the Unlicense.