import re

import pytest

from scripts.library.util.quotation_marks import AddedMark, PrintedMark, UnsettledMark, characters

_URN = 'urn:cts:latinLit:fict001.fict001.fict-lat1'


def _printed(text: str, first_idx: int = 0, textpart_id: str = 'poem') -> list:
    """Returns the printed marks of a block's text, each with the place of its character, from first_idx, as its
    token's index"""
    return [PrintedMark(idx=first_idx + position, character=character,
                        character_before=text[position - 1:position],
                        character_after=text[position + 1:position + 2],
                        is_contraction_apostrophe=False, textpart_id=textpart_id, reference='1.1', words_around=text)
            for position, character in enumerate(text) if character in '“„”‘’«»`"\'']


def _added(idx: int, opens: bool, pair_by_rend: str | None = None, textpart_id: str = 'poem') -> AddedMark:
    return AddedMark(idx=idx, opens=opens, pair_by_rend=pair_by_rend, textpart_id=textpart_id, reference='1.1',
                     words_around='ait')


def _shown(text: str, marks: list, unsettled_printed_marks=None, inside=None) -> str:
    """Returns the text with each printed mark's character"""
    found, problems = characters(marks, unsettled_printed_marks or {}, inside or {}, _URN)
    assert problems == []
    return ''.join(found.get(idx, character) for idx, character in enumerate(text))


@pytest.mark.parametrize("text, shown", [
    ("Ipsa mihi dixi: 'si valet ille, venit.'", "Ipsa mihi dixi: ‘si valet ille, venit.’"),
    ('"Feliciter!" succlamans.', '“Feliciter!” succlamans.'),
    ('si quis Deus ‘en ego,’ dicat', 'si quis Deus ‘en ego,’ dicat'),
    ("ait 'lib. 2' et", "ait ‘lib. 2’ et"),
], ids=["straight single marks", "straight double marks", "a ’ after punctuation", "a ' after a digit"])
def test_a_printed_mark_opens_after_a_space_before_a_letter_and_closes_after_punctuation_or_a_digit_and_is_typographic(
        text, shown):
    assert _shown(text, _printed(text)) == shown


@pytest.mark.parametrize("text, idx", [
    ("si quis ‘en ego’ dicat", 15), ("talin' pavidissime", 5), ('paras adclamare : " Haec sunt', 18),
    ("quod dicis, ' libenter oppetam", 12), ("'quo'que ait", 4), ("dixit '2 viri", 6),
], ids=["a ’ after a letter", "a ' after a letter", 'a " between two spaces', "a ' between a space and another",
        "a ' between two letters", "a ' between a space and a digit"])
def test_a_mark_that_the_characters_around_it_leave_unsettled_needs_the_configuration_to_say_what_it_is(text, idx):
    _, problems = characters(_printed(text), {}, {}, _URN)

    assert [problem.startswith(f"{_URN} 1.1: unsettled_printed_marks must say whether the {text[idx]} at idx "
                               f"{idx}, in {text!r}, ") for problem in problems] == [True]


def test_unsettled_printed_marks_says_whether_a_mark_opens_closes_or_is_an_apostrophe():
    text = "si quis ‘en ego’ dicat, talin’ pavidissime"
    marks = _printed(text)

    closing_mark, apostrophe = text.index('’'), text.rindex('’')

    assert _shown(text, marks, {closing_mark: UnsettledMark.CLOSES, apostrophe: UnsettledMark.APOSTROPHE}) == \
        "si quis ‘en ego’ dicat, talin' pavidissime"
    assert _shown('" Haec sunt "', _printed('" Haec sunt "'), {0: UnsettledMark.OPENS, 12: UnsettledMark.CLOSES}) == \
        '“ Haec sunt ”'


def test_a_contraction_s_apostrophe_is_one_without_an_answer():
    marks = [mark._replace(is_contraction_apostrophe=True) for mark in _printed('locutu’s')]

    assert characters(marks, {}, {}, _URN) == ({6: "'"}, [])


