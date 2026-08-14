# README for process_phaedrus.py

This script is responsible for the complete processing of the TEI XML source text for Phaedrus's Fables.

## Overview

The script performs the following key functions:

1.  **Parses** the TEI XML file for Phaedrus.
2.  **Segments** the text into individual tokens (words, punctuation, etc.) and normalizes digraphs (`æ` → `ae`, `œ` → `oe`) to maintain skeleton identity with macronized forms.
3.  **Classifies Tokens**: Each token is assigned a `tokenType` (1 = word, 2 = abbreviation, 3 = roman numeral, 4 = punctuation, 5 = editorial marker, 6 = other). Known abbreviations (e.g., praenomina like `C.`, `M.`) are re-attached to their trailing period during segmentation so they are treated as single tokens. Work-specific overrides can reclassify individual tokens via `WORK_SPECIFIC_TOKEN_OVERRIDES`.
4.  **Determines Proper Noun State**: For each word, it queries a local Morpheus API to determine if the word is a common noun (0), a proper noun (1), or could be either (2), based on both its dictionary form and its context in the text. Abbreviations are forced to state 1; numerals to state 0.
5.  **Detects Enclitics**: During morphological analysis, the script detects fused enclitics (`-que`, `-ne`, `-ve`, `-ue`, `-dum`) by comparing Morpheus's returned surface forms against the full token. When the full token is absent from the surface forms but a stem + clitic decomposition matches, the enclitic is recorded. For `-dum`, an additional check restricts detection to stems that are imperatives, interjections, or adverbs.
6.  **Assigns Expansions**: Abbreviations and numerals can be given a macronized expansion (e.g., `C.` → `Mārcus`, `I` → `ūnum`) via `WORK_SPECIFIC_EXPANSIONS`, keyed by fragment index. These expansions are always macronized because they feed directly into the app's macron-aware normalization columns.
7.  **Computes Sentence and Word Indices**: A `sentenceIdx` (per work) increments on sentence-terminal punctuation (`.`, `!`, `?`) and at forced boundaries (start of each poem/book title). A `wordIdx` (per sentence) increments only for tokens with `tokenType` ≤ 3, and is `NULL` for punctuation, editorial markers, and other non-word tokens.
8.  **Generates Source References**: Each token receives a CTS-style `sourceReference` string (e.g., `3.7.12` for book 3, poem 7, line 12) for display in the reader and concordance results.
9.  **Performs Macronization**: It queries a local Macronization API to determine the correct vowel lengths for every word in the text.
10. **Handles Ambiguity**: It intelligently separates macronization results into two categories:
    -   **Unambiguous Macronizations**: Words with stable vowel lengths are stored in a global, reusable CSV. For state-2 words (proper-or-common), both capitalized and lowercase forms are stored only when the macronizer knows both and they agree; when the capitalized form is unknown to the macronizer, only the lowercase form is stored.
    -   **Work-Specific Macronizations**: Words whose macronization is uncertain (nonzero uncertainty mask), unknown, context-dependent (different macrons depending on proper noun status), or morphologically unanalyzable are stored in a work-specific CSV.
    -   Non-word tokens (punctuation, abbreviations, numerals, etc.) are stored in the unambiguous table as-is.
11. **Generates CSVs**: It outputs a comprehensive set of structured data files ready for aggregation and use in the final application.
12. **Validates Output**: After generation, it runs a series of internal checks to ensure the result makes sense, including:
    -   Sequential index integrity for contents, subdivisions, and supplementary data.
    -   Subdivision parent-child range containment.
    -   Proper noun state completeness for all alphabetic words.
    -   Macronization coverage (every word instance has a source in exactly one table; no same-case duplicates across tables).
    -   Expansion completeness (every abbreviation/numeral token has a supplied expansion).
    -   Sentence and word index correctness (sequential per scope, `wordIdx` null iff `tokenType` ≥ 4).

    It may require small manual adjustments.
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

| File | Description |
|------|-------------|
| `works.csv` | Work metadata (id, name, about) |
| `authors.csv` | Author metadata (id, name, about, image) |
| `work_contents.csv` | Tokenized text with columns: `workId`, `idx`, `word`, `sourceReference`, `properNounState`, `tokenType`, `sentenceIdx`, `wordIdx`, `enclitic`, `expansion` |
| `work_content_subdivisions.csv` | Hierarchical structure (books, poems, verses, titles, etc.) |
| `work_content_supplementary.csv` | Notes, gaps, and other editorial annotations |
| `author_abbreviations.csv` | Standard abbreviations for the author |
| `work_abbreviations.csv` | Standard abbreviations for the work |
| `authors_and_works.csv` | Author-to-work relationships |
| `work_macronizations.csv` | Per-instance macronizations with uncertainty masks (`workId`, `idx`, `macronizedWord`, `uncertaintyBitMask`) |
| `unambiguous_macronizations.csv` | Global stable macronizations (`word`, `macronizedWord`) |

## How to Run

Ensure the prerequisite APIs are running, then execute the script from the project root:

```bash
python -m scripts.library.item.process_phaedrus
```