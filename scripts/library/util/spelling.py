from typing import Iterable, NamedTuple

_PAIRS = ("uv", "ij")


class LetterConvention(NamedTuple):
    """The letters that an edition prints for u/v and for i/j, in lowercase and in capitals.
    Two letters, such as 'uv', mean that the edition tells them apart. One letter, such as 'u', stands for both."""
    uv_lowercase: str
    uv_capitals: str
    ij_lowercase: str
    ij_capitals: str


def _pair_of(letter: str) -> str | None:
    return next((pair for pair in _PAIRS if letter.lower() in pair), None)


def _stands_for(letter: str, convention: LetterConvention) -> str:
    """Returns the lowercase letters of Morpheus's spelling that a letter printed in the edition can stand for"""
    pair = _pair_of(letter)
    if pair is None:
        return letter.lower()
    printed = getattr(convention, f"{pair}_{'capitals' if letter.isupper() else 'lowercase'}")
    return pair if len(printed) == 1 else letter.lower()


def _respelled_as(word: str, surface: str, convention: LetterConvention) -> str | None:
    """Returns the word with the surface's letters where the edition prints one letter for two, in the word's case.
    Returns None when the surface has a different letter anywhere else"""
    if len(word) != len(surface):
        return None
    letters = []
    for letter, morpheus_letter in zip(word, surface):
        if morpheus_letter not in _stands_for(letter, convention):
            return None
        letters.append(morpheus_letter.upper() if letter.isupper() else morpheus_letter)
    return "".join(letters)


def spellings_of(word: str, surfaces: Iterable[str], convention: LetterConvention) -> set[str]:
    """Returns every spelling of the word that Morpheus's surfaces give it. The surfaces are lowercase and without
    macrons."""
    return {spelling for surface in surfaces if (spelling := _respelled_as(word, surface, convention)) is not None}


def token_spellings_of(word: str, enclitic: str | None, surfaces: Iterable[str],
                       convention: LetterConvention) -> set[str]:
    """Returns the same as spellings_of, or the host's spellings followed by the enclitic when the surfaces leave the
    enclitic out"""
    surfaces = set(surfaces)
    spellings = spellings_of(word, surfaces, convention)
    if not spellings and enclitic and len(word) > len(enclitic):
        tail = word[-len(enclitic):]
        spellings = {host + tail for host in spellings_of(word[:-len(enclitic)], surfaces, convention)}
    return spellings


def respell(word: str, enclitic: str | None, surfaces: Iterable[str], convention: LetterConvention) -> str:
    """Returns the word spelled as Morpheus spells it where the edition prints one letter for two.
    The word keeps the edition's letters when no surface has its other letters, or when the surfaces disagree"""
    spellings = token_spellings_of(word, enclitic, surfaces, convention)
    return spellings.pop() if len(spellings) == 1 else word


def respell_macronized(word: str, respelled: str, macronized: str) -> str:
    """Returns the macronized word with the letters that respelling changed"""
    if len(macronized) != len(word):
        raise ValueError(f"'{macronized}' doesn't have the same letters as '{word}'")
    letters = list(macronized)
    for i, (letter, new_letter) in enumerate(zip(word, respelled)):
        if letter != new_letter:
            if macronized[i] != letter:
                raise ValueError(f"'{macronized}' has a macron on the letter that '{respelled}' spells as a consonant")
            letters[i] = new_letter
    return "".join(letters)


def differs_in_told_apart_letters(word: str, surface: str, convention: LetterConvention) -> bool:
    """Returns whether the surface differs from the word only in letters of a pair, and in at least one letter of a
    pair that the edition tells apart"""
    if len(word) != len(surface):
        return False
    only_pairs_changed = all(letter.lower() == morpheus_letter or morpheus_letter in (_pair_of(letter) or "")
                             for letter, morpheus_letter in zip(word, surface))
    return only_pairs_changed and _respelled_as(word, surface, convention) is None
