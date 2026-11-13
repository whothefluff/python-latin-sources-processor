import pytest

from scripts.library.util.spelling import (
    LetterConvention, differs_in_told_apart_letters, has_the_letters_of, projected_macronization, respell,
    respell_macronized, token_spellings_of,
)

# The bundled Phaedrus tells u and v apart, and prints i for both i and j
PHAEDRUS = LetterConvention(uv_lowercase="uv", uv_capitals="UV", ij_lowercase="i", ij_capitals="I")
# OCT and Teubner editions print u for both u and v but a capital V, and i for both i and j
OCT = LetterConvention(uv_lowercase="u", uv_capitals="V", ij_lowercase="i", ij_capitals="I")


class TestRespell:

    @pytest.mark.parametrize("word, surfaces, expected", [
        ("iam", {"jam"}, "jam"),
        ("Iam", {"jam"}, "Jam"),
        ("IAM", {"jam"}, "JAM"),
        ("eius", {"ejus"}, "ejus"),
        ("ait", {"ait"}, "ait"),
    ])
    def test_respell_takes_morpheus_letter_where_the_edition_prints_one_for_both(self, word, surfaces, expected):
        assert respell(word, None, surfaces, PHAEDRUS) == expected


    def test_respell_keeps_a_letter_the_edition_tells_apart(self):
        assert respell("voluit", None, {"voluit", "volvit"}, PHAEDRUS) == "voluit"


    def test_respell_keeps_the_word_without_a_surface_with_its_other_letters(self):
        assert respell("adiecit", None, {"affecit"}, PHAEDRUS) == "adiecit"


    def test_respell_keeps_the_word_when_the_surfaces_disagree(self):
        assert respell("uoluit", None, {"voluit", "volvit"}, OCT) == "uoluit"


    @pytest.mark.parametrize("word, expected", [("uir", "vir"), ("Vt", "Ut"), ("VIR", "VIR")])
    def test_respell_reads_a_capital_v_as_u_or_v_where_the_edition_prints_only_v(self, word, expected):
        assert respell(word, None, {"vir", "ut"}, OCT) == expected


    def test_respell_spells_the_host_when_morpheus_leaves_out_the_enclitic(self):
        assert respell("Iubetque", "que", {"jubet"}, PHAEDRUS) == "Jubetque"


    def test_respell_prefers_the_whole_word(self):
        assert token_spellings_of("iamque", "que", {"jamque", "iam"}, PHAEDRUS) == {"jamque"}


class TestRespellMacronized:

    def test_respell_macronized_changes_the_same_letters(self):
        assert respell_macronized("Iuppiter", "Juppiter", "Iuppiter") == "Juppiter"


    def test_respell_macronized_keeps_the_macrons(self):
        assert respell_macronized("eius", "ejus", "ēius") == "ējus"


    def test_respell_macronized_refuses_a_macron_on_a_consonant(self):
        with pytest.raises(ValueError, match="macron"):
            respell_macronized("iam", "jam", "īam")


class TestDiffersInToldApartLetters:

    @pytest.mark.parametrize("word, surface, expected", [
        ("voluit", "volvit", True),
        ("voluit", "voluit", False),
        ("iam", "jam", False),
        ("voluit", "volvis", False),
        ("adfectus", "affectus", False),
    ])
    def test_differs_in_told_apart_letters(self, word, surface, expected):
        assert differs_in_told_apart_letters(word, surface, PHAEDRUS) is expected


class TestHasTheLettersOf:

    @pytest.mark.parametrize("printed, written, convention, expected", [
        ("Lucio", "Lūciō", PHAEDRUS, True),
        ("locutus es", "locūtus es", PHAEDRUS, True),
        ("iam", "jam", PHAEDRUS, True),
        ("laruatus", "lārvātus", OCT, True),
        ("laruatus", "lārvātus", PHAEDRUS, False),
        ("levis es", "lēvior es", PHAEDRUS, False),
        ("levis es", "lēvis", PHAEDRUS, False),
    ])
    def test_a_written_text_has_the_printed_letters_in_either_case_and_either_letter_where_the_edition_prints_one(
            self, printed, written, convention, expected):
        assert has_the_letters_of(printed, written, convention) is expected


class TestProjectedMacronization:

    @pytest.mark.parametrize("word, expansion, convention, expected", [
        ("locutu", "locūtus", PHAEDRUS, "locūtu"),
        ("s", "es", PHAEDRUS, "s"),
        ("qua", "quā", PHAEDRUS, "quā"),
        ("Laruatu", "lārvātus", OCT, "Lāruātu"),
        ("LOCUTU", "locūtus", PHAEDRUS, "LOCŪTU"),
        ("Iratu", "Īrātus", PHAEDRUS, "Īrātu"),
        ("iratu", "Īrātus", PHAEDRUS, "īrātu"),
    ])
    def test_a_word_printed_short_gets_the_macrons_of_the_letters_of_its_expansion_that_it_prints_in_its_case(
            self, word, expansion, convention, expected):
        assert projected_macronization(word, expansion, convention) == expected

    def test_a_word_that_both_starts_and_ends_its_expansion_gets_the_macrons_of_its_start(self):
        assert projected_macronization("e", "ēdere", PHAEDRUS) == "ē"


    @pytest.mark.parametrize("word, expansion, convention", [
        ("vaniloquo", "vāniloquus", PHAEDRUS),
        ("laruatu", "lārvātus", PHAEDRUS),
        ("locutus", "locūtu", PHAEDRUS),
        ("Vlixe", "ūlixes", OCT),
    ])
    def test_a_word_whose_letters_dont_start_or_end_its_expansion_or_that_would_get_a_macron_on_a_j_or_v_gets_none(
            self, word, expansion, convention):
        assert projected_macronization(word, expansion, convention) is None
