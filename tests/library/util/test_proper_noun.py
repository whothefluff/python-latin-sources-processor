import pytest

from scripts.library.util.proper_noun import ProperNounState, compute_context_aware_state

NO, YES, EITHER = ProperNounState.NO, ProperNounState.YES, ProperNounState.EITHER


@pytest.mark.parametrize("inherent_state", [NO, YES, EITHER, None], ids=["fabula", "caesar", "venere", "unknown"])
@pytest.mark.parametrize("is_forgivable_context", [False, True], ids=["inside a sentence", "at a start"])
def test_a_lowercase_word_is_common_whatever_morpheus_has(inherent_state, is_forgivable_context):
    assert compute_context_aware_state(inherent_state, False, is_forgivable_context) == NO


@pytest.mark.parametrize("inherent_state, state", [(NO, EITHER), (YES, YES), (EITHER, YES), (None, YES)],
                         ids=["Religio, a personification", "Caesar", "Venere, Venus", "Philete, without an analysis"])
def test_a_capital_inside_a_sentence_is_proper_and_on_a_common_word_a_proper_use_of_it(inherent_state, state):
    assert compute_context_aware_state(inherent_state, True, False) == state


@pytest.mark.parametrize("inherent_state, state", [(NO, NO), (YES, YES), (EITHER, EITHER), (None, EITHER)],
                         ids=["Fabula", "Caesar", "Venere, venio or Venus", "Venantum, without an analysis"])
def test_a_capital_at_a_start_lets_the_analyses_decide(inherent_state, state):
    assert compute_context_aware_state(inherent_state, True, True) == state
