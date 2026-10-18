import os
import re
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.common import publishing
from scripts.common.publishing import UNFINISHED_PUBLICATION, publish
from scripts.morphological_analysis import process_morpheus_perseids_api
from scripts.morphological_analysis.process_morpheus_perseids_api import (
    MorphologicalAnalyzer, Reading, RuledOutReadings, ValidationFailed, WordsWithoutAnalysis,
)


def _verb(stem, suffix, person="3rd"):
    return {"term": {"stem": {"$": stem}, "suff": {"$": suffix}}, "pofs": {"$": "verb"}, "mood": {"$": "indicative"},
            "tense": {"$": "present"}, "voice": {"$": "active"}, "num": {"$": "singular"}, "pers": {"$": person},
            "stemtype": {"$": "conj3"}}


def _body(headword, *inflections):
    return {"rest": {"entry": {"dict": {"hdwd": {"$": headword}, "pofs": {"$": "verb"}}, "infl": list(inflections)}}}


def _answer(*bodies):
    return {"RDF": {"Annotation": {"Body": list(bodies)}} if bodies else {"Annotation": {}}}


class _Response:
    def __init__(self, status_code, analysis):
        self.status_code = status_code
        self.analysis = analysis

    def json(self):
        return self.analysis


# est is analyzed, fictum is unknown to Morpheus, ferunt's analysis has no person, and the others get no analysis
# written
_MORPHEUS = {
    "est": _Response(201, _answer(_body("sum1", _verb("es", "t")))),
    "fictum": _Response(201, _answer()),
    "et": _Response(500, {}),
    "jam": requests.exceptions.ConnectionError("No answer for 'jam'"),
    "sunt": _Response(201, _answer(_body("sum1", _verb("s", "unt")), {"about": "urn:uuid:idm0"})),
    "voluit": _Response(201, _answer(_body("volvo", _verb("volv", "it")))),
    "fuit": _Response(201, {"error": {"$": "Morpheus crashed"}}),
    "ferunt": _Response(201, _answer(_body("fero", _verb("fer", "unt", person="")))),
}


@pytest.fixture
def morpheus(monkeypatch):
    """Returns the words that Morpheus is asked for, in order."""
    asked = []

    def get(url, params, timeout):
        asked.append(params["word"])
        answer = _MORPHEUS.get(params["word"], _Response(201, _answer()))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(process_morpheus_perseids_api.requests, "get", get)
    return asked


def _library(project_root, words):
    work_contents = project_root / "output" / "library" / "work_contents.csv"
    work_contents.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"word": words}).to_csv(work_contents, index=False)


@pytest.fixture
def analyzer(morpheus, tmp_path):
    _library(tmp_path, ["est", "fictum", "et", "jam", "sunt", "voluit", "fuit"])
    return MorphologicalAnalyzer(str(tmp_path))


def test_the_words_without_an_analysis_written_fail_the_run_after_the_last_word(analyzer):
    with pytest.raises(WordsWithoutAnalysis) as raised:
        analyzer.process_words()

    assert raised.value.reasons_by_word == {
        "et": "Morpheus answered 'et' with status 500",
        "jam": "No answer for 'jam'",
        "sunt": "Analysis 1 of 'sunt' has no 'rest'",
        "voluit": "every analysis was dropped",
        "fuit": "Morpheus's answer for 'fuit' has no annotation: {'error': {'$': 'Morpheus crashed'}}",
    }
    assert sorted(map(tuple, pd.read_csv(analyzer.details_file, dtype=str, keep_default_na=False).values)) == [
        ("est", "0", "sum1"), ("fictum", "0", "")]


def test_morpheus_is_given_10_seconds_to_answer(monkeypatch):
    timeouts = []

    def get(url, params, timeout):
        timeouts.append(timeout)
        return _Response(201, _answer())

    monkeypatch.setattr(process_morpheus_perseids_api.requests, "get", get)

    MorphologicalAnalyzer.analyze_word("est")

    assert timeouts == [10]


def _outputs(project_root):
    return {path.name: path.read_bytes() for path in (project_root / "output" / "morphological_analysis").iterdir()}


def test_a_run_adds_the_new_words_analyses_to_the_outputs(morpheus, tmp_path):
    _library(tmp_path, ["est"])
    process_morpheus_perseids_api.analyze(str(tmp_path))
    _library(tmp_path, ["est", "fictum"])
    morpheus.clear()

    process_morpheus_perseids_api.analyze(str(tmp_path))

    assert morpheus == ["fictum", "Fictum"]
    assert sorted(_outputs(tmp_path)) == ["morphological_detail_inflections.csv", "morphological_details.csv"]
    assert sorted(map(tuple, pd.read_csv(tmp_path / "output" / "morphological_analysis" / "morphological_details.csv",
                                         dtype=str, keep_default_na=False).values)) == [
        ("est", "0", "sum1"), ("fictum", "0", "")]


