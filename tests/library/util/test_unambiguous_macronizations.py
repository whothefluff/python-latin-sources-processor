import pytest

from scripts.library.util.proper_noun import ProperNounState
from scripts.library.util.token_classification import TokenType
from scripts.library.util.unambiguous_macronizations import lookup_key


@pytest.mark.parametrize("word, token_type, proper_noun_state, keys, expected", [
    ("Levis", TokenType.WORD, ProperNounState.NO, {"Levis", "levis"}, "levis"),
    ("roma", TokenType.WORD, ProperNounState.YES, {"Roma", "roma"}, "Roma"),
    ("roma", TokenType.WORD, ProperNounState.YES, {"roma"}, None),
    ("Venere", TokenType.WORD, ProperNounState.EITHER, {"Venere", "venere"}, "Venere"),
    ("Venere", TokenType.WORD, ProperNounState.EITHER, {"venere"}, "venere"),
    ("Fabula", TokenType.WORD, None, {"Fabula", "fabula"}, "Fabula"),
    ("Fabula", TokenType.WORD, None, {"fabula"}, "fabula"),
    ("XII", TokenType.NUMERAL, ProperNounState.NO, {"XII", "xii"}, "XII"),
])
def test_lookup_key_follows_the_reader_casing_rules(word, token_type, proper_noun_state, keys, expected):
    assert lookup_key(word, token_type, proper_noun_state, keys) == expected
