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

## 3. Expansions and Enclitics

In `work_contents.csv`:

* **Expansion Format:** The `expansion` column is exported display-cased and macronized (e.g., `Mārcus`, not `marcus`).
* **Mutual Exclusivity:** A single token will *never* have both an `expansion` and an `enclitic`.

## 4. Token & Sentence Tracking

In `work_contents.csv`:

* `wordIdx` increments if and ONLY if `tokenType <= 3` (Words, Abbreviations, Numerals). Punctuation and editorial marks
  export a null/empty `wordIdx`.
* `tokenType == 2` (Proper Abbreviations like 'M.') are forced to `properNounState = 1` so downstream systems case them
  as proper nouns.
* `tokenType == 3` (Numerals like 'XII') are forced to `properNounState = 0` so downstream systems case them as common
  lowercase words.