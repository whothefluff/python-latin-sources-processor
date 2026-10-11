import pytest
from scripts.library.item import process_phaedrus


def _answers(monkeypatch, enclitics):
    """Morpheus's answers by the exact word queried (strictCase): its enclitic, or no analysis"""
    monkeypatch.setattr(process_phaedrus, "_analyze_word_with_clitic",
                        lambda word: ([word] if word in enclitics else [], enclitics.get(word)))


@pytest.mark.parametrize("word", ["seque", "Seque", "SEQUE"])
def test_find_enclitic_finds_a_common_word_enclitic_in_any_case(monkeypatch, word):
    _answers(monkeypatch, {"seque": "que"})

    assert process_phaedrus.find_enclitic(word) == "que"


@pytest.mark.parametrize("word", ["Caesarque", "caesarque"])
def test_find_enclitic_finds_a_proper_noun_enclitic_in_any_case(monkeypatch, word):
    _answers(monkeypatch, {"Caesarque": "que"})

    assert process_phaedrus.find_enclitic(word) == "que"
