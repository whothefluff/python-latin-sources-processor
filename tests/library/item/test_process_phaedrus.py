import pandas as pd
import pytest
import requests

from scripts.library.item import process_phaedrus
from scripts.library.util.proper_noun import ProperNounState


def _answers(monkeypatch, enclitics):
    """Makes Morpheus answer each word in enclitics with that enclitic, and any other word with no analysis."""
    monkeypatch.setattr(process_phaedrus, "_analyze_word_with_clitic",
                        lambda word: process_phaedrus.MorpheusAnswer([word] if word in enclitics else [],
                                                                     enclitics.get(word), frozenset()))


@pytest.mark.parametrize("word", ["seque", "Seque", "SEQUE"])
def test_find_enclitic_finds_a_common_word_enclitic_in_any_case(monkeypatch, word):
    _answers(monkeypatch, {"seque": "que"})

    assert process_phaedrus.find_enclitic(word) == "que"


@pytest.mark.parametrize("word", ["Caesarque", "caesarque"])
def test_find_enclitic_finds_a_proper_noun_enclitic_in_any_case(monkeypatch, word):
    _answers(monkeypatch, {"Caesarque": "que"})

    assert process_phaedrus.find_enclitic(word) == "que"


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _morpheus_xml(surfaces):
    """Returns a Morpheus answer with one inflection per surface. A surface is a stem, or a stem and a suffix as
    Morpheus writes them, such as ('ob:jurg', 'a_bat')."""
    terms = ''.join(f'<infl><term><stem>{stem}</stem>{f"<suff>{suffix}</suff>" if suffix else ""}</term></infl>'
                    for stem, suffix in ((surface, None) if isinstance(surface, str) else surface
                                         for surface in surfaces))
    return f'<words><word><entry><dict><hdwd>x</hdwd></dict>{terms}</entry></word></words>' if terms else '<words/>'


def _surfaces(monkeypatch, surfaces_by_word):
    """Makes Morpheus answer each word in surfaces_by_word with those surfaces, and any other word with no analysis."""
    def get(url, params, headers, timeout):
        return _Response(_morpheus_xml(surfaces_by_word.get(params['word'], [])))

    process_phaedrus._analyze_word_with_clitic.cache_clear()
    monkeypatch.setattr(process_phaedrus.requests, "get", get)


@pytest.mark.parametrize("word, expected", [("iam", "jam"), ("Iam", "Jam"), ("voluit", "voluit"), ("ait", "ait")])
def test_spelled_with_morpheus_letters_takes_morpheus_j_and_keeps_the_edition_u(monkeypatch, word, expected):
    _surfaces(monkeypatch, {"iam": ["jam"], "voluit": ["voluit", "volvit"], "ait": ["ait"]})

    assert process_phaedrus.spelled_with_morpheus_letters(word) == expected


def test_a_host_that_morpheus_spells_with_j_gets_its_enclitic(monkeypatch):
    _surfaces(monkeypatch, {"iamque": ["jam"]})

    assert (process_phaedrus.find_enclitic("Iamque"), process_phaedrus.spelled_with_morpheus_letters("Iamque")) == ("que", "Jamque")


@pytest.mark.parametrize("stem, suffix, expected", [("ob:jurg", "a_bat", "objurgabat"), ("vi^r", "*", "vir")])
def test_surface_forms_leave_out_the_prefix_and_empty_suffix_marks(stem, suffix, expected):
    assert process_phaedrus._surface_forms(_morpheus_xml([(stem, suffix)])) == {expected}


@pytest.mark.parametrize("word, expected", [("obiurgabat", "objurgabat"), ("Obiurgabat", "Objurgabat")])
def test_a_compound_that_morpheus_spells_with_j_gets_it(monkeypatch, word, expected):
    _surfaces(monkeypatch, {"obiurgabat": [("ob:jurg", "a_bat")]})

    assert process_phaedrus.spelled_with_morpheus_letters(word) == expected


@pytest.mark.parametrize("word, host, expected", [("obiurgatque", ("ob:jurg", "at"), "objurgatque"),
                                                  ("virque", ("vi^r", "*"), "virque")])
def test_a_compound_host_or_a_host_without_a_suffix_gets_its_enclitic(monkeypatch, word, host, expected):
    _surfaces(monkeypatch, {word: [host]})

    assert process_phaedrus.find_enclitic(word) == "que"
    assert process_phaedrus.spelled_with_morpheus_letters(word) == expected


