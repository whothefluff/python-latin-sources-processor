import pytest

from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_outputs_built_from_another_source_are_refused(tmp_path):
    _write(tmp_path / "output" / "library" / "work_contents.csv", "word\njam\n")
    _write(tmp_path / "output" / "morphological_analysis" / "morphological_details.csv",
           "form,item,dictionaryRef\niam,0,jam\n")

    with pytest.raises(ValueError, match="iam"):
        MorphologicalAnalyzer(str(tmp_path))


def test_outputs_missing_forms_of_the_source_are_extended(tmp_path):
    _write(tmp_path / "output" / "library" / "work_contents.csv", "word\njam\nest\n")
    _write(tmp_path / "output" / "morphological_analysis" / "morphological_details.csv",
           "form,item,dictionaryRef\nest,0,sum1\n")

    analyzer = MorphologicalAnalyzer(str(tmp_path))

    assert analyzer.unique_words - analyzer.processed_forms == {"jam"}
