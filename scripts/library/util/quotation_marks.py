"""Gives a work's quotation marks and apostrophes their characters, printed or added around tagged quotations"""
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, NamedTuple, Sequence, Set, Tuple, Union


class UnsettledMark(Enum):
    """What a printed straight mark or ’ is, where the characters around it don't say"""
    OPENS = auto()
    CLOSES = auto()
    APOSTROPHE = auto()


class PrintedMark(NamedTuple):
    """A quotation mark or an apostrophe that the edition prints"""
    idx: int
    character: str
    #: '' at an edge of its block or of a lost passage
    character_before: str
    character_after: str
    is_contraction_apostrophe: bool
    #: Where a mark that code can't follow counts for the quotations after it
    textpart_id: str
    reference: str
    words_around: str


class AddedMark(NamedTuple):
    """A mark that the producer adds before or after the chain of a tagged quotation"""
    idx: int
    opens: bool
    pair_by_rend: str | None
    textpart_id: str
    reference: str
    words_around: str


Mark = Union[PrintedMark, AddedMark]

#: No edition of the corpus prints one as a quotation mark, so one in the text is its edition's mistake
_MARKS_NO_EDITION_PRINTS = ('«', '»', '„', '`')
_PAIRS = {'double': ('“', '”'), 'single': ('‘', '’')}
_INNER_PAIRS = {'double': 'single', 'single': 'double'}
_PAIR_BY_MARK_OF_ONE_READING = {'“': 'double', '”': 'double', '‘': 'single'}
_OPENING_MARKS_OF_ONE_READING = ('“', '‘')
#: A " opens or closes, and a ' or a ’ can also be an apostrophe
_PAIR_BY_MARK_OF_SEVERAL_READINGS = {'"': 'double', "'": 'single', '’': 'single'}
_APOSTROPHE = "'"
MARK_CHARACTERS = (*_PAIR_BY_MARK_OF_ONE_READING, *_PAIR_BY_MARK_OF_SEVERAL_READINGS, *_MARKS_NO_EDITION_PRINTS)


class _QuotationMarkReading(NamedTuple):
    pair: str
    opens: bool


@dataclass(frozen=True)
class _ApostropheReading:
    pass


_Reading = Union[_QuotationMarkReading, _ApostropheReading]


def characters(marks: Sequence[Mark], unsettled_printed_marks: Dict[int, UnsettledMark],
               quotations_inside_printed_marks: Dict[int, bool], urn: str) -> Tuple[Dict[int, str], List[str]]:
    """Returns each mark's character by its token index, and the configuration's problems with them. Raises on what
    can only be the edition's mistake: a mark that no edition prints, a ” that closes no “, and a “ still open where
    the edition ends"""
    printed_marks = [mark for mark in marks if isinstance(mark, PrintedMark)]
    marks_no_edition_prints = [mark for mark in printed_marks if mark.character in _MARKS_NO_EDITION_PRINTS]
    if marks_no_edition_prints:
        raise ValueError('\n'.join(f"{urn} {mark.reference}: the {mark.character} at idx {mark.idx}, in "
                                   f"{mark.words_around!r}, is a mark that no edition prints, so it can only be the "
                                   f"edition's mistake." for mark in marks_no_edition_prints))
    problems: List[str] = []
    readings = {mark.idx: _reading(mark, unsettled_printed_marks.get(mark.idx), urn, problems)
                for mark in printed_marks}
    unsettled = {mark.idx for mark in printed_marks if _is_unsettled(mark)}
    problems.extend(f"{urn}: unsettled_printed_marks has idx {idx}, which isn't a printed mark that the characters "
                    f"around it leave unsettled" for idx in sorted(set(unsettled_printed_marks) - unsettled))
    openings = _openings_by_pair(marks, readings)
    found: Dict[int, str] = {}
    open_printed_double_marks: List[PrintedMark] = []
    open_chain_pairs: List[str] = []
    unfollowed_pair_by_textpart_id: Dict[str, str] = {}
    asked: Set[int] = set()
    for mark in sorted(marks, key=lambda mark: mark.idx):
        if isinstance(mark, PrintedMark):
            reading = readings[mark.idx]
            found[mark.idx] = _PAIRS[reading.pair][0 if reading.opens else 1] \
                if isinstance(reading, _QuotationMarkReading) else _APOSTROPHE
            _follow(mark, reading, open_printed_double_marks, unfollowed_pair_by_textpart_id, urn)
        elif mark.opens:
            asks = not open_chain_pairs and mark.textpart_id in unfollowed_pair_by_textpart_id
            inside = quotations_inside_printed_marks.get(mark.idx) if asks else False
            if asks:
                asked.add(mark.idx)
            if inside is None:
                problems.append(f"{urn} {mark.reference}: the quotation that opens at idx {mark.idx}, in "
                                f"{mark.words_around!r}, comes after a printed mark that code can't follow, so "
                                f"quotations_inside_printed_marks must say whether it's inside a printed quotation")
            holder = open_chain_pairs[-1] if open_chain_pairs \
                else unfollowed_pair_by_textpart_id[mark.textpart_id] if inside \
                else 'double' if open_printed_double_marks else None
            open_chain_pairs.append(_INNER_PAIRS[holder] if holder is not None else _work_pair(openings, mark, urn))
            found[mark.idx] = _PAIRS[open_chain_pairs[-1]][0]
        else:
            found[mark.idx] = _PAIRS[open_chain_pairs.pop()][1]
    problems.extend(f"{urn}: quotations_inside_printed_marks has idx {idx}, which opens no quotation after a printed "
                    f"mark that code can't follow" for idx in sorted(set(quotations_inside_printed_marks) - asked))
    if open_printed_double_marks:
        raise ValueError('\n'.join(f"{urn} {mark.reference}: the “ at idx {mark.idx}, in {mark.words_around!r}, is "
                                   f"still open where the edition ends, which can only be the edition's mistake."
                                   for mark in open_printed_double_marks))
    return found, problems


