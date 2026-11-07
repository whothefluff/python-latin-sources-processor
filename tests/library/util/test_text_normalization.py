import pytest
from scripts.library.util.text_normalization import ictus_bit_mask, normalize_digraphs, without_ictus_marks


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


class TestIctusMarks:

    @pytest.mark.parametrize(
        "word, expected",
        [
            ("audácior", "audacior"),
            ("áéíóúý", "aeiouy"),
            ("ÁÉÍÓÚÝ", "AEIOUY"),
            ("Útinam", "Utinam"),
            ("audācior", "audācior"),
            ("puella", "puella"),
        ],
    )
    def test_a_word_loses_the_acutes_that_mark_its_ictus_and_nothing_else(self, word, expected):
        assert without_ictus_marks(word) == expected

    @pytest.mark.parametrize(
        "word, expected",
        [
            ("audácior", 0b1000),
            ("ímperátor", 0b100001),
            ("Útinam", 0b1),
            ("ý", 0b1),
            ("audācior", 0),
            ("puella", 0),
        ],
    )
    def test_the_ictus_bit_mask_has_the_bit_of_each_letter_with_the_acute_of_the_ictus(self, word, expected):
        assert ictus_bit_mask(word) == expected
