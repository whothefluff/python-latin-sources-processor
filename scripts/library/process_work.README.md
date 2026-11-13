# README for process_work.py

This module processes the TEI XML source text of a work. What is specific to the work's edition is in the work's own
script in `scripts/library/item/`, which runs this module with it: the edition's CTS URN, the letters that the edition
prints, the corrections that its tokens need, its author's abbreviations, and its about and image files. Phaedrus's
Fables are `process_phaedrus.py`.

The ids are the same on every run, so that a run changes only the rows whose data changed: the work's comes from its
edition's URN (`urn:cts:latinLit:phi0975.phi001.perseus-lat2`), which must be the edition's `n` when it has one, its
author's from the URN's textgroup (`urn:cts:latinLit:phi0975`), which the author's other works share, and each
subdivision's from the work's id and the type and count of each subdivision down to it (`BOOK 0/POEM 3/VERS 12`).
So a subdivision's id follows its place, not its edition label: a verse added or removed moves the ids of the later
subdivisions of its type next to it, and of what they hold. Another edition of a work is another work, with ids of its
own.

## Overview

The script performs the following key functions:

1.  **Parses** the TEI XML file of the work (`util/tei_edition.py`): its books and their poems, or its poems alone; line groups (`<lg>`, also nested) and speeches (`<sp>`, whose `<speaker>` is their title); verses, titles and paragraphs, each with the text of its quotations (`<q>`, `<quote>`), words set in capitals (`<hi rend="uppercase">`, and `<emph>` with the same `rend`), and numerals (`<num>`), and without its milestones and line breaks (a line break between words is a space); additions, deletions, and, outside a `<choice>`, the edition's sic (`<sic>`) and the editor's corrections (`<corr>`), each with a supplementary note over its tokens ("added by the editor", "marked for deletion", "sic", "corrected by the editor"), and blocks marked for deletion as a whole; and lost passages (`<gap reason="lost">` and `"omitted"`) where they are in a block. A page break (`<pb>`) is left out wherever it is, so that a page that starts inside a word doesn't split it, and so is the edition's own heading, the work's title, which its header gives. An abbreviation with its expansion, `<choice><abbr>locutu's</abbr><expan>locutu<ex>s e</ex>s</expan></choice>`, is read as printed, and the edition's expansion is kept to check the work's own (step 6); so is the shape of Amphitruo, Curculio and Menaechmi, with the `<expan>` inside the `<abbr>`, until their editions are fixed. A heading in another language than Latin is a supplementary note over what holds it, and takes no tokens. So is a note, unless it has a lemma (`<lem>`, `<w type="lemma">`) that matches the last words before it, without punctuation or case, with two dots or more, spaced or not (`...`, `. .`), for the words between: then it's a note over those words. A lemma that matches nothing, and an empty note, are logged as warnings that name the work, for whoever processes it to fix in the source. A note with more than one lemma raises, and so does one with a lemma outside a verse, title or paragraph. A poem whose `n` the work configures, such as `prologus`, gets that type. Any other structure raises, rather than being guessed at, and so does typography of any other `rend`, which can change what the text says: an overline multiplies a numeral by a thousand.
2.  **Segments** the text into individual tokens (words, punctuation, etc.) and normalizes digraphs (`æ` → `ae`, `œ` → `oe`) and takes out the acutes that mark the ictus (`audácior` → `audacior`, kept in `ictusBitMask`) to maintain skeleton identity with macronized forms. A printed word listed in the work's `WorkConfiguration.spellings_by_printed_word` is replaced by the spelling it maps to, in tokens and titles, before Morpheus and the macronizer see it (with `'Mercvrivs': 'Mercurius'` in it, `Mercvrivs` → `Mercurius`).
3.  **Classifies Tokens**: Each token is assigned a `tokenType` (1 = word, 2 = abbreviation, 3 = roman numeral, 4 = punctuation, 5 = editorial marker, 6 = other). Known abbreviations (e.g., praenomina like `C.`, `M.`) are re-attached to their trailing period during segmentation so they are treated as single tokens. A token inside a `<num>` is a numeral, as the edition says, whatever its shape; a `<num>` that holds only part of a token (`<num>x</num>viri`) raises. Work-specific overrides can reclassify individual tokens via the work's `token_overrides` (`WORK_SPECIFIC_TOKEN_OVERRIDES` in Phaedrus's script).
4.  **Determines Proper Noun State**: For each word, it queries a local Morpheus API to determine if the word is a common noun (0), a proper noun (1), or could be either (2), based on both its dictionary form and its context in the text. Abbreviations are forced to state 1; numerals to state 0.
5.  **Detects Enclitics**: During morphological analysis, the script detects fused enclitics (`-que`, `-ne`, `-ve`, `-ue`, `-dum`) by comparing Morpheus's returned surface forms against the full token. When the full token is absent from the surface forms but a stem + clitic decomposition matches, the enclitic is recorded. Morpheus is queried with strictCase, and a capitalized token gets no analysis when all its forms are lowercase (`Seque`), so the token is looked up in both. An enclitic counts only when neither answer analyzes the whole token: `Iove` is Juppiter, not `io` and `ve`. When one case is split and the other has no analysis, the other case's host is still looked up, since a capitalized host can be a name. When neither case has any analysis, the host is looked up in both. For `-dum`, an additional check restricts detection to stems that are imperatives, interjections, or adverbs. Which endings are split, and why: [`ENCLITICS.md`](../../../ENCLITICS.md).
6.  **Assigns Expansions**: Abbreviations and numerals can be given a macronized expansion (e.g., `C.` → `Mārcus`, `I` → `ūnum`) via the work's `expansions` (`WORK_SPECIFIC_EXPANSIONS` in Phaedrus's script), keyed by fragment index. These expansions are always macronized because they feed directly into the app's macron-aware normalization columns. A word printed short gets its whole word there too, keeps a word's proper noun state, and gets no enclitic. Plautus and some other poets join es ("you are") to the word before it, and leave letters out: `locutu's` is locutus es. Such a contraction is three tokens, the words locutu (`locūtus`) and s (`es`) and the apostrophe, so that each is looked up and counted as its whole word. The work fails, before the macronizer is asked, when one of the two words lacks its expansion; when the edition expands them (locutus es) and their expansions, joined by a space, don't have its letters without macrons and case (where the edition prints one letter for two, either); when it doesn't (Catullus's `beatu's`), and the first one's expansion doesn't start with the letters that it prints, or the s's isn't es; and when any other word has an expansion.
7.  **Computes Sentence and Word Indices**: A `sentenceIdx` (per work) increments on sentence-terminal punctuation (`.`, `!`, `?`) and at forced boundaries: a title, the first block of a poem, prologue or epilogue, and the first block after a speaker. A `wordIdx` (per sentence) increments only for tokens with `tokenType` ≤ 3, and is `NULL` for punctuation, editorial markers, and other non-word tokens.
8.  **Generates Source References**: Each token receives a CTS-style `sourceReference` string for display in the reader and concordance results: the TEI `n` of each division above it that the edition cites (the work's `cited_division_subtypes`), then its verse's (e.g., `3.7.12` for book 3, poem 7, line 12 in Phaedrus, and `14a.3` for poem 14a, line 3 in Catullus, who cites poems but not books).
9.  **Performs Macronization**: It queries a local Macronization API to determine the correct vowel lengths for every word in the text.
10. **Handles Ambiguity**: It intelligently separates macronization results into two categories:
    -   **Unambiguous Macronizations**: Words with stable vowel lengths are stored in a global, reusable CSV. For state-2 words (proper-or-common), both capitalized and lowercase forms are stored only when the macronizer knows both and they agree; when the capitalized form is unknown to the macronizer, only the lowercase form is stored.
    -   **Work-Specific Macronizations**: Words whose macronization is uncertain (nonzero uncertainty mask), unknown, context-dependent (different macrons depending on proper noun status), or morphologically unanalyzable are stored in a work-specific CSV.
    -   **Certain Macronizations That Differ**: When the macronizer is certain of a word but macronizes it differently in different places, the word stays out of the global CSV, and every certain occurrence that the reader would look up under it gets its own macronization in the work-specific CSV, with mask 0. So does a certain occurrence that the reader would look up under another token's macronization, such as a capitalized I under a numeral I's.
    -   Non-word tokens (punctuation, abbreviations, numerals, etc.) are stored in the unambiguous table as-is.
    -   **Words Printed Short**: A word with an expansion gets its macronization in the work-specific CSV, certain (mask 0), and not from the macronizer, which reads only the letters that it prints: its expansion's macrons on those letters where they start or end the expansion, a capital aside (locūtu of locūtus, s of es). Where they don't, as Amphitruo's old spelling `vaniloquo's` for vāniloquus es, the work's `printed_macronizations` gives it, by fragment index and with the token's letters (`vāniloquo`). The work fails, before the macronizer is asked, when one is missing there, when one is there that the expansion already gives or for a token that isn't a word with an expansion, and when its letters aren't the token's. A word printed short gets its j and v as any word does, from Morpheus's reading of the letters that it prints; where Morpheus has none, the work's `spellings_by_printed_word` gives them, as `{'Iniuriu': 'Injuriu'}` does for Curculio's `Iniuriu's`, injūrius es.
11. **Spells Consonants as `j` and `v`**: Where the edition prints one letter for two sounds, as Phaedrus's edition prints `i` for both `i` and `j`, each word gets the letter that Morpheus's analyses of the word have, so `iam` becomes `jam`. When Morpheus splits off an enclitic, the analyses of the host decide. Letters that the edition tells apart, `u` and `v` in Phaedrus's, stay as printed. Words are respelled only when the CSVs are written, because the steps before look words up as the source prints them. `works.csv` records the letters that the edition prints (`PIPELINE_CONTRACT.md`, section 5).
12. **Generates CSVs**: It outputs a comprehensive set of structured data files ready for aggregation and use in the final application.
13. **Validates Output**: It writes the files to a temporary directory and runs a series of internal checks to ensure the result makes sense, then moves them to the output directory. When any check fails, it raises and leaves the output directory as it was. The checks include:
    -   Sequential index integrity for contents and supplementary data. Subdivisions are counted among their siblings of the same type, from 0 up, whatever the edition numbers them (Phaedrus 4.24 has no verse 4), and a subdivision has one title at most, numbered 0, as the reader's unique index requires.
    -   Edition labels: books, poems, prologues, epilogues and verses have one, and other subdivisions none.
    -   Subdivision parent-child range containment.
    -   Proper noun states: 1 for every abbreviation, 0 for every numeral, none for punctuation, editorial marks and other tokens. Words without one, which Morpheus has no analysis for, are logged for review.
    -   Macronization coverage (every word token has its own macronization, or an unambiguous one under the key that the reader looks it up by, which depends on its proper noun state).
    -   Expansion completeness (every abbreviation/numeral token has a supplied expansion).
    -   Sentence and word index correctness (sequential per scope, `wordIdx` null iff `tokenType` ≥ 4).
    -   Letters checked against Morpheus. Every word must have Morpheus's letter where the edition prints one letter for two. The check also logs, for review, the words that Morpheus spells with both letters of a pair that the edition tells apart, and the words that keep the edition's letters because no analysis has the same letters.

    It may require small manual adjustments.
## Prerequisites

This script requires two local APIs to be running on your machine. Please refer to their respective repositories for setup and installation instructions.

1.  **Morpheus API (Morphological Analysis)**
    -   Provides dictionary lookup and morphological analysis.
    -   **Repository**: [whothefluff/morpheus-perseids-api](https://github.com/whothefluff/morpheus-perseids-api)

2.  **Latin Macronizer API**
    -   Provides macronization (vowel length) analysis.
    -   **Repository**: [whothefluff/latin-macronizer](https://github.com/whothefluff/latin-macronizer)

The script expects the Morpheus API at port 1500 and the Macronizer API at port 8001, on `localhost` or on the host
named in `SERVICES_HOST`.

## Input

-   **Source XML**: the work's, such as `data/library/item/phaedrus/phi0975.phi001.perseus-lat2_modified.xml` for
    Phaedrus

## Output

The work's script generates the following files in its directory of `output/library/item/`, such as
`output/library/item/phaedrus/`:

| File | Description |
|------|-------------|
| `works.csv` | Work metadata (id, name, about) and the edition's letters (`uvLowercase`, `uvCapitals`, `ijLowercase`, `ijCapitals`) |
| `authors.csv` | Author metadata (id, name, about, image) |
| `work_contents.csv` | Tokenized text with columns: `workId`, `idx`, `word`, `sourceReference`, `properNounState`, `tokenType`, `sentenceIdx`, `wordIdx`, `enclitic`, `expansion` |
| `work_content_subdivisions.csv` | Hierarchical structure (books, poems, verses, titles, etc.). `editionLabel` is the subdivision's TEI `n`, preserved as text (`appendix`, `prologus`, `14a`, `3ff`) |
| `work_content_supplementary.csv` | Notes, gaps, and other editorial annotations |
| `author_abbreviations.csv` | Standard abbreviations for the author (sources: [`ABBREVIATIONS.md`](../../../ABBREVIATIONS.md)) |
| `work_abbreviations.csv` | Standard abbreviations for the work (sources: [`ABBREVIATIONS.md`](../../../ABBREVIATIONS.md)) |
| `authors_and_works.csv` | Author-to-work relationships |
| `work_macronizations.csv` | Per-instance macronizations with uncertainty masks (`workId`, `idx`, `macronizedWord`, `uncertaintyBitMask`) |
| `unambiguous_macronizations.csv` | Global stable macronizations (`word`, `macronizedWord`) |

## How to Run

Ensure the prerequisite APIs are running, then execute the work's script from the project root:

```bash
python -m scripts.library.item.process_phaedrus
```