@pytest.mark.parametrize("word, error, message", [
    ("et", WordsWithoutAnalysis, "1 words have no analysis written"),
    ("ferunt", ValueError, "Found 1 issues"),
], ids=["a word without an analysis", "an analysis that fails validation"])
def test_a_run_that_fails_leaves_the_outputs_as_they_were(morpheus, tmp_path, word, error, message):
    _library(tmp_path, ["est"])
    process_morpheus_perseids_api.analyze(str(tmp_path))
    before = _outputs(tmp_path)
    _library(tmp_path, ["est", "fictum", word])

    with pytest.raises(error, match=message):
        process_morpheus_perseids_api.analyze(str(tmp_path))
    assert _outputs(tmp_path) == before


def test_a_library_whose_publication_couldnt_be_undone_isnt_analyzed(monkeypatch, morpheus, tmp_path):
    _library(tmp_path, ["est"])
    process_morpheus_perseids_api.analyze(str(tmp_path))
    before = _outputs(tmp_path)
    # The library has works.csv but not work_contents.csv. A publication of both fails to move works.csv in, and then
    # to remove the work_contents.csv it added: the library is left with the old works.csv and the new contents
    library = tmp_path / "output" / "library"
    (library / "work_contents.csv").unlink()
    (library / "works.csv").write_text("id,name\n", encoding="utf-8")
    _library(tmp_path / "next", ["est", "fictum"])
    (tmp_path / "next" / "output" / "library" / "works.csv").write_text("id,name\nw,Carmen\n", encoding="utf-8")
    rename = os.replace
    unlink = Path.unlink

    def replace(source, target):
        if Path(source).name == ".works.csv.new":
            raise PermissionError(f"{target} is open in another program")
        rename(source, target)

    def unlink_all_but_the_contents(path, missing_ok=False):
        if path == library / "work_contents.csv":
            raise PermissionError(f"{path} is open in another program")
        unlink(path, missing_ok=missing_ok)

    with monkeypatch.context() as failing:
        failing.setattr(publishing.os, "replace", replace)
        failing.setattr(Path, "unlink", unlink_all_but_the_contents)
        with pytest.raises(OSError, match="couldn't be undone"):
            publish(tmp_path / "next" / "output" / "library", library)
    assert sorted(path.name for path in library.iterdir()) == [UNFINISHED_PUBLICATION, "work_contents.csv", "works.csv"]
    morpheus.clear()

    with pytest.raises(FileExistsError, match=re.escape(f"{library / UNFINISHED_PUBLICATION}:\nA publication into "
                                                        f"{library} didn't finish")):
        process_morpheus_perseids_api.analyze(str(tmp_path))
    assert morpheus == []
    assert _outputs(tmp_path) == before


_EXCLAMATION_HERCULES = {"dict": {"hdwd": {"$": "Hercules"}, "pofs": {"$": "exclamation"}},
                         "infl": {"term": {"stem": {"$": "hercu^le_s"}}, "pofs": {"$": "exclamation"},
                                  "stemtype": {"$": "exclam"}, "morph": {"$": "indeclform"}}}
_NOUN_HERCULES = {"dict": {"hdwd": {"$": "Hercules"}, "pofs": {"$": "noun"}, "decl": {"$": "3rd"},
                           "gend": {"$": "masculine"}},
                  "infl": {"term": {"stem": {"$": "Hercul"}, "suff": {"$": "e_s"}}, "pofs": {"$": "noun"},
                           "decl": {"$": "3rd"}, "case": {"$": "nominative"}, "gend": {"$": "masculine"},
                           "num": {"$": "singular"}, "stemtype": {"$": "es_is"}}}


def _written(monkeypatch, tmp_path, word, entries_by_spelling):
    """Returns the items written for word, and each reading's form, item and part of speech, when Morpheus answers
    each spelling with its entries, each body with an id of its own."""
    def get(url, params, timeout):
        entries = entries_by_spelling.get(params["word"], [])
        return _Response(201, _answer(*({"about": f"urn:uuid:{params['word']}{i}", "rest": {"entry": entry}}
                                        for i, entry in enumerate(entries))))

    monkeypatch.setattr(process_morpheus_perseids_api.requests, "get", get)
    _library(tmp_path, [word])
    analyzer = MorphologicalAnalyzer(str(tmp_path))
    analyzer.process_words()
    inflections = pd.read_csv(analyzer.inflections_file, dtype=str, keep_default_na=False)
    return (sorted(map(tuple, pd.read_csv(analyzer.details_file, dtype=str, keep_default_na=False).values)),
            sorted(zip(inflections["form"], inflections["item"], inflections["partOfSpeech"])))


