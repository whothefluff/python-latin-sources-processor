from typing import Iterable

# A capitalized headword makes an item proper only for these parts of speech. An interjection whose headword is a name
# ("hercle" -> "Hercules") is not itself proper
PROPER_PARTS_OF_SPEECH = frozenset({"noun", "adjective"})


def is_proper_item(headword: str | None, parts_of_speech: Iterable[str | None]) -> bool:
    """Whether an analysis item is proper: its headword is capitalized and at least one of its inflections is a noun or
    an adjective. Proper adjectives ("Atticus") keep their part of speech."""
    return bool(headword) and headword[0].isupper() and any(pos in PROPER_PARTS_OF_SPEECH for pos in parts_of_speech)


def apply_contract_casing(word_form: str, is_proper: bool) -> str:
    """
    Enforces the 'Match Domain Casing Rule' for dictionary joins.
    - Proper nouns and proper adjectives -> Capitalized (Title Case)
    - Everything else -> lowercase
    """
    if not word_form:
        return word_form
    if is_proper:
        return word_form.capitalize()
    return word_form.lower()