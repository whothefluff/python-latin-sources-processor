import pandas as pd
import pytest
import requests

from scripts.morphological_analysis import process_morpheus_perseids_api
from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer, WordsWithoutAnalysis


def _verb(stem, suffix):
    return {"term": {"stem": {"$": stem}, "suff": {"$": suffix}}, "pofs": {"$": "verb"}, "mood": {"$": "indicative"},
            "tense": {"$": "present"}, "voice": {"$": "active"}, "num": {"$": "singular"}, "pers": {"$": "3rd"},
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


# est is analyzed, fictum is unknown to Morpheus, and the others get no analysis written
_MORPHEUS = {
    "est": _Response(201, _answer(_body("sum1", _verb("es", "t")))),
    "fictum": _Response(201, _answer()),
    "et": _Response(500, {}),
    "jam": requests.exceptions.ConnectionError("No answer for 'jam'"),
    "sunt": _Response(201, _answer(_body("sum1", _verb("s", "unt")), {"about": "urn:uuid:idm0"})),
    "voluit": _Response(201, _answer(_body("volvo", _verb("volv", "it")))),
    "fuit": _Response(201, {"error": {"$": "Morpheus crashed"}}),
}


@pytest.fixture
def analyzer(monkeypatch, tmp_path):
    def get(url, params, timeout):
        answer = _MORPHEUS.get(params["word"], _Response(201, _answer()))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(process_morpheus_perseids_api.requests, "get", get)
    work_contents = tmp_path / "output" / "library" / "work_contents.csv"
    work_contents.parent.mkdir(parents=True)
    pd.DataFrame({"word": list(_MORPHEUS)}).to_csv(work_contents, index=False)
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