def _items_of(monkeypatch, tmp_path, word, entries_by_spelling):
    """Returns the items written for word when Morpheus answers each spelling with its entries."""
    return _written(monkeypatch, tmp_path, word, entries_by_spelling)[0]


def test_entries_of_the_two_spellings_that_only_share_a_headword_are_both_kept(monkeypatch, tmp_path):
    assert _items_of(monkeypatch, tmp_path, "hercules", {"hercules": [_EXCLAMATION_HERCULES],
                                                         "Hercules": [_NOUN_HERCULES]}) == [
        ("Hercules", "1", "Hercules"), ("hercules", "0", "Hercules")]


def test_an_entry_under_a_headword_that_only_the_capitalized_answer_has_is_kept_whole(monkeypatch, tmp_path):
    # Venere is the ablative of Venus, venere a perfect of venio and a present of venor
    venio = {"dict": {"hdwd": {"$": "venio"}, "pofs": {"$": "verb"}},
             "infl": {"term": {"stem": {"$": "ve_n"}, "suff": {"$": "e_re"}}, "pofs": {"$": "verb"},
                      "mood": {"$": "indicative"}, "num": {"$": "plural"}, "pers": {"$": "3rd"},
                      "tense": {"$": "perfect"}, "voice": {"$": "active"}, "stemtype": {"$": "perfstem"},
                      "morph": {"$": "poetic"}}}
    venor = {"dict": {"hdwd": {"$": "venor"}, "pofs": {"$": "verb"}},
             "infl": {"term": {"stem": {"$": "ve_n"}, "suff": {"$": "e_re"}}, "pofs": {"$": "verb"},
                      "mood": {"$": "subjunctive"}, "num": {"$": "singular"}, "pers": {"$": "2nd"},
                      "tense": {"$": "present"}, "voice": {"$": "passive"}, "stemtype": {"$": "conj1"},
                      "derivtype": {"$": "are_vb"}}}
    venus = {"dict": {"hdwd": {"$": "Venus"}, "pofs": {"$": "noun"}, "decl": {"$": "3rd"}, "gend": {"$": "feminine"}},
             "infl": {"term": {"stem": {"$": "Ve^n"}, "suff": {"$": "ere"}}, "pofs": {"$": "noun"},
                      "decl": {"$": "3rd"}, "case": {"$": "ablative"}, "gend": {"$": "feminine"},
                      "num": {"$": "singular"}, "stemtype": {"$": "us_eris"}}}

    assert _written(monkeypatch, tmp_path, "venere", {"venere": [venio, venor], "Venere": [venus]}) == (
        [("Venere", "2", "Venus"), ("venere", "0", "venio"), ("venere", "1", "venor")],
        [("Venere", "2", "noun"), ("venere", "0", "verb"), ("venere", "1", "verb")])


def test_an_entry_that_both_spellings_give_is_kept_once(monkeypatch, tmp_path):
    assert _items_of(monkeypatch, tmp_path, "hercules", {"hercules": [_NOUN_HERCULES],
                                                         "Hercules": [_NOUN_HERCULES]}) == [
        ("Hercules", "0", "Hercules")]


def test_a_capitalized_headword_gains_only_the_readings_that_the_lowercase_answer_lacks(monkeypatch, tmp_path):
    # Morpheus answers Hercules with one entry that holds the noun and the exclamation that hercules gives
    noun_and_exclamation = dict(_NOUN_HERCULES, infl=[_NOUN_HERCULES["infl"], _EXCLAMATION_HERCULES["infl"]])

    assert _written(monkeypatch, tmp_path, "hercules", {"hercules": [_EXCLAMATION_HERCULES],
                                                        "Hercules": [noun_and_exclamation]}) == (
        [("Hercules", "1", "Hercules"), ("hercules", "0", "Hercules")],
        [("Hercules", "1", "noun"), ("hercules", "0", "interjection")])


def test_a_lowercase_headword_has_only_the_readings_of_the_lowercase_answer(monkeypatch, tmp_path):
    adjective = {"term": {"stem": {"$": "nov"}, "suff": {"$": "ae"}}, "pofs": {"$": "adjective"},
                 "decl": {"$": "1st & 2nd"}, "case": {"$": "nominative"}, "gend": {"$": "feminine"},
                 "num": {"$": "plural"}, "stemtype": {"$": "us_a_um"}}
    shops = {"term": {"stem": {"$": "Nov"}, "suff": {"$": "ae"}}, "pofs": {"$": "noun"}, "decl": {"$": "1st"},
             "case": {"$": "nominative"}, "gend": {"$": "feminine"}, "num": {"$": "plural"},
             "stemtype": {"$": "a_ae"}}
    novus = {"dict": {"hdwd": {"$": "novus"}, "pofs": {"$": "adjective"}}, "infl": adjective}

    assert _items_of(monkeypatch, tmp_path, "novae", {
        "novae": [novus],
        "Novae": [{"dict": {"hdwd": {"$": "novus"}, "pofs": {"$": "noun"}}, "infl": [adjective, shops]}]}) == [
        ("novae", "0", "novus")]


