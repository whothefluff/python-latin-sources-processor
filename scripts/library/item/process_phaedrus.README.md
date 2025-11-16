# README for process_phaedrus.py

This script is responsible for the complete processing of the TEI XML source text for Phaedrus's Fables.

## Overview

The script performs the following key functions:
1.  **Parses** the TEI XML file for Phaedrus.
2.  **Segments** the text into individual words and punctuation (tokens).
3.  **Determines Proper Noun State**: For each word, it queries a local Morpheus API to determine if the word is a common noun, a proper noun, or could be either, based on both its dictionary form and its context in the text.
4.  **Performs Macronization**: It queries a local Macronization API to determine the correct vowel lengths for every word in the text.
5.  **Handles Ambiguity**: It intelligently separates macronization results into two categories:
    - **Unambiguous Macronizations**: Words with stable vowel lengths are stored in a global, reusable CSV.
    - **Work-Specific Macronizations**: Words whose macronization is uncertain, unknown, or context-dependent (e.g., depends on being a proper noun) are stored in a work-specific CSV.
6.  **Generates CSVs**: It outputs a comprehensive set of structured data files ready for aggregation and use in the final application.
7.  **Validates Output**: After generation, it runs a series of internal checks to ensure the result makes sense. It may require small manual adjustments

## Prerequisites

This script requires two local APIs to be running on your machine. Please refer to their respective repositories for setup and installation instructions.

1.  **Morpheus API (Morphological Analysis)**
    -   Provides dictionary lookup and morphological analysis.
    -   **Repository**: [whothefluff/morpheus-perseids-api](https://github.com/whothefluff/morpheus-perseids-api)

2.  **Latin Macronizer API**
    -   Provides macronization (vowel length) analysis.
    -   **Repository**: [whothefluff/latin-macronizer](https://github.com/whothefluff/latin-macronizer)

The script expects the Morpheus API to be available at `http://localhost:1501` and the Macronizer API at `http://localhost:8001`.

## Input

-   **Source XML**: `data/library/item/phaedrus/phi0975.phi001.perseus-lat2_modified.xml`

## Output

The script generates the following files in `output/library/item/phaedrus/`:
-   `works.csv`
-   `authors.csv`
-   `work_contents.csv`
-   `work_content_subdivisions.csv`
-   `work_content_supplementary.csv`
-   `author_abbreviations.csv`
-   `work_abbreviations.csv`
-   `authors_and_works.csv`
-   `work_macronizations.csv`
-   `unambiguous_macronizations.csv`

## How to Run

Ensure the prerequisite APIs are running, then execute the script from the project root:

```bash
python library/item/process_phaedrus.py