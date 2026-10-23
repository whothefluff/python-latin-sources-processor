import re

import pytest

from scripts.morphological_analysis import process_morpheus_perseids_api
from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer, RulesThatChangeNothing
from scripts.morphological_analysis.process_morpheus_perseids_api_aux.overrides import ReadingRule, check_rules


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


@pytest.mark.parametrize("ignored, kept", [
    ({"volvo": frozenset({"voluit"})}, [(0, "volo1")]), ({"volvo": frozenset()}, [(0, "volo1")]),
    ({"volvo": frozenset({"volvit"})}, [(0, "volvo"), (1, "volo1")]),
], ids=["for the word", "for every word", "for another word"])
def test_an_analysis_that_the_overrides_ignore_is_dropped_without_failing(monkeypatch, ignored, kept):
    monkeypatch.setattr(process_morpheus_perseids_api, "IGNORED_DICT_REFS", ignored)

    assert _process("voluit", ("volvo", [_verb("volu", "it")]), ("volo1", [_verb("volu", "it")]))[0] == kept


@pytest.mark.parametrize("notation, spellings", [
    ("a_mo^", ["āmo"]), ("gy_r", ["gȳr"]), ("tibi_^", ["tibi", "tibī"]), ("i^bi^_", ["ibi", "ibī"]),
    ("A_^s", ["As", "Ās"]), ("pa_^tr", ["patr"]), ("sa^_cr", ["sacr"]), ("ca^the_^dr", ["cathedr"]),
    ("Thre_i+ss", ["Thrēiss"]),
], ids=["long and short", "long y", "common", "common written ^_", "capital", "common before a mute and a liquid",
        "the same written ^_", "the same after a short vowel", "diaeresis"])
def test_morpheus_notation_gives_long_vowels_macrons_and_common_ones_both_spellings(notation, spellings):
    assert MorphologicalAnalyzer.spellings(notation) == spellings


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


_TIBI = ("tu", "pronoun", [_inflection("pronoun", "tibi_^", None, "pron2", case="dative", gend=gender,
                                       num="singular", morph="indeclform") for gender in ("masculine", "feminine")])


def test_a_common_vowel_gives_each_inflection_both_spellings():
    _, inflections = MorphologicalAnalyzer.process_analysis("tibi", _entries(_TIBI))

    assert [(i["cnt"], i["stem"], i["gender"]) for i in inflections] == [
        (0, "tibi", "masculine"), (1, "tibī", "masculine"), (2, "tibi", "feminine"), (3, "tibī", "feminine")]


def test_a_rule_that_drops_a_reading_drops_all_its_spellings(monkeypatch):
    monkeypatch.setattr(process_morpheus_perseids_api, "FORMS", (
        ReadingRule(headword="tu", match={"gend": "feminine"}, changes=None, words=frozenset({"tibi"})),))

    _, inflections = MorphologicalAnalyzer.process_analysis("tibi", _entries(_TIBI))

    assert [(i["cnt"], i["stem"], i["gender"]) for i in inflections] == [
        (0, "tibi", "masculine"), (1, "tibī", "masculine")]


@pytest.mark.parametrize("stems, spellings", [
    (["tibi_", "tibi_^"], ["tibī"]), (["tibi_^", "tibi_"], ["tibi", "tibī"]),
    (["tibi_^", "ti:bi_"], ["ti-bī"]), (["tibi_", "ti:bi_^"], ["ti-bi", "ti-bī"]),
], ids=["long first", "common first", "a hyphenated long one after a common one",
        "a hyphenated common one after a long one"])
def test_a_reading_with_the_grammar_of_one_before_is_dropped_with_all_its_spellings(stems, spellings):
    # As Morpheus gives one inflection twice, but for its stem's notation; the hyphenated stem is kept
    tibi = ("tu", "pronoun", [_inflection("pronoun", stem, None, "pron2", case="dative", gend="masculine",
                                          num="singular", morph="indeclform") for stem in stems])

    _, inflections = MorphologicalAnalyzer.process_analysis("tibi", _entries(tibi))

    assert [(i["cnt"], i["stem"]) for i in inflections] == list(enumerate(spellings))


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
    monkeypatch.setattr(process_morpheus_perseids_api, "FORMS", (ReadingRule(
        headword="Hercules", match={"pofs": "exclamation"}, changes={"partOfSpeech": "noun"},
        words=frozenset({"hercle"})),))

    details, _ = MorphologicalAnalyzer.process_analysis("hercle", _entries(_HERCLE))

    assert _items(details) == [("Hercle", 0, "Hercules")]


def test_an_excluded_adjective_inflection_does_not_capitalize_the_item(monkeypatch):
    monkeypatch.setattr(process_morpheus_perseids_api, "FORMS", (
        ReadingRule(headword="Atticus", match={"pofs": "adjective"}, changes=None, words=frozenset({"attice"})),))

    details, inflections = MorphologicalAnalyzer.process_analysis(
        "attice", _entries(("Atticus", "adjective", [_ATTICUS, _ATTICE])))

    assert _items(details) == [("attice", 0, "Atticus")]
    assert [i["partOfSpeech"] for i in inflections] == ["adverb"]



_SATIS_READINGS = [_inflection("adverb", "satis", None, "adverb", morph="indeclform"),
                   _inflection("irregular", "satis", None, "indecl", gend="neuter", morph="indeclform")]
_SATIN_READINGS = [_inflection("adverb", "sa^ti^n", None, "adverb", morph="indeclform"),
                   _inflection("irregular", "sa^ti^n", None, "indecl", gend="neuter", morph="indeclform")]
