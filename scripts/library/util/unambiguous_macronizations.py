from typing import Container, Dict, Iterable, List, NamedTuple, Optional, Set

from scripts.library.util.proper_noun import ProperNounState
from scripts.library.util.token_classification import TokenType


class WorkMacronization(NamedTuple):
    work_id: str
    idx: int
    macronized_word: str
    uncertainty_bit_mask: int


class CertainToken(NamedTuple):
    """A token without a work macronization, and the macronization that its work is certain of, in the token's case."""
    work_id: str
    idx: int
    word: str
    token_type: int
    proper_noun_state: Optional[int]
    macronized_word: str


def lookup_key(word: str, token_type: int, proper_noun_state: Optional[int], keys: Container[str]) -> Optional[str]:
    """Returns the key in keys under which the reader would find the token's unambiguous macronization."""
    if token_type > TokenType.WORD:
        candidates = [word]
    else:
        tries_capitalized = proper_noun_state in (ProperNounState.YES, ProperNounState.EITHER, None)
        tries_lowercase = proper_noun_state in (ProperNounState.NO, ProperNounState.EITHER, None)
        candidates = [*([word.capitalize()] if tries_capitalized else []), *([word.lower()] if tries_lowercase else [])]
    return next((key for key in candidates if key in keys), None)


def agreed_macronizations(certain_macronizations_by_key: Dict[str, Set[str]]) -> Dict[str, str]:
    """Returns the macronization of each key whose certain macronizations are all the same."""
    return {key: next(iter(macronizations))
            for key, macronizations in certain_macronizations_by_key.items() if len(macronizations) == 1}


def work_macronizations_where_keys_disagree(certain_macronizations_by_key: Dict[str, Set[str]],
                                            certain_tokens: Iterable[CertainToken]) -> List[WorkMacronization]:
    """Returns a work macronization with its own macronization for each certain token that the reader would look up by
    a key whose certain macronizations differ."""
    work_macronizations = []
    for token in certain_tokens:
        key = lookup_key(token.word, token.token_type, token.proper_noun_state, certain_macronizations_by_key)
        if key is not None and len(certain_macronizations_by_key[key]) > 1:
            work_macronizations.append(WorkMacronization(token.work_id, token.idx, token.macronized_word, 0))
    return work_macronizations
