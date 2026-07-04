import pytest
from scripts.library.util.text_normalization import normalize_digraphs


class TestNormalizeDigraphs:

    def test_normalize_returns_none_when_given_none(self):
        assert normalize_digraphs(None) is None

    def test_normalize_returns_empty_string_when_given_empty_string(self):
        assert normalize_digraphs("") == ""

    @pytest.mark.parametrize(
        "input_text, expected",
        [
            ("puella", "puella"),
            ("Romamque", "Romamque"),
        ],
    )
    def test_normalize_ignores_text_without_digraphs(self, input_text, expected):
        assert normalize_digraphs(input_text) == expected

    @pytest.mark.parametrize(
        "input_text, expected",
        [
            ("cælum", "caelum"),
            ("œconomia", "oeconomia"),
            ("cælumœ", "caelumoe"),
        ],
    )
    def test_normalize_replaces_lowercase_digraphs(self, input_text, expected):
        assert normalize_digraphs(input_text) == expected

    @pytest.mark.parametrize(
        "input_text, expected",
        [
            ("Æneas", "Aeneas"),
            ("Œdipus", "Oedipus"),
        ],
    )
    def test_normalize_replaces_uppercase_digraphs(self, input_text, expected):
        assert normalize_digraphs(input_text) == expected

    @pytest.mark.parametrize(
        "input_text, expected",
        [
            ("ÆNEAS", "AENEAS"),
            ("ŒDIPUS", "OEDIPUS"),
            ("Æ", "AE"),
            ("CŒLUM", "COELUM"),
        ],
    )
    def test_normalize_replaces_uppercase_digraphs_in_all_caps_words(
        self, input_text, expected
    ):
        assert normalize_digraphs(input_text) == expected
