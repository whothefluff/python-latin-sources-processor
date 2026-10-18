import csv

from scripts.morphological_analysis.process_morpheus_perseids_api import readings_ruled_out_by_certain_vowels

_WORK = "00000000-0000-0000-0000-000000000001"


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([header, *rows])


def _ruled_out(tmp_path, tokens, unambiguous_macronizations, work_macronizations, readings):
    """Returns what certain vowels rule out in the work Carmen, whose tokens are each a word, its properNounState,
    tokenType, enclitic and expansion, with the unambiguous macronizations by word, the work's by token index with
    their masks, and readings that are each a form, a stem, a suffix and a lemma. Token i has the reference 1.i."""
    _write(tmp_path / "works.csv", ["id", "name"], [[_WORK, "Carmen"]])
    _write(tmp_path / "work_contents.csv",
           ["workId", "idx", "word", "sourceReference", "properNounState", "tokenType", "sentenceIdx", "wordIdx",
            "enclitic", "expansion"],
           ([_WORK, idx, word, f"1.{idx}", "" if state is None else state, token_type, 0, idx, enclitic, expansion]
            for idx, (word, state, token_type, enclitic, expansion) in enumerate(tokens)))
    _write(tmp_path / "unambiguous_macronizations.csv", ["word", "macronizedWord"], unambiguous_macronizations.items())
    _write(tmp_path / "work_macronizations.csv", ["workId", "idx", "macronizedWord", "uncertaintyBitMask"],
           ([_WORK, idx, macronized, mask] for idx, (macronized, mask) in work_macronizations.items()))
    _write(tmp_path / "morphological_details.csv", ["form", "item", "dictionaryRef"],
           ([form, item, lemma] for item, (form, _, _, lemma) in enumerate(readings)))
    _write(tmp_path / "morphological_detail_inflections.csv", ["form", "item", "cnt", "stem", "suffix"],
           ([form, item, 0, stem, suffix] for item, (form, stem, suffix, _) in enumerate(readings)))
    return readings_ruled_out_by_certain_vowels(tmp_path, tmp_path / "morphological_details.csv",
                                                tmp_path / "morphological_detail_inflections.csv")


def _counts(ruled_out):
    """Returns how many tokens rule out every reading, by macronization, and how many rule out each reading."""
    return ({macronized: len(references) for macronized, references in ruled_out.every_reading.items()},
            {tuple(reading): len(references) for reading, references in ruled_out.by_reading.items()})


def _word(word, state: int | None = 0, enclitic=""):
    return word, state, 1, enclitic, ""


def test_a_certain_vowel_rules_out_a_reading_of_the_other_length(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("tibi"), _word("tibi")], {"tibi": "tibi"}, {},
                              [("tibi", "tib", "ī", "tu")])) == ({"tibi": 2}, {("tibī", "tu"): 2})


def test_each_token_is_referred_to_by_its_works_name_and_its_reference(tmp_path):
    ruled_out = _ruled_out(tmp_path, [_word("tibi"), _word("tibi")], {"tibi": "tibi"}, {},
                           [("tibi", "tib", "ī", "tu")])

    assert ruled_out.every_reading == {"tibi": ["Carmen 1.0", "Carmen 1.1"]}
    assert ruled_out.by_reading == {("tibī", "tu"): ["Carmen 1.0", "Carmen 1.1"]}


def test_a_reading_that_another_reading_of_the_token_agrees_with_is_listed_alone(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("serpens")], {"serpens": "serpēns"}, {},
                              [("serpens", "serp", "ens", "serpens"), ("serpens", "serp", "ēns", "serpo")])) == (
        {}, {("serpens", "serpens"): 1})


def test_a_token_rules_out_a_reading_once_however_many_inflections_spell_it(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("tibi")], {"tibi": "tibi"}, {},
                              [("tibi", "tib", "ī", "tu"), ("tibi", "tib", "ī", "tu")])) == (
        {"tibi": 1}, {("tibī", "tu"): 1})


def test_tokens_are_counted_by_their_macronization_in_lowercase(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("Consilio"), _word("consilio")], {},
                              {0: ("Cōnsiliō", 0), 1: ("cōnsiliō", 0)},
                              [("consilio", "consili", "ō", "consilium")])) == (
        {"cōnsiliō": 2}, {("consiliō", "consilium"): 2})


