import pytest
from scripts.library.util.token_classification import get_token_type, TokenType


class TestGetTokenType:

    @pytest.mark.parametrize(
        "input_punctuation", [",", ".", "?", "!", ";", "—", "-", "_", "(", ")", ":"]
    )
    def test_token_type_is_4_for_punctuation(self, input_punctuation):
        assert get_token_type(input_punctuation) == TokenType.PUNCTUATION

    @pytest.mark.parametrize("input_editorial", ["†", "‡", "*", "※", "*†"])
    def test_token_type_is_5_for_editorial_marks(self, input_editorial):
        assert get_token_type(input_editorial) == TokenType.EDITORIAL

    @pytest.mark.parametrize("input_numeral", ["I", "XII", "xiv", "IIII", "MDCCLXXVI"])
    def test_token_type_is_3_for_roman_numerals_without_morph_analysis(
        self, input_numeral
    ):
        assert get_token_type(input_numeral, inherent_state=None) == TokenType.NUMERAL

    @pytest.mark.parametrize(
        "input_word, inherent_state",
        [
            ("VI", 0),
            ("DI", 2),
        ],
    )
    def test_token_type_is_1_for_roman_numeral_lookalikes_with_morph_analysis(
        self, input_word, inherent_state
    ):
        assert get_token_type(input_word, inherent_state=inherent_state) == 1

    @pytest.mark.parametrize("input_abbrev", ["M.", "C.", "Ti."])
    def test_token_type_is_2_for_abbreviations(self, input_abbrev):
        assert get_token_type(input_abbrev) == TokenType.ABBREVIATION

    @pytest.mark.parametrize(
        "input_word, inherent_state",
        [
            ("puella", 0),
            ("Roma", 1),
            ("est", None),
        ],
    )
    def test_token_type_is_1_for_alphabetic_words(self, input_word, inherent_state):
        assert (
            get_token_type(input_word, inherent_state=inherent_state) == TokenType.WORD
        )

    @pytest.mark.parametrize("input_other", [None, "", "123", "word1"])
    def test_token_type_is_6_for_unrecognized_tokens(self, input_other):
        assert get_token_type(input_other) == TokenType.OTHER