def _follow(mark: PrintedMark, reading: _Reading, open_printed_double_marks: List[PrintedMark],
            unfollowed_pair_by_textpart_id: Dict[str, str], urn: str):
    """Follows a printed mark: a “ opens, a ” closes the last “ open, and a ‘, a straight mark or a ’ after no letter
    is its textpart's last unfollowed one. Raises on a ” that closes no “, which can only be the edition's mistake"""
    if mark.character == '“':
        open_printed_double_marks.append(mark)
    elif mark.character == '”' and not open_printed_double_marks:
        raise ValueError(f"{urn} {mark.reference}: the ” at idx {mark.idx}, in {mark.words_around!r}, closes no “, "
                         f"which can only be the edition's mistake.")
    elif mark.character == '”':
        open_printed_double_marks.pop()
    elif isinstance(reading, _QuotationMarkReading) and \
            (mark.character != '’' or not mark.character_before.isalpha()):
        unfollowed_pair_by_textpart_id[mark.textpart_id] = reading.pair


def _is_after_a_space(mark: PrintedMark) -> bool:
    return mark.character_before == '' or mark.character_before.isspace()


def _opens_by_the_characters_around(mark: PrintedMark) -> bool:
    return _is_after_a_space(mark) and mark.character_after.isalpha()


def _closes_by_the_characters_around(mark: PrintedMark) -> bool:
    before_a_break = not mark.character_after.isalnum()
    can_be_an_apostrophe = mark.character != '"' and mark.character_before.isalpha()
    return not _is_after_a_space(mark) and before_a_break and not can_be_an_apostrophe


def _is_unsettled(mark: PrintedMark) -> bool:
    """Whether unsettled_printed_marks has to say what the mark is"""
    return mark.character in _PAIR_BY_MARK_OF_SEVERAL_READINGS and not mark.is_contraction_apostrophe \
        and not _opens_by_the_characters_around(mark) and not _closes_by_the_characters_around(mark)


def _reading(mark: PrintedMark, answer: UnsettledMark | None, urn: str, problems: List[str]) -> _Reading:
    """Returns what a printed mark is: by its character, or by the characters around it, or by
    unsettled_printed_marks' answer"""
    opens = _opens_by_the_characters_around(mark)
    choices = 'opens or closes' if mark.character == '"' else 'opens, closes or is an apostrophe'
    reading: _Reading
    if mark.character in _PAIR_BY_MARK_OF_ONE_READING:
        reading = _QuotationMarkReading(_PAIR_BY_MARK_OF_ONE_READING[mark.character],
                                        mark.character in _OPENING_MARKS_OF_ONE_READING)
    elif mark.is_contraction_apostrophe:
        reading = _ApostropheReading()
    elif opens or _closes_by_the_characters_around(mark):
        reading = _QuotationMarkReading(_PAIR_BY_MARK_OF_SEVERAL_READINGS[mark.character], opens)
    elif answer is None or answer == UnsettledMark.APOSTROPHE and mark.character == '"':
        problems.append(f"{urn} {mark.reference}: unsettled_printed_marks must say whether the {mark.character} at "
                        f"idx {mark.idx}, in {mark.words_around!r}, {choices}: the characters around it don't")
        reading = _ApostropheReading()
    elif answer == UnsettledMark.APOSTROPHE:
        reading = _ApostropheReading()
    else:
        reading = _QuotationMarkReading(_PAIR_BY_MARK_OF_SEVERAL_READINGS[mark.character],
                                        answer == UnsettledMark.OPENS)
    return reading


def _openings_by_pair(marks: Sequence[Mark], readings: Dict[int, _Reading]) -> Dict[str, float]:
    """Counts the quotations that the edition opens with each pair: a printed opening mark and a chain's rend count
    one, and a straight mark half"""
    openings: Dict[str, float] = defaultdict(float)
    for mark in marks:
        if isinstance(mark, PrintedMark):
            reading = readings[mark.idx]
            if mark.character in _OPENING_MARKS_OF_ONE_READING:
                openings[_PAIR_BY_MARK_OF_ONE_READING[mark.character]] += 1
            elif mark.character in ('"', "'") and isinstance(reading, _QuotationMarkReading):
                openings[reading.pair] += 0.5
        elif mark.opens and mark.pair_by_rend is not None:
            openings[mark.pair_by_rend] += 1
    return openings


def _work_pair(openings: Dict[str, float], quotation: AddedMark, urn: str) -> str:
    """Returns the pair with the most openings, or double with none. Raises on a tie, which no work has yet"""
    ranked = sorted(openings.items(), key=lambda pair_and_openings: -pair_and_openings[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        raise ValueError(f"{urn} {quotation.reference}: the quotation that opens at idx {quotation.idx}, in "
                         f"{quotation.words_around!r}, takes the work's pair, but the edition opens as many "
                         f"quotations with {ranked[0][0]} marks as with {ranked[1][0]}, so its pair can't be counted, "
                         f"which isn't read yet.")
    return ranked[0][0] if ranked else 'double'
