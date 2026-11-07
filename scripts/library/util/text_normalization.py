def normalize_digraphs(text: str | None) -> str | None:
    """
    Replaces æ/œ ligatures with ae/oe.
    Required by the Pipeline Contract to maintain skeleton identity
    between raw words and macronized words.
    """
    if text is not None:
        if text.isupper():
            return (
                text.replace("æ", "AE")  # Safe fallback
                .replace("œ", "OE")
                .replace("Æ", "AE")
                .replace("Œ", "OE")
            )
        else:
            return (
                text.replace("æ", "ae")
                .replace("œ", "oe")
                .replace("Æ", "Ae")
                .replace("Œ", "Oe")
            )


#: Each vowel with the acute that some editions put on it to mark the ictus, and the vowel without it
_VOWELS_BY_ICTUS_MARKED_VOWEL = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ý': 'y',
                                 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ý': 'Y'}


def without_ictus_marks(text: str) -> str:
    """Returns the text without the acutes that some editions put on vowels to mark the ictus, such as Plautus's
    audácior. Required by the Pipeline Contract, as digraphs are"""
    return text.translate(str.maketrans(_VOWELS_BY_ICTUS_MARKED_VOWEL))


def ictus_bit_mask(word: str) -> int:
    """Returns a mask with bit N set when the Nth letter of the word has the acute that marks the ictus"""
    return sum(1 << position for position, letter in enumerate(word) if letter in _VOWELS_BY_ICTUS_MARKED_VOWEL)
