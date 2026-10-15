import pytest

from scripts.morphological_analysis import process_morpheus_perseids_api
from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer


def _verb(stem, suffix):
    return {"term": {"stem": {"$": stem}, "suff": {"$": suffix}}, "pofs": {"$": "verb"}, "mood": {"$": "indicative"},
            "tense": {"$": "perfect"}, "voice": {"$": "active"}, "num": {"$": "singular"}, "pers": {"$": "3rd"},
            "stemtype": {"$": "perfstem"}}


def _analysis(*bodies):
    """Returns Morpheus's JSON with one body for each pair of headword and inflections."""
    return {"RDF": {"Annotation": {"Body": [
        {"rest": {"entry": {"dict": {"hdwd": {"$": headword}, "pofs": {"$": "verb"}}, "infl": inflections}}}
        for headword, inflections in bodies
    ]}}}


def _process(word, *bodies, **kwargs):
    details, inflections = MorphologicalAnalyzer.process_analysis(word, _analysis(*bodies), **kwargs)
    return ([(d["item"], d["dictionaryRef"]) for d in details],
            [(i["item"], i["cnt"], i["stem"] + (i["suffix"] or "")) for i in inflections])


def test_an_analysis_spelled_with_other_letters_is_dropped_before_items_are_numbered():
    assert _process("voluit", ("volvo", [_verb("volv", "it")]), ("volo1", [_verb("volu", "it")])) == (
        [(0, "volo1")], [(0, 0, "voluit")])


def test_only_the_inflections_spelled_with_other_letters_are_dropped():
    assert _process("voluit", ("volo1", [_verb("volv", "it"), _verb("volu", "it")])) == (
        [(0, "volo1")], [(0, 0, "voluit")])


def test_an_analysis_without_an_enclitic_is_compared_with_the_host():
    assert _process("jubetque", ("jubeo", [_verb("jub", "et")]), ("iubeo", [_verb("iub", "et")])) == (
        [(0, "jubeo")], [(0, 0, "jubet")])


def test_the_longest_omitted_tail_finds_the_host():
    assert _process("qualecumque", ("qualis", [_verb("qual", "e")])) == ([(0, "qualis")], [(0, 0, "quale")])


def test_an_analysis_that_doesnt_line_up_is_kept(caplog):
    assert _process("elapsum", ("elabor", [_verb("ex-la_ps", "um")])) == ([(0, "elabor")], [(0, 0, "ex-lāpsum")])
    assert "elapsum" in caplog.text


def test_letters_are_compared_with_the_word_morpheus_was_asked_for():
    assert _process("uoluit", ("volvo", [_verb("volv", "it")]), analyzed_as="volvit") == (
        [(0, "volvo")], [(0, 0, "volvit")])


@pytest.mark.parametrize("malformed", [{}, {"rest": {"entry": {"infl": _verb("volu", "it")}}},
                                       {"rest": {"entry": {"dict": {"pofs": {"$": "verb"}}}}}],
                         ids=["no entry", "no dictionary entry", "no headword"])
def test_an_analysis_without_a_headword_raises(malformed):
    analysis = _analysis(("volo1", [_verb("volu", "it")]))
    analysis["RDF"]["Annotation"]["Body"].append(malformed)

    with pytest.raises(ValueError, match="Analysis 1 of 'voluit'"):
        MorphologicalAnalyzer.process_analysis("voluit", analysis)


@pytest.mark.parametrize("override, ignored", [("FORMS_TO_IGNORE", {"voluit_0"}), ("IGNORED_DICT_REFS", {"volvo"})],
                         ids=["the word's first analysis", "the dictionary entry"])
def test_an_analysis_that_the_overrides_ignore_is_dropped_without_failing(monkeypatch, override, ignored):
    monkeypatch.setattr(process_morpheus_perseids_api, override, ignored)

    assert _process("voluit", ("volvo", [_verb("volu", "it")]), ("volo1", [_verb("volu", "it")])) == (
        [(0, "volo1")], [(0, 0, "voluit")])