@pytest.mark.parametrize("unreachable", ["musaque", "musa"], ids=["the word", "its host"])
def test_a_request_to_morpheus_that_fails_raises_and_leaves_nothing_cached(monkeypatch, unreachable):
    _surfaces(monkeypatch, {"musa": [("mu^s", "a")]})
    answer = process_phaedrus.requests.get

    def get(url, params, headers, timeout):
        if params['word'] == unreachable:
            raise requests.exceptions.ConnectionError(f"No answer for '{unreachable}'")
        return answer(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(process_phaedrus.requests, "get", get)
    with pytest.raises(requests.exceptions.ConnectionError):
        process_phaedrus.find_enclitic("musaque")
    monkeypatch.setattr(process_phaedrus.requests, "get", answer)

    assert process_phaedrus.find_enclitic("musaque") == "que"


@pytest.mark.parametrize("word, answers, error", [
    ("levis", {"levis": "<words><word>"}, process_phaedrus.ET.ParseError),
    ("levis", {"levis": "<error>unknown engine</error>"}, ValueError),
    ("agedum", {"age": "<words><word>"}, process_phaedrus.ET.ParseError),
], ids=["not XML", "an error", "not XML for a host that dum may follow"])
def test_an_answer_that_is_an_error_or_isnt_xml_raises(monkeypatch, word, answers, error):
    process_phaedrus._analyze_word_with_clitic.cache_clear()
    monkeypatch.setattr(process_phaedrus.requests, "get",
                        lambda url, params, headers, timeout: _Response(answers.get(params['word'], '<words/>')))

    with pytest.raises(error):
        process_phaedrus.find_enclitic(word)


def _morpheus(monkeypatch, answers):
    """Makes Morpheus give each word in answers that answer, and any other word no analysis."""
    monkeypatch.setattr(process_phaedrus, "_analyze_word_with_clitic",
                        lambda word: answers.get(word, process_phaedrus.MorpheusAnswer([], None, frozenset())))


_IOVE = {"iove": process_phaedrus.MorpheusAnswer(["io"], "ve", frozenset({"io"})),
         "Iove": process_phaedrus.MorpheusAnswer(["Juppiter"], None, frozenset({"jove"}))}


def test_a_word_that_morpheus_knows_whole_in_one_case_has_no_enclitic(monkeypatch):
    _morpheus(monkeypatch, _IOVE)

    assert process_phaedrus.find_enclitic("Iove") is None
    assert process_phaedrus.spelled_with_morpheus_letters("Iove") == "Jove"


def test_a_word_that_morpheus_knows_whole_only_as_a_name_is_a_name(monkeypatch):
    _morpheus(monkeypatch, _IOVE)

    assert process_phaedrus.determine_proper_noun_state("Iove", True, False) == (ProperNounState.YES,
                                                                                ProperNounState.YES)


_CARMEN = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title xml:lang="lat">Carmen</title><author>Fictor</author></titleStmt></fileDesc>
  </teiHeader>
  <text><body><div type="textpart" subtype="book" n="1"><div type="textpart" subtype="poem" n="1">
    <l n="1">Levis et levis est.</l>
    <l n="2">Est levis, levis.</l>
    <l n="3">iacere et iacere iam.</l>
  </div></div></body></text>
</TEI>"""
_CARMEN_ANALYSES = {word: process_phaedrus.MorpheusAnswer(lemmas, None, frozenset({surface}))
                    for word, lemmas, surface in [("levis", ["levis"], "levis"), ("et", ["et"], "et"),
                                                  ("est", ["sum"], "est"), ("iacere", ["jaceo", "jacio"], "jacere"),
                                                  ("iam", ["jam"], "jam")]}
# Certain of levis as lĕvis in the first verse and as lēvis in the second, except for the last levis, of iacere as
# jacēre and as jacere, and of iam
_CARMEN_MACRONIZED = [("Levis", "Levis", 0), ("et", "et", 0), ("levis", "levis", 0), ("est", "est", 0), (".", ".", 0),
                      ("Est", "Est", 0), ("levis", "lēvis", 0), (",", ",", 0), ("levis", "levis", 2), (".", ".", 0),
                      ("iacere", "iacēre", 0), ("et", "et", 0), ("iacere", "iacere", 0), ("iam", "iam", 0),
                      (".", ".", 0)]


def _macronizer_answers(monkeypatch, macronized):
    """Makes the macronizer answer any text with macronized, a list of (word, macronized word, mask)."""
    monkeypatch.setattr(process_phaedrus, "macronize_text", lambda text: [
        process_phaedrus.TokenResult(word=word, is_word=word.isalpha(), macronized=macronized, uncertainty_mask=mask,
                                     candidates=[])
        for word, macronized, mask in macronized])


def _process_carmen(monkeypatch, output_dir, xml=_CARMEN, macronized=_CARMEN_MACRONIZED):
    _morpheus(monkeypatch, _CARMEN_ANALYSES)
    process_phaedrus.determine_proper_noun_state.cache_clear()
    _macronizer_answers(monkeypatch, macronized)
    process_phaedrus.process_verse(xml, output_dir)


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
    process_phaedrus.determine_proper_noun_state.cache_clear()

    def post(url, data, headers, timeout):
        raise requests.exceptions.ConnectionError("No answer from the macronizer")

    monkeypatch.setattr(process_phaedrus.requests, "post", post)

    with pytest.raises(requests.exceptions.ConnectionError):
        process_phaedrus.process_verse(_CARMEN, tmp_path)
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

    assert process_phaedrus._get_macronization_data_from_api({"Levis", "Venere"}) == {"Levis": ("Lēvis", 0),
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
        process_phaedrus._get_macronization_data_from_api(words)
