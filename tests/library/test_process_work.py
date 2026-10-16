import logging
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import pytest
import requests

from scripts.library import process_work
from scripts.library.util.proper_noun import ProperNounState
from scripts.library.util.spelling import LetterConvention
from scripts.library.util.token_classification import TokenType

_CARMEN_FILES = Path(__file__).parent / 'fixtures' / 'carmen'
# u and v apart, i for both i and j
_CARMEN_LETTERS = LetterConvention(uv_lowercase="uv", uv_capitals="UV", ij_lowercase="i", ij_capitals="I")
_CARMEN_WORK = process_work.WorkConfiguration(
    letter_convention=_CARMEN_LETTERS, token_overrides={}, expansions={}, proper_noun_overrides={},
    author_abbreviations=('Fict.',), work_about_file=str(_CARMEN_FILES / 'work_about.txt'),
    author_about_file=str(_CARMEN_FILES / 'author_about.txt'),
    author_image_file=str(_CARMEN_FILES / 'author_image.bin'))


@pytest.fixture(autouse=True)
def _forget_morpheus_answers():
    for cached in (process_work._lookup, process_work._morpheus_reading,
                   process_work.determine_proper_noun_state):
        cached.cache_clear()


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _Inflection(NamedTuple):
    """An inflection with its stem and suffix as Morpheus writes them, such as 'ob:jurg' and 'a_bat'"""
    stem: str
    suffix: str | None = None
    pofs: str | None = None
    mood: str | None = None


class _Entry(NamedTuple):
    headword: str
    inflections: tuple


def _entry(headword, *surfaces):
    """Returns an entry for the headword with one inflection per surface. A surface is a stem, a stem and a suffix, or
    an _Inflection"""
    return _Entry(headword, surfaces)


def _inflection(surface) -> _Inflection:
    if isinstance(surface, _Inflection):
        return surface
    return _Inflection(surface) if isinstance(surface, str) else _Inflection(*surface)


def _morpheus_xml(answer):
    """Returns Morpheus's answer for an _Entry, or for a list of surfaces with the headword x"""
    entry = answer if isinstance(answer, _Entry) else _Entry("x", tuple(answer))
    infls = ''.join(f'<infl><term><stem>{i.stem}</stem>{f"<suff>{i.suffix}</suff>" if i.suffix else ""}</term>'
                    f'{f"<pofs>{i.pofs}</pofs>" if i.pofs else ""}{f"<mood>{i.mood}</mood>" if i.mood else ""}</infl>'
                    for i in map(_inflection, entry.inflections))
    return f'<words><word><entry><dict><hdwd>{entry.headword}</hdwd></dict>{infls}</entry></word></words>' if infls \
        else '<words/>'


def _morpheus(monkeypatch, answers):
    """Makes Morpheus give each word in answers that answer, and any other word no analysis.
    Returns the words asked for, in order."""
    asked = []

    def get(url, params, headers, timeout):
        asked.append(params['word'])
        return _Response(_morpheus_xml(answers.get(params['word'], [])))

    monkeypatch.setattr(process_work.requests, "get", get)
    return asked


@pytest.mark.parametrize("word", ["seque", "Seque", "SEQUE"])
def test_find_enclitic_finds_a_common_word_enclitic_in_any_case(monkeypatch, word):
    _morpheus(monkeypatch, {"seque": _entry("sui", "se")})

    assert process_work.find_enclitic(word, _CARMEN_LETTERS) == "que"


@pytest.mark.parametrize("word", ["Caesarque", "caesarque"])
def test_find_enclitic_finds_a_proper_noun_enclitic_in_any_case(monkeypatch, word):
    _morpheus(monkeypatch, {"Caesarque": _entry("Caesar", ("Caesa^r", "*"))})

    assert process_work.find_enclitic(word, _CARMEN_LETTERS) == "que"


@pytest.mark.parametrize("word, expected", [("iam", "jam"), ("Iam", "Jam"), ("voluit", "voluit"), ("ait", "ait")])
def test_spelled_with_morpheus_letters_takes_morpheus_j_and_keeps_the_edition_u(monkeypatch, word, expected):
    _morpheus(monkeypatch, {"iam": ["jam"], "voluit": ["voluit", "volvit"], "ait": ["ait"]})

    assert process_work.spelled_with_morpheus_letters(word, _CARMEN_LETTERS) == expected


