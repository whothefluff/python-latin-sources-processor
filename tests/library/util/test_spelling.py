import pytest

from scripts.library.util.spelling import (
    LetterConvention, differs_in_told_apart_letters, respell, respell_macronized, token_spellings_of,
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