@pytest.mark.parametrize("unsettled_printed_marks, inside, problem", [
    ({0: UnsettledMark.OPENS, 5: UnsettledMark.CLOSES}, {},
     f"{_URN}: unsettled_printed_marks has idx 0, which isn't a printed mark that the characters around it leave "
     f"unsettled"),
    ({5: UnsettledMark.CLOSES}, {3: True},
     f"{_URN}: quotations_inside_printed_marks has idx 3, which opens no quotation after a printed mark that code "
     f"can't follow"),
    ({5: UnsettledMark.APOSTROPHE}, {},
     f"{_URN} 1.1: unsettled_printed_marks must say whether the \" at idx 5, in ' \" ', opens or closes: the "
     f"characters around it don't"),
], ids=["an answer where the characters around the mark settle it", "an answer for a quotation after no such mark",
        'an apostrophe for a "'])
def test_an_answer_that_nothing_reads_or_that_cant_be_is_a_problem(unsettled_printed_marks, inside, problem):
    marks = [*_printed("'s", textpart_id='other poem'), _added(3, True, 'double'), _added(4, False),
             *_printed(' " ', first_idx=4, textpart_id='another poem')]

    _, problems = characters(marks, unsettled_printed_marks, inside, _URN)

    assert problems == [problem]


@pytest.mark.parametrize("marks, pair", [
    ([_added(0, True), _added(1, False)], '“”'),
    ([_added(0, True, 'single'), _added(1, False)], '‘’'),
    ([_added(0, True), _added(1, False), *_printed('"a" \'a', first_idx=9, textpart_id='other')], '“”'),
    ([_added(0, True), _added(1, False), *_printed('‘a.’ "a', first_idx=9, textpart_id='other')], '‘’'),
], ids=["none: double", "a rend", "a straight pair against a single mark", "a printed opening against half one"])
def test_the_marks_that_the_producer_adds_are_of_the_pair_with_the_most_openings(marks, pair):
    found, _ = characters(marks, {}, {}, _URN)

    assert found[0] + found[1] == pair


def test_a_quotation_that_takes_the_work_s_pair_raises_when_the_pairs_tie():
    marks = [*_printed('“a” ‘a.’'), _added(8, True, textpart_id='next poem'), _added(9, False, textpart_id='next poem')]

    with pytest.raises(ValueError, match=re.escape(f"{_URN} 1.1: the quotation that opens at idx 8, in 'ait', takes "
                                                   f"the work's pair, but the edition opens as many quotations with "
                                                   f"double marks as with single")):
        characters(marks, {}, {}, _URN)


def test_pairs_that_tie_raise_nothing_where_no_quotation_takes_the_work_s_pair():
    inside_printed_double_marks = [*_printed('“a ‘a.’'), _added(10, True, textpart_id='next poem'),
                                   _added(11, False, textpart_id='next poem'), *_printed('a”', 11, 'next poem')]

    assert characters(_printed('“a” ‘a.’'), {}, {}, _URN) == ({0: '“', 2: '”', 4: '‘', 7: '’'}, [])
    assert characters(inside_printed_double_marks, {}, {}, _URN) == (
        {0: '“', 3: '‘', 6: '’', 10: '‘', 11: '’', 12: '”'}, [])


def test_a_quotation_inside_another_or_inside_printed_double_marks_gets_the_other_pair():
    marks = [_added(0, True, 'double'), _added(1, True), _added(2, False), _added(3, False), *_printed('“a', 4),
             _added(5, True), _added(6, False), *_printed('.”', 6), _added(8, True, 'double'), _added(9, False)]

    found, problems = characters(marks, {}, {}, _URN)

    assert (''.join(found[idx] for idx in range(10)), problems) == ('“‘’”“‘’”“”', [])