def test_a_host_that_morpheus_spells_with_j_gets_its_enclitic(monkeypatch):
    _morpheus(monkeypatch, {"iamque": ["jam"]})

    assert (process_work.find_enclitic("Iamque", _CARMEN_LETTERS),
            process_work.spelled_with_morpheus_letters("Iamque", _CARMEN_LETTERS)) == ("que", "Jamque")


def test_a_word_gets_what_the_letters_of_its_work_give_it_whatever_another_work_got_before(monkeypatch):
    _morpheus(monkeypatch, {"iamque": ["jam"]})
    i_and_j_apart = _CARMEN_LETTERS._replace(ij_lowercase="ij", ij_capitals="IJ")

    assert [(process_work.find_enclitic("Iamque", letters),
             process_work.spelled_with_morpheus_letters("Iamque", letters))
            for letters in (_CARMEN_LETTERS, i_and_j_apart, _CARMEN_LETTERS)] == [
        ("que", "Jamque"), (None, "Iamque"), ("que", "Jamque")]


@pytest.mark.parametrize("stem, suffix, expected", [("ob:jurg", "a_bat", "objurgabat"), ("vi^r", "*", "vir")])
def test_surface_forms_leave_out_the_prefix_and_empty_suffix_marks(stem, suffix, expected):
    assert process_work._surface_forms(_morpheus_xml([(stem, suffix)])) == {expected}


@pytest.mark.parametrize("word, expected", [("obiurgabat", "objurgabat"), ("Obiurgabat", "Objurgabat")])
def test_a_compound_that_morpheus_spells_with_j_gets_it(monkeypatch, word, expected):
    _morpheus(monkeypatch, {"obiurgabat": [("ob:jurg", "a_bat")]})

    assert process_work.spelled_with_morpheus_letters(word, _CARMEN_LETTERS) == expected


@pytest.mark.parametrize("word, host, expected", [("obiurgatque", ("ob:jurg", "at"), "objurgatque"),
                                                  ("virque", ("vi^r", "*"), "virque")])
def test_a_compound_host_or_a_host_without_a_suffix_gets_its_enclitic(monkeypatch, word, host, expected):
    _morpheus(monkeypatch, {word: [host]})

    assert process_work.find_enclitic(word, _CARMEN_LETTERS) == "que"
    assert process_work.spelled_with_morpheus_letters(word, _CARMEN_LETTERS) == expected