_SATA = ("sata", "noun", [_inflection("noun", "sa^t", "i_s", "us_i", case="dative", gend="neuter", num="plural")])


@pytest.mark.parametrize("word, entries, item", [
    ("satis", (_SATA, ("satis", "adverb", _SATIS_READINGS)), 1), ("satin", (("satis", "adverb", _SATIN_READINGS),), 0),
    ("satisque", (("satis", "adverb", _SATIS_READINGS),), 0),
], ids=["satis", "satin, its -ne cut short", "satisque, answered with satis's readings"])
def test_the_indeclinable_satis_is_an_adjective_without_gender(word, entries, item):
    details, inflections = MorphologicalAnalyzer.process_analysis(word, _entries(*entries))

    assert _items(details)[item] == (word, item, "satis")
    assert [(i["partOfSpeech"], i["gender"]) for i in inflections if i["item"] == item] == [
        ("adverb", None), ("adjective", None)]


def _satis_readings(monkeypatch, *rules):
    """Returns the part of speech and gender of satis's two readings under the rules given."""
    monkeypatch.setattr(process_morpheus_perseids_api, "FORMS", rules)
    _, inflections = MorphologicalAnalyzer.process_analysis("satis", _entries(("satis", "adverb", _SATIS_READINGS)))
    return [(i["partOfSpeech"], i["gender"]) for i in inflections]


_ADJECTIVE = {"partOfSpeech": "adjective", "gender": None}


@pytest.mark.parametrize("rule", [
    ReadingRule(headword="satum", match={"stemtype": "indecl"}, changes=_ADJECTIVE),
    ReadingRule(headword="satis", match={"stemtype": "indecl", "gend": "feminine"}, changes=_ADJECTIVE),
    ReadingRule(headword="satis", match={"stemtype": "indecl"}, changes=_ADJECTIVE, words=frozenset({"satin"})),
], ids=["another headword", "another value", "another word"])
def test_a_rule_changes_only_the_readings_of_its_headword_with_its_values_in_its_words(monkeypatch, rule):
    assert _satis_readings(monkeypatch, rule) == [("adverb", None), ("noun", "neuter")]


def test_a_word_that_none_of_its_readings_has_a_rule_for_raises(monkeypatch):
    monkeypatch.setattr(process_morpheus_perseids_api, "FORMS", (ReadingRule(
        headword="volo1", match={"tense": "present"}, changes={"person": "1st"}, words=frozenset({"voluit"})),))

    with pytest.raises(RulesThatChangeNothing, match=re.escape(
            "Rules in FORMS change nothing for 'voluit': volo1 {'tense': 'present'}: none of the word's readings has")):
        _process("voluit", ("volo1", [_verb("volu", "it")]))


@pytest.mark.parametrize("changes, field", [
    ({"partOfSpeech": "adjective", "gender": None, "segmentsInfo": "indeclinable"}, "segmentsInfo"),
    ({"partOfSpeech": "adjective", "number": [None]}, "number"),
], ids=["a value the script gives", "a list of only that value"])
def test_a_rule_that_sets_a_field_to_the_value_it_has_already_raises(monkeypatch, changes, field):
    with pytest.raises(RulesThatChangeNothing, match=re.escape(f"every reading it matches has its {field} already")):
        _satis_readings(monkeypatch, ReadingRule(headword="satis", match={"stemtype": "indecl"}, changes=changes))


def test_a_rule_whose_readings_are_the_ones_the_word_has_already_raises(monkeypatch):
    # The masculine dative made masculine and feminine, as the feminine one is already
    monkeypatch.setattr(process_morpheus_perseids_api, "FORMS", (ReadingRule(
        headword="tu", match={"gend": "masculine"}, changes={"gender": ["masculine", "feminine"]},
        words=frozenset({"tibi"})),))

    with pytest.raises(RulesThatChangeNothing,
                       match=re.escape("tu {'gend': 'masculine'}: it changes none of the word's readings")):
        MorphologicalAnalyzer.process_analysis("tibi", _entries(_TIBI))


def test_a_reading_that_two_rules_are_for_raises(monkeypatch):
    with pytest.raises(ValueError, match="an inflection of satis has 2 rules in FORMS"):
        _satis_readings(monkeypatch, ReadingRule(headword="satis", match={"stemtype": "indecl"}, changes=_ADJECTIVE),
                        ReadingRule(headword="satis", match={"pofs": "irregular"}, changes={"gender": None}))


@pytest.mark.parametrize("rule, unknown", [
    (ReadingRule(headword="satis", match={"gender": "neuter"}, changes=_ADJECTIVE), "['gender']"),
    (ReadingRule(headword="satis", match={"gend": "neuter"}, changes={"gend": None}), "['gend']"),
], ids=["a match by an output field", "a change to one of Morpheus's elements"])
def test_a_rule_with_an_element_or_field_that_no_inflection_has_is_refused(rule, unknown):
    with pytest.raises(ValueError, match=re.escape(f"has elements or fields that no inflection has: {unknown}")):
        check_rules([rule])


def test_a_rule_that_changes_no_field_is_refused():
    with pytest.raises(ValueError, match="changes no field; a rule that drops a reading has changes None"):
        check_rules([ReadingRule(headword="satis", match={"stemtype": "indecl"}, changes={})])


def test_an_inflection_whose_part_of_speech_has_no_rule_in_its_entry_says_which(caplog):
    MorphologicalAnalyzer.process_analysis("hercules", _entries(
        ("Hercules", "noun", [_inflection("exclamation", "hercu^le_s")])))

    assert ("'hercules': inflection 0 of Hercules (hercules) is 'exclamation' in an entry that is 'noun', a pair that "
            "part_of_speech has no rule for") in caplog.text

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