def test_a_word_without_readings_is_left_out(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("fictum")], {"fictum": "fictum"}, {}, [])) == ({}, {})


def test_the_work_macronization_comes_before_the_unambiguous_one(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("consilio")], {"consilio": "consiliō"}, {0: ("cōnsiliō", 0)},
                              [("consilio", "consili", "ō", "consilium")])) == (
        {"cōnsiliō": 1}, {("consiliō", "consilium"): 1})


def test_an_uncertain_vowel_rules_out_nothing(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("mihi")], {}, {0: ("mihi", 0b1000)},
                              [("mihi", "mih", "ī", "ego")])) == ({}, {})


def test_a_token_without_a_macronization_rules_out_nothing(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("tibi")], {}, {}, [("tibi", "tib", "ī", "tu")])) == ({}, {})


def test_a_reading_with_other_letters_rules_out_nothing(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("elapsum")], {"elapsum": "ēlāpsum"}, {},
                              [("elapsum", "ex-lāps", "um", "elabor")])) == ({}, {})


def test_the_enclitic_that_morpheus_leaves_out_is_put_back(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("arvaque", enclitic="que")], {}, {0: ("arvāque", 0)},
                              [("arvaque", "arv", "a", "arvum")])) == ({"arvāque": 1}, {("arvaque", "arvum"): 1})


def test_only_the_length_of_a_certain_vowel_is_compared(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("Arva")], {}, {0: ("Arva", 0)}, [("arva", "arv", "a", "arvum")])) == (
        {}, {})


_VENERE = [("Venere", "Vēner", "e", "Venus"), ("venere", "vener", "e", "venio")]
_VENIO = [("Venere", "Vener", "e", "Venus"), ("venere", "vēn", "ēre", "venio")]


def test_a_name_has_only_the_capitalized_readings(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("Venere", state=1)], {"Venere": "Venere"}, {}, _VENERE)) == (
        {"venere": 1}, {("Vēnere", "Venus"): 1})


def test_a_common_word_has_only_the_lowercase_readings(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("Venere", state=0)], {"venere": "venere"}, {}, _VENIO)) == (
        {"venere": 1}, {("vēnēre", "venio"): 1})


def test_a_word_that_can_be_either_has_both(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("Venere", state=2)], {"Venere": "Venere"}, {}, _VENERE)) == (
        {}, {("Vēnere", "Venus"): 1})
    assert _counts(_ruled_out(tmp_path, [_word("Venere", state=2)], {"Venere": "Venere"}, {}, _VENIO)) == (
        {}, {("vēnēre", "venio"): 1})


def test_a_word_of_unknown_state_has_both(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("venere", state=None)], {"venere": "venere"}, {}, _VENERE)) == (
        {}, {("Vēnere", "Venus"): 1})
    assert _counts(_ruled_out(tmp_path, [_word("venere", state=None)], {"venere": "venere"}, {}, _VENIO)) == (
        {}, {("vēnēre", "venio"): 1})


def test_only_an_ending_that_morpheus_leaves_out_is_put_back(tmp_path):
    assert _counts(_ruled_out(tmp_path, [_word("redeo")], {}, {0: ("redeō", 0)},
                              [("redeo", "re-e", "ō", "redeo")])) == ({}, {})


def test_a_token_with_an_expansion_has_its_readings_and_its_certain_macrons(tmp_path):
    assert _counts(_ruled_out(tmp_path, [("V", 0, 3, "", "quīnque"), ("M.", 1, 2, "", "Mārcus")], {}, {},
                              [("quinque", "quinqu", "e", "quinque"), ("Marcus", "Mārc", "us", "Marcus"),
                               ("marcus", "marc", "us", "marcus")])) == ({"quīnque": 1}, {("quinque", "quinque"): 1})


def test_a_token_that_is_neither_a_word_nor_expanded_is_left_out(tmp_path):
    assert _counts(_ruled_out(tmp_path, [("ii", 0, 3, "", "")], {"ii": "ii"}, {}, [("ii", "i", "ī", "eo")])) == (
        {}, {})