@pytest.mark.parametrize("unreachable", ["musaque", "musa"], ids=["the word", "its host"])
def test_a_request_to_morpheus_that_fails_raises_and_leaves_nothing_cached(monkeypatch, unreachable):
    _morpheus(monkeypatch, {"musa": _entry("musa", ("mu^s", "a"))})
    answer = process_work.requests.get

    def get(url, params, headers, timeout):
        if params['word'] == unreachable:
            raise requests.exceptions.ConnectionError(f"No answer for '{unreachable}'")
        return answer(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(process_work.requests, "get", get)
    with pytest.raises(requests.exceptions.ConnectionError):
        process_work.find_enclitic("musaque", _CARMEN_LETTERS)
    monkeypatch.setattr(process_work.requests, "get", answer)

    assert process_work.find_enclitic("musaque", _CARMEN_LETTERS) == "que"


@pytest.mark.parametrize("word, answers, error", [
    ("levis", {"levis": "<words><word>"}, process_work.ET.ParseError),
    ("levis", {"levis": "<error>unknown engine</error>"}, ValueError),
    ("agedum", {"age": "<words><word>"}, process_work.ET.ParseError),
], ids=["not XML", "an error", "not XML for a host that dum may follow"])
def test_an_answer_that_is_an_error_or_isnt_xml_raises(monkeypatch, word, answers, error):
    monkeypatch.setattr(process_work.requests, "get",
                        lambda url, params, headers, timeout: _Response(answers.get(params['word'], '<words/>')))

    with pytest.raises(error):
        process_work.find_enclitic(word, _CARMEN_LETTERS)


# Morpheus splits iove as io and ve, and knows Iove whole, as Juppiter
_IO = _entry("io", _Inflection("i^o", pofs="exclamation"))
_IOVE = {"iove": _IO, "io": _IO, "Iove": _entry("Juppiter", ("Jov", "e"))}


def test_a_word_that_morpheus_knows_whole_in_one_case_has_no_enclitic(monkeypatch):
    _morpheus(monkeypatch, _IOVE)

    assert process_work.find_enclitic("Iove", _CARMEN_LETTERS) is None
    assert process_work.spelled_with_morpheus_letters("Iove", _CARMEN_LETTERS) == "Jove"


def test_a_word_that_morpheus_knows_whole_only_as_a_name_is_a_name(monkeypatch):
    _morpheus(monkeypatch, _IOVE)

    assert process_work.determine_proper_noun_state("Iove", True, False, _CARMEN_LETTERS) == (ProperNounState.YES,
                                                                                               ProperNounState.YES)


def test_a_word_that_morpheus_knows_whole_in_one_case_is_never_asked_for_without_an_ending(monkeypatch):
    asked = _morpheus(monkeypatch, _IOVE)

    process_work.find_enclitic("Iove", _CARMEN_LETTERS)
    process_work.morpheus_surfaces("iove", _CARMEN_LETTERS)
    process_work.determine_proper_noun_state("Iove", True, False, _CARMEN_LETTERS)

    assert asked == ["iove", "Iove"]


def test_a_split_in_one_case_still_asks_for_the_host_in_the_other(monkeypatch):
    asked = _morpheus(monkeypatch, {"jubetque": _entry("jubeo", ("jub", "et"))})

    assert process_work.find_enclitic("Jubetque", _CARMEN_LETTERS) == "que"
    assert asked == ["jubetque", "Jubetque", "Jubet"]


def test_a_name_that_only_the_capitalized_host_has_counts(monkeypatch):
    _morpheus(monkeypatch, {"venereque": _entry("venio", ("ve_n", "e_re")), "Venere": _entry("Venus", ("Vener", "e"))})

    assert process_work.find_enclitic("Venereque", _CARMEN_LETTERS) == "que"
    assert process_work.determine_proper_noun_state("Venereque", False, False, _CARMEN_LETTERS) == (
        ProperNounState.EITHER, ProperNounState.YES)


def test_a_word_that_neither_case_knows_gets_the_enclitic_of_a_host_that_answers(monkeypatch):
    asked = _morpheus(monkeypatch, {"musa": _entry("musa", ("mu^s", "a"))})

    assert process_work.find_enclitic("Musaque", _CARMEN_LETTERS) == "que"
    assert process_work.morpheus_surfaces("Musaque", _CARMEN_LETTERS) == {"musa"}
    assert asked == ["musaque", "Musaque", "musa", "Musa"]


_AGE = _Inflection("ag", "e", mood="imperative")
_AGE_AS_A_NOUN = _Inflection("ag", "e", pofs="noun")


@pytest.mark.parametrize("word, answers, expected", [
    ("agedum", {"agedum": _entry("ago", _AGE)}, "dum"),
    ("ehodum", {"ehodum": _entry("eho", _Inflection("eho", pofs="exclamation"))}, "dum"),
    ("agedum", {"agedum": _entry("x", _AGE_AS_A_NOUN), "age": _entry("ago", _AGE)}, "dum"),
    ("agedum", {"agedum": _entry("x", _AGE_AS_A_NOUN), "age": _entry("x", _AGE_AS_A_NOUN)}, None),
    ("vixdum", {"vix": _entry("vix", _Inflection("vix", pofs="adverb"))}, "dum"),
    ("agedum", {"age": _entry("x", _AGE_AS_A_NOUN)}, None),
])
def test_dum_is_an_enclitic_only_after_an_imperative_an_interjection_or_an_adverb(monkeypatch, word, answers,
                                                                                    expected):
    _morpheus(monkeypatch, answers)

    assert process_work.find_enclitic(word, _CARMEN_LETTERS) == expected
    assert bool(process_work.morpheus_surfaces(word, _CARMEN_LETTERS)) == (expected is not None)


_CARMEN = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title xml:lang="lat">Carmen</title><author>Fictor</author></titleStmt></fileDesc>
  </teiHeader>
  <text><body><div type="textpart" subtype="book" n="1"><div type="textpart" subtype="poem" n="1">
    <l n="1">Levis et levis est.</l>
    <l n="2">Est levis, levis.</l>
    <l n="3">iacere et iacere iam.</l>
  </div></div></body></text>
</TEI>"""
_CARMEN_ANALYSES = {word: _entry(headword, surface)
                    for word, headword, surface in [("levis", "levis", "levis"), ("et", "et", "et"),
                                                    ("est", "sum", "est"), ("iacere", "jaceo", "jacere"),
                                                    ("iam", "jam", "jam"), ("i", "eo", "i")]}
# Certain of levis as lĕvis in the first verse and as lēvis in the second, except for the last levis, of iacere as
# jacēre and as jacere, and of iam
_CARMEN_MACRONIZED = [("Levis", "Levis", 0), ("et", "et", 0), ("levis", "levis", 0), ("est", "est", 0), (".", ".", 0),
                      ("Est", "Est", 0), ("levis", "lēvis", 0), (",", ",", 0), ("levis", "levis", 2), (".", ".", 0),
                      ("iacere", "iacēre", 0), ("et", "et", 0), ("iacere", "iacere", 0), ("iam", "iam", 0),
                      (".", ".", 0)]


def _macronizer_answers(monkeypatch, macronized):
    """Makes the macronizer answer any text with macronized, a list of (word, macronized word, mask)."""
    monkeypatch.setattr(process_work, "macronize_text", lambda text: [
        process_work.TokenResult(word=word, is_word=word.isalpha(), macronized=macronized, uncertainty_mask=mask,
                                 candidates=[])
        for word, macronized, mask in macronized])


def _process_carmen(monkeypatch, output_dir, xml=_CARMEN, macronized=_CARMEN_MACRONIZED, work=_CARMEN_WORK):
    _morpheus(monkeypatch, _CARMEN_ANALYSES)
    process_work.determine_proper_noun_state.cache_clear()
    _macronizer_answers(monkeypatch, macronized)
    process_work.process_verse(xml, output_dir, work)


@pytest.fixture
def carmen(monkeypatch, tmp_path):
    _process_carmen(monkeypatch, tmp_path)
    return tmp_path


def _rows(csv_path, *dropped_columns):
    return sorted(map(tuple, pd.read_csv(csv_path).drop(columns=list(dropped_columns)).values.tolist()))


def test_each_certain_occurrence_of_a_word_that_the_work_macronizes_in_two_ways_gets_its_own_macronization(carmen):
    assert _rows(carmen / "work_macronizations.csv", "workId") == [
        (0, "Levis", 0), (2, "levis", 0), (6, "lēvis", 0), (8, "levis", 2), (10, "jacēre", 0), (12, "jacere", 0)]


def test_only_the_macronizations_that_the_certain_occurrences_agree_on_are_unambiguous(carmen):
    assert _rows(carmen / "unambiguous_macronizations.csv") == [
        (",", ","), (".", "."), ("est", "est"), ("et", "et"), ("jam", "jam")]


def test_a_request_to_the_macronizer_that_fails_raises_and_writes_nothing(monkeypatch, tmp_path):
    _morpheus(monkeypatch, _CARMEN_ANALYSES)
    process_work.determine_proper_noun_state.cache_clear()

    def post(url, data, headers, timeout):
        raise requests.exceptions.ConnectionError("No answer from the macronizer")

    monkeypatch.setattr(process_work.requests, "post", post)

    with pytest.raises(requests.exceptions.ConnectionError):
        process_work.process_verse(_CARMEN, tmp_path, _CARMEN_WORK)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("macronized, error", [
    (_CARMEN_MACRONIZED[:-2], "ran out before 'iam'"),
    (_CARMEN_MACRONIZED + [("et", "et", 0)], "returned 1 more results than the text has tokens, from 'et'"),
], ids=["fewer results", "more results"])
def test_macronizer_results_that_dont_match_the_text_raise_and_write_nothing(monkeypatch, tmp_path, macronized, error):
    with pytest.raises(RuntimeError, match=error):
        _process_carmen(monkeypatch, tmp_path, macronized=macronized)
    assert list(tmp_path.iterdir()) == []


_CARMEN_WITH_GAPS = _CARMEN.replace('<l n="2">Est levis, levis.</l>', '<l n="2"><gap reason="lost"/></l>\n'
                                    '    <l n="3">Est levis, levis.</l>').replace(
    '<l n="3">iacere et iacere iam.</l>', '<l n="4">iacere et iacere iam.</l>\n    <l n="5"><gap reason="lost"/></l>')


def test_lost_lines_get_no_macronizer_results(monkeypatch, tmp_path):
    _process_carmen(monkeypatch, tmp_path, xml=_CARMEN_WITH_GAPS)

    assert _rows(tmp_path / "work_macronizations.csv", "workId") == [
        (0, "Levis", 0), (2, "levis", 0), (7, "lēvis", 0), (9, "levis", 2), (11, "jacēre", 0), (13, "jacere", 0)]


def test_a_list_of_words_gets_the_macronizations_of_its_words_and_not_of_the_et_between_them(monkeypatch):
    _macronizer_answers(monkeypatch, [("et", "et", 0), (" ", " ", 0), ("Levis", "Lēvis", 0), (" ", " ", 0),
                                      ("et", "et", 0), (" ", " ", 0), ("Venere", "Venere", 2)])

    assert process_work._get_macronization_data_from_api({"Levis", "Venere"}) == {"Levis": ("Lēvis", 0),
                                                                                      "Venere": ("Venere", 2)}


@pytest.mark.parametrize("words, macronized, error", [
    ({"Levis", "Venere"}, [], "ran out before 'et'"),
    ({"Levis", "Venere"}, [("et", "et", 0), ("Levis", "Lēvis", 0), ("et", "et", 0)], "ran out before 'Venere'"),
    ({"Levis", "Venere"}, [("et", "et", 0), ("Levis", "Lēvis", 0), ("et", "et", 0), ("Venere", "Venere", 0),
                           ("et", "et", 0), ("Roma", "Rōma", 0)],
     "returned 2 more results than the text has tokens, from 'et'"),
    ({"Levis"}, [("Levis", "Lēvis", 0)], "Expected 'et', reconstructed 'Levis'"),
    ({"Levis"}, [("et", "et", 0), ("Levis", "Lēvis", 0), ("et", "et", 0)],
     "returned 1 more results than the text has tokens, from 'et'"),
    ({"Levis"}, [("et", "et", 0), ("Levis", "Lēvis", 0), (".", ".", 0)],
     "returned 1 more results than the text has tokens, from '.'"),
], ids=["no results", "fewer results", "more results", "without the first et", "one more et", "punctuation"])
def test_macronizer_results_for_a_list_of_words_that_dont_match_it_raise(monkeypatch, words, macronized, error):
    _macronizer_answers(monkeypatch, macronized)

    with pytest.raises(RuntimeError, match=error):
        process_work._get_macronization_data_from_api(words)


# A capitalized i ("go!") mid-sentence, which the reader looks up as I before i, and the numeral I
_CARMEN_WITH_I = _CARMEN.replace('</l>\n  </div>', '</l>\n    <l n="4">et I et I.</l>\n  </div>')
_CARMEN_WITH_I_MACRONIZED = _CARMEN_MACRONIZED + [("et", "et", 0), ("I", "Ī", 0), ("et", "et", 0), ("I", "I", 0),
                                                  (".", ".", 0)]


def test_a_word_whose_own_macronization_comes_before_a_numeral_unambiguous_one_is_covered(monkeypatch, tmp_path):
    _process_carmen(monkeypatch, tmp_path, xml=_CARMEN_WITH_I, macronized=_CARMEN_WITH_I_MACRONIZED,
                    work=_CARMEN_WORK._replace(token_overrides={18: TokenType.NUMERAL}, expansions={18: "ūnus"}))
    errors = []

    process_work.check_macronization_coverage(errors, pd.read_csv(tmp_path / "work_contents.csv"),
                                              pd.read_csv(tmp_path / "work_macronizations.csv"),
                                              pd.read_csv(tmp_path / "unambiguous_macronizations.csv"))

    assert (16, "Ī", 0) in _rows(tmp_path / "work_macronizations.csv", "workId")
    assert ("I", "I") in _rows(tmp_path / "unambiguous_macronizations.csv")
    assert errors == []


@pytest.mark.parametrize("word, token_type, proper_noun_state, keys, errors", [
    ("Roma", TokenType.WORD, ProperNounState.YES, ["roma"],
     ["Found 1 words missing a macronization entry entirely. Examples: 'Roma' (idx 0)"]),
    ("Levis", TokenType.WORD, ProperNounState.NO, ["Levis"],
     ["Found 1 words missing a macronization entry entirely. Examples: 'Levis' (idx 0)"]),
    ("Venere", TokenType.WORD, ProperNounState.EITHER, ["venere"], []),
    ("Fabula", TokenType.WORD, None, ["fabula"], []),
    ("XII", TokenType.NUMERAL, ProperNounState.NO, [], []),
], ids=["a name under the common word's key", "a common word under the name's key", "either under the common word's",
        "unknown under the common word's", "a numeral without any"])
def test_a_word_is_covered_by_the_unambiguous_macronization_that_the_reader_looks_it_up_by(
        word, token_type, proper_noun_state, keys, errors):
    contents = pd.DataFrame({"workId": ["w"], "idx": [0], "word": [word], "tokenType": [int(token_type)],
                             "properNounState": pd.array([proper_noun_state], dtype="Int64")})
    found = []

    process_work.check_macronization_coverage(
        found, contents, pd.DataFrame(columns=["workId", "idx", "macronizedWord", "uncertaintyBitMask"]),
        pd.DataFrame({"word": keys, "macronizedWord": keys}, dtype=str))

    assert found == errors


# The edition skips verse 3, and Morpheus has no analysis for Fictor
_CARMEN_WITH_A_GAP = _CARMEN.replace('<l n="3">iacere et iacere iam.</l>',
                                     '<l n="4">iacere et iacere iam.</l>\n    <l n="5">Fictor est.</l>')
_CARMEN_WITH_A_GAP_MACRONIZED = _CARMEN_MACRONIZED + [("Fictor", "Fictor", 0), ("est", "est", 0), (".", ".", 0)]


def test_verses_numbered_by_the_edition_and_a_word_that_morpheus_doesnt_know_pass_validation(monkeypatch, tmp_path,
                                                                                              caplog):
    _process_carmen(monkeypatch, tmp_path, xml=_CARMEN_WITH_A_GAP, macronized=_CARMEN_WITH_A_GAP_MACRONIZED)

    process_work.validate_csv_files(_CARMEN_WITH_A_GAP, tmp_path, _CARMEN_WORK)

    subdivisions = pd.read_csv(tmp_path / "work_content_subdivisions.csv")
    assert list(subdivisions[subdivisions["typ"] == "VERS"]["cnt"]) == [0, 1, 3, 4]
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []
    assert "'Fictor' at index 15" in caplog.text


def test_a_word_that_morpheus_cant_be_asked_about_raises_instead_of_getting_no_state(monkeypatch, tmp_path):
    def get(url, params, headers, timeout):
        raise requests.exceptions.ConnectionError("No answer from Morpheus")

    monkeypatch.setattr(process_work.requests, "get", get)
    _macronizer_answers(monkeypatch, _CARMEN_MACRONIZED)

    with pytest.raises(requests.exceptions.ConnectionError):
        process_work.process_verse(_CARMEN, tmp_path, _CARMEN_WORK)
    assert list(tmp_path.iterdir()) == []


def _subdivisions(*rows):
    """Returns the subdivisions of one work, each given as (node, typ, cnt, parent)"""
    return pd.DataFrame([("w", *row) for row in rows], columns=["workId", "node", "typ", "cnt", "parent"])


@pytest.mark.parametrize("subdivisions, errors", [
    (_subdivisions(("v1", "VERS", 0, "p"), ("v3", "VERS", 2, "p")), []),
    (_subdivisions(("b1", "BOOK", 0, None), ("b3", "BOOK", 2, None)), []),
    (_subdivisions(("a1", "PARA", 0, "p"), ("a2", "PARA", 0, "p")), []),
    (_subdivisions(("v1", "VERS", 1, "p"), ("v2", "VERS", 1, "p")),
     ["For subs, column 'cnt' in group (workId=w, parent=p, typ=VERS) contains duplicate values."]),
    (_subdivisions(("v1", "VERS", -1, "p")),
     ["For subs, column 'cnt' in group (workId=w, parent=p, typ=VERS) contains values that aren't integers from 0 "
      "up."]),
    (_subdivisions(("v1", "VERS", 0.5, "p")),
     ["For subs, column 'cnt' in group (workId=w, parent=p, typ=VERS) contains values that aren't integers from 0 "
      "up."]),
    (_subdivisions(("v1", "VERS", None, "p")),
     ["For subs, column 'cnt' in group (workId=w, parent=p, typ=VERS) contains values that aren't integers from 0 "
      "up."]),
    (_subdivisions(("b1", "BOOK", 0, None), ("b2", "BOOK", 0, None)),
     ["For subs, column 'cnt' in group (workId=w, parent=nan, typ=BOOK) contains duplicate values."]),
    (_subdivisions(("p1", "POEM", 0, "b"), ("p3", "POEM", 2, "b")),
     ["For subs, column 'cnt' in group (workId=w, parent=b, typ=POEM) does not contain sequential integers starting "
      "from 0."]),
    (_subdivisions(("p1", "PROL", 0, "b"), ("p3", "PROL", 2, "b")),
     ["For subs, column 'cnt' in group (workId=w, parent=b, typ=PROL) does not contain sequential integers starting "
      "from 0."]),
    (_subdivisions(("e1", "EPIL", 0, "b"), ("e3", "EPIL", 2, "b")),
     ["For subs, column 'cnt' in group (workId=w, parent=b, typ=EPIL) does not contain sequential integers starting "
      "from 0."]),
    (_subdivisions(("t1", "TITL", 0, "p"), ("t2", "TITL", 0, "p")), ["Subdivision p has more than one title."]),
    (_subdivisions(("t1", "TITL", 0, "p"), ("t2", "TITL", 1, "p")),
     ["Title t2 isn't numbered 0.", "Subdivision p has more than one title."]),
    (_subdivisions(("t1", "TITL", 1, "p")), ["Title t1 isn't numbered 0."]),
    (_subdivisions(("t1", "TITL", 0, "p1"), ("t2", "TITL", 0, "p2")), []),
    (_subdivisions(("a1", "PARA", 1, "p")), ["Paragraph a1 isn't numbered 0."]),
], ids=["verses that skip a number", "books that skip a number", "two paragraphs of a poem", "a verse number twice",
        "a negative verse number", "a fraction of a verse number", "a verse without a number", "a book number twice",
        "poems that skip a number", "prologues that skip a number", "epilogues that skip a number",
        "two titles of a poem", "two titles of a poem numbered 0 and 1", "a title numbered 1",
        "a title of each poem", "a paragraph numbered 1"])
def test_subdivisions_are_numbered_by_the_edition_or_counted_as_the_script_numbers_them(subdivisions, errors):
    found = []

    process_work.check_subdivision_numbers(found, subdivisions)

    assert found == errors


@pytest.mark.parametrize("word, token_type, proper_noun_state, errors", [
    ("Fictor", TokenType.WORD, None, []),
    ("C.", TokenType.ABBREVIATION, ProperNounState.YES, []),
    ("C.", TokenType.ABBREVIATION, None, ["Found 1 abbreviations whose properNounState isn't 1: 'C.' at index 0"]),
    ("C.", TokenType.ABBREVIATION, ProperNounState.NO,
     ["Found 1 abbreviations whose properNounState isn't 1: 'C.' at index 0"]),
    ("XII", TokenType.NUMERAL, ProperNounState.NO, []),
    ("XII", TokenType.NUMERAL, ProperNounState.YES,
     ["Found 1 numerals whose properNounState isn't 0: 'XII' at index 0"]),
    (".", TokenType.PUNCTUATION, None, []),
    (".", TokenType.PUNCTUATION, ProperNounState.NO,
     ["Found 1 non-word tokens with a properNounState that should be NULL."]),
    ("†", TokenType.EDITORIAL, ProperNounState.YES,
     ["Found 1 non-word tokens with a properNounState that should be NULL."]),
    ("Sex.", TokenType.OTHER, ProperNounState.YES,
     ["Found 1 non-word tokens with a properNounState that should be NULL."]),
], ids=["a word without a state", "an abbreviation", "an abbreviation without a state",
        "an abbreviation as a common word", "a numeral", "a numeral as a name", "punctuation",
        "punctuation with a state", "an editorial mark with a state", "another token with a state"])
def test_abbreviations_numerals_and_other_tokens_have_their_proper_noun_states(word, token_type, proper_noun_state,
                                                                                errors):
    contents = pd.DataFrame({"idx": [0], "word": [word], "tokenType": [int(token_type)],
                             "properNounState": pd.array([proper_noun_state], dtype="Int64")})
    found = []

    process_work.check_proper_noun_states(found, contents)

    assert found == errors


def _publish_carmen(monkeypatch, output_dir, xml=_CARMEN, macronized=_CARMEN_MACRONIZED, work=_CARMEN_WORK):
    _morpheus(monkeypatch, _CARMEN_ANALYSES)
    process_work.determine_proper_noun_state.cache_clear()
    _macronizer_answers(monkeypatch, macronized)
    process_work.publish_work(xml, output_dir, work)


_WORK_FILES = ["author_abbreviations.csv", "authors.csv", "authors_and_works.csv", "unambiguous_macronizations.csv",
               "work_abbreviations.csv", "work_content_subdivisions.csv", "work_content_supplementary.csv",
               "work_contents.csv", "work_macronizations.csv", "works.csv"]


def test_a_work_that_passes_validation_is_published(monkeypatch, tmp_path):
    _publish_carmen(monkeypatch, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == _WORK_FILES
    assert _rows(tmp_path / "work_macronizations.csv", "workId") == [
        (0, "Levis", 0), (2, "levis", 0), (6, "lēvis", 0), (8, "levis", 2), (10, "jacēre", 0), (12, "jacere", 0)]


def test_a_work_gets_the_letters_corrections_author_and_about_texts_of_its_configuration(monkeypatch, tmp_path):
    _process_carmen(monkeypatch, tmp_path, work=_CARMEN_WORK._replace(proper_noun_overrides={0: ProperNounState.YES}))

    assert _rows(tmp_path / "works.csv", "id") == [("Carmen", "An invented work.", "uv", "UV", "i", "I")]
    assert _rows(tmp_path / "authors.csv", "id") == [("Fictor", "An invented poet.", "Zml4dHVyZQ==")]
    assert _rows(tmp_path / "author_abbreviations.csv", "authorId") == [(0, "Fict.")]
    assert pd.read_csv(tmp_path / "work_contents.csv")["properNounState"][0] == ProperNounState.YES


def test_a_work_that_fails_validation_raises_and_leaves_the_published_files_as_they_were(monkeypatch, tmp_path):
    _publish_carmen(monkeypatch, tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    # The numeral has no expansion
    numeral_without_expansion = _CARMEN_WORK._replace(token_overrides={18: TokenType.NUMERAL})

    with pytest.raises(ValueError, match="1 abbreviation/numeral tokens missing an 'expansion'"):
        _publish_carmen(monkeypatch, tmp_path, xml=_CARMEN_WITH_I, macronized=_CARMEN_WITH_I_MACRONIZED,
                        work=numeral_without_expansion)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
