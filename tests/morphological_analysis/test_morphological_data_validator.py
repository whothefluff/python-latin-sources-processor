import csv

import pytest

from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalDataValidator


@pytest.mark.parametrize("existing", ["morphological_details.csv", "morphological_detail_inflections.csv"],
                         ids=["without inflections", "without details"])
def test_validation_fails_without_both_files(tmp_path, existing):
    (tmp_path / existing).write_text("form,item\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        MorphologicalDataValidator(str(tmp_path / "morphological_detail_inflections.csv"),
                                   str(tmp_path / "morphological_details.csv")).validate()


_FIELDS = ["form", "item", "cnt", "partOfSpeech", "stem", "suffix", "segmentsInfo", "gender", "number", "declension",
           "case", "verbForm", "tense", "voice", "person"]
_NOMINATIVE = {"gender": "masculine", "number": "singular", "declension": "2nd", "case": "nominative"}
_NOMINATIVE_PLURAL = {"gender": "feminine", "number": "plural", "declension": "1st", "case": "nominative"}


def _validator(tmp_path, *items):
    """Returns a validator of output files that hold one item for each form, headword, sublemma, part of speech and
    its other fields."""
    details_path = tmp_path / "morphological_details.csv"
    inflections_path = tmp_path / "morphological_detail_inflections.csv"
    with open(details_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["form", "item", "dictionaryRef", "sublemma"],
                                 *([form, 0, ref, sublemma] for form, ref, sublemma, _, _ in items)])
    with open(inflections_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, _FIELDS)
        writer.writeheader()
        writer.writerows({"form": form, "item": 0, "cnt": 0, "partOfSpeech": pos, "stem": form} | fields
                         for form, _, _, pos, fields in items)
    return MorphologicalDataValidator(str(inflections_path), str(details_path))


def test_forms_cased_as_their_items_pass(tmp_path):
    _validator(tmp_path, ("Atticus", "Atticus", "", "adjective", _NOMINATIVE),
               ("hercle", "Hercules", "", "interjection", {}), ("Aesopus", "Aesopus", "", "noun", _NOMINATIVE),
               ("fabula", "fabula", "", "noun", _NOMINATIVE),
               ("Horae", "hora1", "Horae", "noun", _NOMINATIVE_PLURAL)).validate()


@pytest.mark.parametrize("item", [("atticus", "Atticus", "", "adjective", _NOMINATIVE),
                                  ("Hercle", "Hercules", "", "interjection", {}),
                                  ("horae", "hora1", "Horae", "noun", _NOMINATIVE_PLURAL)],
                         ids=["a proper adjective in lowercase", "a capitalized interjection",
                              "a capitalized sublemma in lowercase"])
def test_a_form_cased_against_its_item_fails_validation(tmp_path, caplog, item):
    with pytest.raises(ValueError, match="Found 1 issues"):
        _validator(tmp_path, item).validate()
    assert f"CASING '{item[0]}'" in caplog.text
