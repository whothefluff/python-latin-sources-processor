import os
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.common import publishing
from scripts.common.publishing import UNFINISHED_PUBLICATION, publish
from scripts.morphological_analysis import process_morpheus_perseids_api
from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer, WordsWithoutAnalysis


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

    with pytest.raises(FileExistsError,
                       match=rf"{UNFINISHED_PUBLICATION}:\nA publication into {library} didn't finish"):
        process_morpheus_perseids_api.analyze(str(tmp_path))
    assert morpheus == []
    assert _outputs(tmp_path) == before
