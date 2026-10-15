import pytest

from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalDataValidator


@pytest.mark.parametrize("existing", ["morphological_details.csv", "morphological_detail_inflections.csv"],
                         ids=["without inflections", "without details"])
def test_validation_fails_without_both_files(tmp_path, existing):
    (tmp_path / existing).write_text("form,item\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        MorphologicalDataValidator(str(tmp_path / "morphological_detail_inflections.csv"),
                                   str(tmp_path / "morphological_details.csv")).validate()
