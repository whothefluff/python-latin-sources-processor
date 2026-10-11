import pytest

from scripts.library.item import process_phaedrus


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


def _surfaces(monkeypatch, surfaces_by_word):
    """Makes Morpheus answer each word in surfaces_by_word with those surfaces, and any other word with no analysis."""
    def get(url, params, headers, timeout):
        terms = ''.join(f'<infl><term><stem>{surface}</stem></term></infl>'
                        for surface in surfaces_by_word.get(params['word'], []))
        return _Response(f'<words><word><entry><dict><hdwd>x</hdwd></dict>{terms}</entry></word></words>'
                         if terms else '<words/>')

    process_phaedrus._analyze_word_with_clitic.cache_clear()
    monkeypatch.setattr(process_phaedrus.requests, "get", get)


@pytest.mark.parametrize("word, expected", [("iam", "jam"), ("Iam", "Jam"), ("voluit", "voluit"), ("ait", "ait")])
def test_spelled_with_morpheus_letters_takes_morpheus_j_and_keeps_the_edition_u(monkeypatch, word, expected):
    _surfaces(monkeypatch, {"iam": ["jam"], "voluit": ["voluit", "volvit"], "ait": ["ait"]})

    assert process_phaedrus.spelled_with_morpheus_letters(word) == expected


def test_a_host_that_morpheus_spells_with_j_gets_its_enclitic(monkeypatch):
    _surfaces(monkeypatch, {"iamque": ["jam"]})

    assert (process_phaedrus.find_enclitic("Iamque"), process_phaedrus.spelled_with_morpheus_letters("Iamque")) == ("que", "Jamque")
