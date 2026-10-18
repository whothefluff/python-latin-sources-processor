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


def _inflection(pos, stem, suffix=None, stemtype="", **tags):
    """Returns one of Morpheus's inflections, with its part of speech, stem, suffix and other tags."""
    term = {"stem": {"$": stem}} | ({"suff": {"$": suffix}} if suffix else {})
    return {"term": term, "pofs": {"$": pos}, "stemtype": {"$": stemtype}} | {
        tag: {"$": value} for tag, value in tags.items()}


def _entries(*entries):
    """Returns Morpheus's JSON with one body for each headword, part of speech and inflections."""
    return {"RDF": {"Annotation": {"Body": [
        {"rest": {"entry": {"dict": {"hdwd": {"$": headword}, "pofs": {"$": pos}}, "infl": inflections}}}
        for headword, pos, inflections in entries
    ]}}}


_ATTICUS = _inflection("adjective", "Attic", "us", "us_a_um", gend="masculine", num="singular", case="nominative",
                       decl="1st & 2nd")
_ATTICE = _inflection("adverb", "Attic", "e_")
_HERCLE = ("Hercules", "exclamation", [_inflection("exclamation", "hercle")])


def _items(details):
    return [(detail["form"], detail["item"], detail["dictionaryRef"]) for detail in details]


def _readings(inflections):
    return [(i["form"], i["item"], i["cnt"], i["partOfSpeech"], i["stem"] + (i["suffix"] or ""), i["case"])
            for i in inflections]


def test_a_proper_adjective_is_capitalized_and_stays_an_adjective():
    details, inflections = MorphologicalAnalyzer.process_analysis(
        "atticus", _entries(("Atticus", "adjective", [_ATTICUS])))

    assert _items(details) == [("Atticus", 0, "Atticus")]
    assert _readings(inflections) == [("Atticus", 0, 0, "adjective", "Atticus", "nominative")]


def test_an_interjection_whose_headword_is_a_name_stays_lowercase():
    details, _ = MorphologicalAnalyzer.process_analysis("hercle", _entries(_HERCLE))

    assert _items(details) == [("hercle", 0, "Hercules")]


def test_an_override_that_makes_an_inflection_a_noun_capitalizes_the_item(monkeypatch):
    monkeypatch.setitem(process_morpheus_perseids_api.FORMS, "hercle_0_0", {"partOfSpeech": "noun"})

    details, _ = MorphologicalAnalyzer.process_analysis("hercle", _entries(_HERCLE))

    assert _items(details) == [("Hercle", 0, "Hercules")]


def test_an_excluded_adjective_inflection_does_not_capitalize_the_item(monkeypatch):
    monkeypatch.setitem(process_morpheus_perseids_api.NOT_WANTED_INFLECTIONS, "attice_0_0", True)

    details, inflections = MorphologicalAnalyzer.process_analysis(
        "attice", _entries(("Atticus", "adjective", [_ATTICUS, _ATTICE])))

    assert _items(details) == [("attice", 0, "Atticus")]
    assert [i["partOfSpeech"] for i in inflections] == ["adverb"]


def _degrees(word, *entries):
    """Returns each reading's form, part of speech, spelling, declension and segments."""
    _, inflections = MorphologicalAnalyzer.process_analysis(word, _entries(*entries))
    return [(i["form"], i["partOfSpeech"], i["stem"] + (i["suffix"] or ""), i["declension"], i["segmentsInfo"])
            for i in inflections]


def _singular(case, gend, **tags):
    return dict(case=case, gend=gend, num="singular", **tags)


def test_a_comparative_built_on_its_positives_stem_is_of_the_3rd_declension():
    assert _degrees("firmiores", ("firmus", "adjective", [
        _inflection("adjective", "firm", "io_re_s", "us_a_um", case="nominative", gend="masculine", num="plural",
                    decl="1st & 2nd", comp="comparative")])) == [
        ("firmiores", "adjective", "firmiōrēs", "3rd", "ior, -ius")]


