from enum import IntEnum


class ProperNounState(IntEnum):
    NO = 0
    YES = 1
    EITHER = 2


def is_proper_noun_lemma(lemma: str) -> bool:
    """Checks whether a lemma indicates a proper noun by looking at its capitalization"""
    return bool(lemma) and lemma[0].isupper()


def compute_inherent_state(has_common_word_analysis: bool, has_proper_noun_analysis: bool) -> ProperNounState | None:
    """Context-independent state. Calls should be based purely on dictionary lookups."""
    if has_proper_noun_analysis and has_common_word_analysis:
        return ProperNounState.EITHER  # e.g. "Venere" (venio, Venus)
    elif has_proper_noun_analysis:
        return ProperNounState.YES  # e.g. "Caesar"
    elif has_common_word_analysis:
        return ProperNounState.NO
    return None


def compute_context_aware_state(
        inherent_state: ProperNounState | None,
        word_is_capitalized: bool,
        is_forgivable_context: bool,
) -> ProperNounState:
    """Refines the inherent state with the word's case and position, as editions use them.

    A lowercase word is common, whatever Morpheus has for it. A capital inside a sentence makes a word proper; when
    Morpheus has only a common word for it, the capital is a proper use of that word, such as a personification. Where
    a verse or a sentence starts, or after a capitalized word, the capital may be the position's: then the analyses
    decide, and without any, the word can be either."""
    if not word_is_capitalized:
        # "fabula", "venere" (venio, not Venus), and "tartareo", an adjective from a name printed lowercase
        return ProperNounState.NO
    if is_forgivable_context:
        # "Fabula", "Caesar", "Venere" (venio or Venus), and a word without an analysis
        return ProperNounState.EITHER if inherent_state is None else inherent_state
    # "Religio" (religio), "Caesar", "Venere" (Venus), and a name without an analysis
    return ProperNounState.EITHER if inherent_state == ProperNounState.NO else ProperNounState.YES