def _library_of_one_certain_est(project_root):
    """Writes a library of one token, est, whose macronization ēst is certain."""
    library = project_root / "output" / "library"
    library.mkdir(parents=True)
    pd.DataFrame({"workId": ["w"], "idx": [0], "word": ["est"], "sourceReference": ["1.1"], "properNounState": [0],
                  "tokenType": [1], "enclitic": [""], "expansion": [""]}).to_csv(library / "work_contents.csv",
                                                                                  index=False)
    (library / "works.csv").write_text("id,name\nw,Carmen\n", encoding="utf-8")
    (library / "unambiguous_macronizations.csv").write_text("word,macronizedWord\nest,ēst\n", encoding="utf-8")
    (library / "work_macronizations.csv").write_text("workId,idx,macronizedWord,uncertaintyBitMask\n",
                                                     encoding="utf-8")


def test_a_run_logs_the_readings_that_certain_vowels_rule_out(morpheus, tmp_path, caplog):
    _library_of_one_certain_est(tmp_path)

    with caplog.at_level("INFO"):
        process_morpheus_perseids_api.analyze(str(tmp_path))

    assert [record.getMessage() for record in caplog.records][-4:] == [
        "1 word tokens have certain vowels that rule out every reading, by their macronization",
        "  ēst: 1, such as Carmen 1.1",
        "1 readings are ruled out by the certain vowels of some tokens, by their spelling and lemma",
        "  est (sum1): 1, such as Carmen 1.1",
    ]


def test_the_log_lists_the_most_tokens_first_with_three_places_each(monkeypatch, morpheus, tmp_path, caplog):
    _library_of_one_certain_est(tmp_path)
    many = ["Carmen 1.1", "Carmen 1.1", "Carmen 1.2", "Carmen 1.3", "Carmen 1.4"]
    monkeypatch.setattr(process_morpheus_perseids_api, "readings_ruled_out_by_certain_vowels",
                        lambda *_: RuledOutReadings({"mihi": ["Carmen 1.1"], "ego": ["Carmen 1.2"], "tibi": many},
                                                    {Reading("tibī", "tu"): many}))

    with caplog.at_level("INFO"):
        process_morpheus_perseids_api.analyze(str(tmp_path))

    assert [record.getMessage() for record in caplog.records][-6:] == [
        "7 word tokens have certain vowels that rule out every reading, by their macronization",
        "  tibi: 5, such as Carmen 1.1, Carmen 1.2, Carmen 1.3",
        "  ego: 1, such as Carmen 1.2",
        "  mihi: 1, such as Carmen 1.1",
        "1 readings are ruled out by the certain vowels of some tokens, by their spelling and lemma",
        "  tibī (tu): 5, such as Carmen 1.1, Carmen 1.2, Carmen 1.3",
    ]


@pytest.mark.parametrize("failure, message", [
    (ValidationFailed(1), "Nothing was saved: validation found 1 issues, listed above. Their line numbers are of the "
                          "files that weren't kept. The output files are as they were."),
    (WordsWithoutAnalysis({"et": "Morpheus answered 'et' with status 500"}),
     "Nothing was saved: 1 words have no analysis written: 'et' (Morpheus answered 'et' with status 500). The output "
     "files are as they were."),
], ids=["analyses that fail validation", "a word without an analysis"])
def test_a_run_that_fails_on_the_data_says_why_without_a_traceback(monkeypatch, caplog, failure, message):
    def analyze(_project_root):
        raise failure

    monkeypatch.setattr(process_morpheus_perseids_api, "analyze", analyze)

    with pytest.raises(SystemExit) as exited:
        process_morpheus_perseids_api.main()

    assert exited.value.code == 1
    assert [(record.levelname, record.getMessage(), record.exc_info) for record in caplog.records] == [
        ("ERROR", message, None)]


def test_a_run_that_fails_on_the_code_shows_its_traceback(monkeypatch):
    def analyze(_project_root):
        raise KeyError("rest")

    monkeypatch.setattr(process_morpheus_perseids_api, "analyze", analyze)

    with pytest.raises(KeyError, match="rest"):
        process_morpheus_perseids_api.main()
