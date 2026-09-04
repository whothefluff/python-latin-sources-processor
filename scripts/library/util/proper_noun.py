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
) -> ProperNounState | None:
    """Refines the inherent state using sentence-start/capitalization data."""
    if word_is_capitalized:
        if inherent_state == ProperNounState.NO:  # Common word like "Fabula"
            # Titles and such are editorial choice; otherwise typo or similar
            return ProperNounState.NO if is_forgivable_context else None
        elif inherent_state == ProperNounState.YES:  # Proper noun like "Caesar"
            return ProperNounState.YES
        elif inherent_state == ProperNounState.EITHER:  # Dubious word like "Venere" (venio, Venus)
            # Capitalized mid-sentence is a proper noun; at start it's uncertain.
            return ProperNounState.EITHER if is_forgivable_context else ProperNounState.YES
        return None
    else:
        if inherent_state == ProperNounState.NO:  # "fabula"
            return ProperNounState.NO
        elif inherent_state == ProperNounState.YES:  # "caesar"
            # Probably a typo or similar
            return None
        elif inherent_state == ProperNounState.EITHER:  # "venere"
            return ProperNounState.NO
        return None