import pytest
from scripts.library.util.casing import apply_contract_casing, is_proper_item

class TestApplyContractCasing:

    def test_casing_returns_none_when_given_none(self):
        assert apply_contract_casing(None, True) is None


    def test_casing_returns_empty_string_when_given_empty_string(self):
        assert apply_contract_casing("", False) == ""


    @pytest.mark.parametrize("input_text", ["roma", "ROMA", "Roma"])
    def test_casing_capitalizes_proper_nouns(self, input_text):
        assert apply_contract_casing(input_text, is_proper=True) == "Roma"


    @pytest.mark.parametrize("input_text", ["VIRUM", "Virum", "virum"])
    def test_casing_lowercases_common_nouns(self, input_text):
        assert apply_contract_casing(input_text, is_proper=False) == "virum"


class TestIsProperItem:

    @pytest.mark.parametrize("parts_of_speech", [["noun"], ["adjective"], ["interjection", "noun"]])
    def test_a_capitalized_headword_with_a_noun_or_adjective_is_proper(self, parts_of_speech):
        assert is_proper_item("Atticus", parts_of_speech)


    @pytest.mark.parametrize("parts_of_speech", [["interjection"], ["adverb"], []])
    def test_a_capitalized_headword_without_a_noun_or_adjective_is_not_proper(self, parts_of_speech):
        assert not is_proper_item("Hercules", parts_of_speech)


    @pytest.mark.parametrize("headword", ["fabula", "", None])
    def test_a_headword_that_is_not_capitalized_is_not_proper(self, headword):
        assert not is_proper_item(headword, ["noun", "adjective"])