def test_a_comparative_with_a_stem_of_its_own_keeps_its_stem_types_segments():
    assert _degrees("melior", ("bonus", "adjective", [
        _inflection("adjective", "me^li^", "or", "or_us_comp", **_singular("nominative", "masculine"), decl="3rd",
                    comp="comparative")])) == [
        ("melior", "adjective", "melior", "3rd", "or, -us")]


def test_a_comparative_that_morpheus_calls_a_noun_is_a_comparative_too():
    assert _degrees("doctior", ("doceo", "noun", [
        _inflection("noun", "do^ct", "ior", "pp4", **_singular("nominative", "masculine"), comp="comparative")])) == [
        ("doctior", "noun", "doctior", "3rd", "ior, -ius")]


def test_a_neuter_comparative_in_ius_is_a_comparative():
    assert _degrees("citius", ("cieo", "noun", [
        _inflection("noun", "ci^t", "ius", "pp4", gend="adverbial", comp="comparative"),
        _inflection("noun", "ci^t", "ius", "pp4", **_singular("nominative", "neuter"), comp="comparative")])) == [
        ("citius", "adverb", "citius", None, None),
        ("citius", "noun", "citius", "3rd", "ior, -ius")]


def test_a_word_in_ius_that_is_no_comparative_keeps_its_declension_and_segments():
    assert _degrees("filius", ("filius", "noun", [
        _inflection("noun", "fi_l", "ius", "ius_i", **_singular("nominative", "masculine"), decl="2nd")])) == [
        ("filius", "noun", "fīlius", "2nd", "ius, -i")]
    assert _degrees("cybeleius", ("Cybele", "adjective", [
        _inflection("adjective", "Cy^be^le_", "ius", "ius_ia_ium", **_singular("nominative", "masculine"),
                    decl="1st & 2nd")])) == [
        ("Cybeleius", "adjective", "Cybelēius", "1st & 2nd", "ius, -ia, -ium")]


def test_a_genitive_plural_in_iorum_is_no_comparative():
    assert _degrees("aliorum", ("allium", "noun", [
        _inflection("noun", "ali", "o_rum", "us_i", case="genitive", gend="neuter", num="plural", decl="2nd")])) == [
        ("aliorum", "noun", "aliōrum", "2nd", "us, -i")]


def test_a_superlative_is_of_the_1st_and_2nd_declensions_with_its_endings_segments():
    assert _degrees("fortissimus", ("fortis", "adjective", [
        _inflection("adjective", "fort", "issimus", "is_e", **_singular("nominative", "masculine"), decl="3rd",
                    comp="superlative")])) == [
        ("fortissimus", "adjective", "fortissimus", "1st & 2nd", "issimus, -issima, -issimum")]
    assert _degrees("pulcherrime", ("pulcher1", "adjective", [
        _inflection("adjective", "pulch", "errime", "er_ra_rum", **_singular("vocative", "masculine"),
                    decl="1st & 2nd", comp="superlative")])) == [
        ("pulcherrime", "adjective", "pulcherrime", "1st & 2nd", "errimus, -errima, -errimum")]
    assert _degrees("carissumus", ("carus", "adjective", [
        _inflection("adjective", "ca_r", "issumus", "us_a_um", **_singular("nominative", "masculine"),
                    decl="1st & 2nd", comp="superlative")])) == [
        ("carissumus", "adjective", "cārissumus", "1st & 2nd", "issumus, -issuma, -issumum")]


def test_a_superlative_with_a_stem_of_its_own_keeps_its_stem_types_segments():
    assert _degrees("optimus", ("bonus", "adjective", [
        _inflection("adjective", "o^pti^m", "us", "us_a_um", **_singular("nominative", "masculine"), decl="1st & 2nd",
                    comp="superlative")])) == [
        ("optimus", "adjective", "optimus", "1st & 2nd", "us, -a, -um")]