def test_a_quotation_after_a_printed_mark_that_code_cant_follow_is_inside_it_as_the_configuration_says():
    marks = [*_printed('‘a'), _added(1, True), _added(2, False), _added(3, True, textpart_id='next poem'),
             _added(4, False, textpart_id='next poem'), *_printed('.’', 4), _added(6, True), _added(7, False)]

    found, problems = characters(marks, {}, {1: True, 6: False}, _URN)

    assert (''.join(found[idx] for idx in range(8)), problems) == ('‘“”‘’’‘’', [])
    assert characters(marks, {}, {}, _URN)[1] == [
        f"{_URN} 1.1: the quotation that opens at idx {idx}, in 'ait', comes after a printed mark that code can't "
        f"follow, so quotations_inside_printed_marks must say whether it's inside a printed quotation"
        for idx in (1, 6)]


def test_a_quotation_inside_another_asks_nothing_after_a_printed_mark_that_code_cant_follow():
    marks = [*_printed('‘a'), _added(1, True), _added(2, True), _added(3, False), _added(4, False)]

    assert characters(marks, {}, {1: False}, _URN) == ({0: '‘', 1: '‘', 2: '“', 3: '”', 4: '’'}, [])


def test_a_quotation_that_the_configuration_puts_inside_a_single_mark_inside_printed_double_marks_gets_double_marks():
    marks = [*_printed('“a ‘b'), _added(5, True), _added(6, False), *_printed('c’ d”', 6)]

    assert characters(marks, {7: UnsettledMark.CLOSES}, {5: True}, _URN) == (
        {0: '“', 3: '‘', 5: '“', 6: '”', 7: '’', 10: '”'}, [])


@pytest.mark.parametrize("mark", ['«', '»', '„', '`'])
def test_a_mark_that_no_edition_prints_raises(mark):
    with pytest.raises(ValueError, match=re.escape(f"{_URN} 1.1: the {mark} at idx 8, in 'pristina{mark} "
                                                   f"fortunae', is a mark that no edition prints")):
        characters(_printed(f'pristina{mark} fortunae'), {}, {}, _URN)


def test_the_raise_names_every_mark_that_no_edition_prints():
    with pytest.raises(ValueError) as raised:
        characters(_printed('pristina« fortunae, usu crescunt»'), {}, {}, _URN)

    assert str(raised.value) == (
        f"{_URN} 1.1: the « at idx 8, in 'pristina« fortunae, usu crescunt»', is a mark that no edition prints, so it "
        f"can only be the edition's mistake.\n"
        f"{_URN} 1.1: the » at idx 32, in 'pristina« fortunae, usu crescunt»', is a mark that no edition prints, so it "
        f"can only be the edition's mistake.")


def test_a_printed_closing_double_mark_that_closes_nothing_raises():
    with pytest.raises(ValueError, match=re.escape(f"{_URN} 1.1: the ” at idx 6, in 'modos.” Et', closes no “")):
        characters(_printed('modos.” Et'), {}, {}, _URN)


def test_an_edition_that_ends_with_printed_double_marks_open_raises_naming_each_one_that_a_closing_mark_left_open():
    with pytest.raises(ValueError) as raised:
        characters(_printed('Dixit “ait “mala ducis” et “avi'), {}, {}, _URN)

    assert str(raised.value) == (
        f"{_URN} 1.1: the “ at idx 6, in 'Dixit “ait “mala ducis” et “avi', is still open where the edition ends, "
        f"which can only be the edition's mistake.\n"
        f"{_URN} 1.1: the “ at idx 27, in 'Dixit “ait “mala ducis” et “avi', is still open where the edition ends, "
        f"which can only be the edition's mistake.")


def test_a_quotation_after_a_closing_single_mark_after_a_letter_asks_nothing():
    marks = [*_printed('o’ '), _added(3, True), _added(4, False)]

    assert characters(marks, {1: UnsettledMark.CLOSES}, {}, _URN)[1] == []
