# Pipeline Data Contract

This contract defines the invariants guaranteed by the CSVs exported from this pipeline. Downstream consumers (e.g., the
Flutter reader app) rely on these rules to build their match domains, frequency counts, and dictionary joins.

## 1. Skeleton Identity

In `work_contents.csv`, the `word` and `macronizedWord` columns MUST have identical character skeletons.

* **Digraphs:** Ligatures like `æ/œ` are normalized to `ae/oe` in the pipeline *before* macronization. One character (
  `æ`) becoming two (`ae`) downstream would break substring math for enclitics and bitmasks.

## 2. Match Domain Casing Rule & Morphological Uniqueness

Any time a base/dictionary form is exported (specifically `form` and `macronizedForm` in the `MorphologicalDetails` and
`MorphologicalDetailInflections` CSVs), it MUST follow a strict 2-shape casing rule:

* If it is a proper noun: `Capitalized` (Title Case).
* Otherwise: `lowercase`.

**Uniqueness Guarantee:** The morphological pipeline analyzes unique word formations based on this canonical casing. It
will *never* export separate duplicate rows for surface casing variations (e.g., `fabula` vs `FABULA`). The downstream
reader handles surface-casing searches dynamically, so duplicate morph entries provide no benefit and violate the data
model.

**Detached Enclitics:** An enclitic split off in `work_contents.csv` has its analyses under its own `form`, with a
hyphen in front: the *ne* of *tune* is `-ne`, apart from the word `ne`.

## 3. Expansions and Enclitics

In `work_contents.csv`:

* **Expansion Format:** The `expansion` column is exported display-cased and macronized (e.g., `Mārcus`, not `marcus`).
* **Mutual Exclusivity:** A single token will *never* have both an `expansion` and an `enclitic`.
* **Which Enclitics:** Only the endings listed in [`ENCLITICS.md`](ENCLITICS.md) are split off.

## 4. Token & Sentence Tracking

In `work_contents.csv`, every chunk of text is assigned a `tokenType`:

* `1`: Word (Alphabetic text categorized as a "normal" word)
* `2`: Abbreviation (e.g., 'M.', 'Ti.')
* `3`: Roman Numeral (e.g., 'XII', 'MDCCLXXVI', 'IIII')
* `4`: Punctuation
* `5`: Editorial Mark (e.g., '†', '*')
* `6`: Other (e.g., unrecognized alphanumeric mixes)

**Editorial Marks vs. Supplementary Ranges:**

* `TokenType.EDITORIAL` is strictly for **literal characters present in the text stream** as if they were part of the
  normal text.
* Annotations that span ranges of text (like `<note>`, `<del>`, or `<gap>`) and that are stored in
  `work_content_supplementary.csv` may or may not be accompanied by editorial tokens.

**Indexing & Casing Rules:**

* `wordIdx` increments if and ONLY if `tokenType <= 3`. Punctuation and editorial marks export a null/empty `wordIdx`.
* `tokenType == 2` (Abbreviations) are forced to `properNounState = 1`.
* `tokenType == 3` (Numerals) are forced to `properNounState = 0`.

**Numeral Collisions:**
Valid Roman numerals often collide with valid Latin words (e.g., 'I', 'VI', 'DI'). The global pipeline defaults to
classifying these as Words (`tokenType = 1`) if the morphological analyzer finds a lemma. **If this default is
contextually wrong for a specific text, the work-specific processor MUST explicitly overwrite the `tokenType`
and `properNounState`.**

## 5. Letters i/j and u/v

Word tokens in `work_contents.csv`, their macronizations and the `TITL` names in `work_content_subdivisions.csv`
write consonants as `j` and `v` and vowels as `i` and `u`, as Morpheus spells them, so they compare directly with the
morphology forms:

* **Edition First:** Where the edition tells the two letters apart (u and v in the bundled Phaedrus), its letter stays.
* **Morpheus Fills In:** Where it prints one letter for both (i), Morpheus's spelling of the word decides. A word that
  no analysis spells with its other letters, or that analyses spell in more than one way, keeps the edition's letter.
* **Edition Letters:** `works.csv` records what the edition printed, so the reader can show it: `uvLowercase` (`uv`,
  `u` or `v`), `uvCapitals` (`UV`, `U` or `V`), `ijLowercase` (`ij`, `i` or `j`) and `ijCapitals` (`IJ`, `I` or
  `J`). Two letters mean the edition tells them apart; one letter stands for both.
* **Hand-Written Data:** Expansions and override analyses are written the same way by hand.

## 6. Subdivisions

In `work_content_subdivisions.csv`:

* **Types:** `BOOK`, `POEM`, `PROL`, `EPIL`, `LGRP` (a group of lines, `<lg>`), `SPCH` (a speech, `<sp>`, whose
  `TITL` is its speaker), `TITL`, `VERS` and `PARA`. The roots are the books or, in a work without books, its poems,
  prologues and epilogues.
* **`cnt`:** a subdivision's position among its siblings of the same type, from 0, whatever the edition numbers it.
* **`editionLabel`:** the subdivision's TEI `n`, preserved as text. Books, poems, prologues, epilogues and verses have
  one (`1`, `appendix`, `prologus`, `14a`, `3ff`), and other subdivisions none.
