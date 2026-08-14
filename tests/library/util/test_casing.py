import pytest
from scripts.library.util.casing import apply_contract_casing

class TestApplyContractCasing:

    def test_casing_returns_none_when_given_none(self):
        assert apply_contract_casing(None, True) is None


    def test_casing_returns_empty_string_when_given_empty_string(self):
        assert apply_contract_casing("", False) == ""


    @pytest.mark.parametrize("input_text", ["roma", "ROMA", "Roma"])
    def test_casing_capitalizes_proper_nouns(self, input_text):
        assert apply_contract_casing(input_text, is_proper_noun=True) == "Roma"


    @pytest.mark.parametrize("input_text", ["VIRUM", "Virum", "virum"])
    def test_casing_lowercases_common_nouns(self, input_text):
        assert apply_contract_casing(input_text, is_proper_noun=False) == "virum"
