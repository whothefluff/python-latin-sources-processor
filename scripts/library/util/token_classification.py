import re
from enum import IntEnum


class TokenType(IntEnum):
    WORD = 1
    ABBREVIATION = 2
    NUMERAL = 3
    PUNCTUATION = 4
    EDITORIAL = 5
    OTHER = 6


# Matches valid Roman numerals (case-insensitive)
ROMAN_NUMERAL_RE = re.compile(
    r"^(?=[MDCLXVI])M*(C[MD]|D?C{0,4})(X[CL]|L?X{0,4})(I[XV]|V?I{0,4})$",
    re.IGNORECASE,
)
EDITORIAL_MARKS = {
    "†",
    "‡",
    "*",
    "※",
}


def get_token_type(raw_token: str, inherent_state: int | None = None) -> TokenType:
    """
    Returns the numeric token type according to the Pipeline Contract:
    1 (word), 2 (abbreviation), 3 (roman numeral), 4 (punctuation mark), 5 (editorial mark), 6 (other)
    """
    if not raw_token:
        return TokenType.OTHER
    if not any(c.isalnum() for c in raw_token):
        if any(c in EDITORIAL_MARKS for c in raw_token):
            return TokenType.EDITORIAL
        else:
            return TokenType.PUNCTUATION
    if ROMAN_NUMERAL_RE.fullmatch(raw_token):
        # Only classify as numeral if Morpheus does NOT recognize it as a word
        # Numeral symbols return empty but collisions return analyses (e.g. 'I' is interpreted as a form of 'ire')
        # We default to the word type meaning that, if wrong, it has to be overwritten in the specific work processor
        if inherent_state is None:
            return TokenType.NUMERAL
    if raw_token.endswith(".") and len(raw_token) <= 3:
        return TokenType.ABBREVIATION
    if raw_token.isalpha():
        return TokenType.WORD
    return TokenType.OTHER  # (e.g., alphanumeric mix)
