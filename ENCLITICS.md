# Enclitics

Which word endings the pipeline splits off into the `enclitic` column of `work_contents.csv`, and why. Checked on
2026-10-10 against Lewis & Short (`data/dictionary/lexica/lat.ls.perseus-eng2.xml`) and the Latin stem files of
[morpheus-alatius-xml](https://github.com/whothefluff/morpheus-alatius-xml) (`my-custom-build`).

## The rule

Split an ending off only when the word it forms has no Lewis & Short entry of its own, so the reader looks up the host
and the enclitic separately. An entry that only points elsewhere ("ĕgŏmet, v. … met") counts as none.

`SPLIT_ENCLITICS` (`process_work.py`) holds `que`, `ne`, `ve`, `ue`, `dum`:

- `que`, `ne` and `ve` attach to any word, and each has its own L&S entry. `ue` is `ve` in editions without v.
- `dum` only after an imperative, interjection or adverb (`_is_valid_dum_stem`): `agedum` has no entry, while `age` and
  `dum` do. Adverbs that have their own entry (`nondum`, `interdum`, `vixdum`) are whole words in Morpheus, which
  analyzes them without stripping anything.

The list is deliberately a subset of Morpheus's `LatinSuff` (`src/anal/checkstring.c`). Don't sync the two.

## Not split

- **`cumque`/`cunque`, `libet`, `vis`:** they form words with their own L&S entry (quīcumque, ubicumque, quamlibet,
  quīvīs, quamvīs…).
- **`piam`, `dem`:** the same (quispiam, īdem, tandem, quidem, prīdem…), and L&S has no entry for the ending itself.
- **`met`:** L&S treats it as a suffix (its `egomet` entry only points to `ego` and `met`), but Morpheus lists egomet,
  memet, mihimet, nōsmet, nōbīsmet, tūtemet and vōsmet as whole forms of the personal pronouns. Only the forms it lacks
  (sēmet, tēmet, sibimet) would be split, which is inconsistent. Its `irreg.nom.src` files egomet, meīmet and mihimet
  under `nos` instead of `ego`: a fix for the fork, not a reason to split.
- **`cum` (mēcum, tēcum, sēcum, nōbīscum):** L&S headwords, and Morpheus lists them as forms of the personal pronouns.
- **`ce`, `cine`:** Morpheus lists huiusce, hōsce, hīsce, hicine… as forms of `hic` and `ille`.
- **`n` (viden, satin, tun, ain, scin, vin…):** -ne cut short to n, in place of a final s (vidēsne, satisne) or
  after a vowel (tūne, cēnāvīne); L&S's -ne entry: "also apocopated n' and only n". Cutting the string gives the
  wrong host (vide, sati), and Morpheus guesses at a final n when the word has no analysis of its own
  (`checkstring.c`), with the n as s and without it. The guess is right for some, which keep it (ten is tē, egon
  ego), and wrong for most: viden got the imperative vidē too, satin sata, satum and sero's satī and satīs, vin the
  noun vīs. Those are whole forms in the Morpheus fork, spelled as the word with its quantities (sătĭn, vīn, scīn)
  and answered with their own readings alone (satin with satis's adverb and indeclinable). A few words that Morpheus
  reads in their own right are a word of this kind in some tokens, and keep their readings beside the whole form: in,
  quin and eon are also isne and īsne, quīne and eōne. Every kind has a line in the macronizer's lexicon. A vowel that
  can be either length is common, so the text leaves it uncertain: viden's, abin's and iuben's last, which iambic
  shortening can shorten. So is a vowel that the readings disagree on (mean's a, short in the nominative and common
  in the ablative; in's i, short in the preposition and long in īsne). The fork's
  `tests/latin_assertions_ne_cut_short.txt` lists every kind. The -ne isn't shown.
- **`pte` (suopte, suapte):** the same as `met`. L&S has an entry for the ending, but Morpheus lists suōpte and suāpte
  as whole forms of suus (`nom.latin.bas`, next to suōmet and suāmet), so they get its reading without splitting
  anything (Catullus 51.10). Other hosts (meōpte, tuōpte) would need an analysis added, not splitting.

## How detection works

- **2015:** Alatius's `a4d8f61` ("Don't try to guess short enclitics") commented `que`, `ne`, `ve`, `ue`, `vis`,
  `piam`, `dem` and `dum` out of `LatinSuff`. morpheus-alatius-xml v1.0.0 and v1.0.1 include it. Morpheus then couldn't
  analyze a word carrying one of them, so the script strips the ending itself and queries the stem (the fallback, now
  in `_morpheus_reading`). The list was named `COMMENTED_OUT_CLITICS` after that.
- **2026-03-29:** upstream's `dc47d28` reverted it, and v2.0.0 includes the revert. Morpheus strips every `LatinSuff`
  ending itself, only when the whole word fails, and returns the host's analysis. The surface-form check finds which
  ending it stripped. The list became `SPLIT_ENCLITICS` on 2026-10-10.
- **The fallback stays** in case a build stops stripping enclitics again. It runs only when neither the lowercase nor
  the capitalized word is analyzed whole, so `Iove` (Juppiter) is never asked for as `io`. It takes the ending that
  Morpheus split off in the other case, or else the first that matches (`que` before `ue`), which is harmless for these
  five: no Latin stem ends in q.
- **The morphology script's `ENCLITICS`** is a different list, for analysis retries and part-of-speech heuristics. It has
  nothing to do with splitting; don't merge the two.
- **Which build runs** is whatever your API container uses.
