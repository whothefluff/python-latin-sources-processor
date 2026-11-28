"""Reads the text of a TEI edition, as Perseus encodes its poetry, prose and plays, into divisions and blocks of text.
Raises on any structure that it doesn't read, rather than guessing what the structure means."""
import re
import unicodedata
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
from typing import Dict, Iterator, List, NamedTuple, Sequence, Set, Tuple, Union, cast

TEI_NAMESPACE = 'http://www.tei-c.org/ns/1.0'
_TEI = f'{{{TEI_NAMESPACE}}}'
_XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'

#: The kinds of division that the edition and each kind of division can hold, one kind at a time
_DIVISION_KINDS_BY_HOLDER: Dict[str, Tuple[str, ...]] = {
    'edition': ('book', 'poem', 'chapter', 'section', 'act'),
    'book': ('poem', 'chapter', 'section'),
    'poem': ('poem',),
    'chapter': ('section',),
    'act': ('scene',),
}
#: The elements that the edition and each kind of division can hold, besides the edition's own heading
_PARTS_BY_DIVISION_KIND: Dict[str, Tuple[str, ...]] = {
    'edition': ('div', 'l', 'sp', 'milestone', 'lb', 'pb'),
    'book': ('head', 'div', 'l', 'lg', 'p', 'note', 'milestone', 'lb', 'pb'),
    'poem': ('head', 'div', 'l', 'lg', 'sp', 'p', 'note', 'milestone', 'lb', 'pb'),
    'chapter': ('head', 'div', 'p', 'note', 'milestone', 'lb', 'pb'),
    'section': ('head', 'p', 'note', 'milestone', 'lb', 'pb'),
    'act': ('head', 'div', 'note', 'milestone', 'lb', 'pb'),
    'scene': ('head', 'sp', 'l', 'note', 'milestone', 'lb', 'pb'),
    'lg': ('head', 'l', 'lg', 'note', 'milestone', 'lb', 'pb'),
    'sp': ('speaker', 'l', 'lg', 'p', 'note', 'milestone', 'lb', 'pb'),
}
_DIVISION_TYPES_BY_KIND = {'book': 'BOOK', 'poem': 'POEM', 'chapter': 'CHAP', 'section': 'SECT', 'act': 'ACT',
                           'scene': 'SCEN', 'lg': 'LGRP', 'sp': 'SPCH'}
_DIVISION_KIND_NAMES = {'edition': 'edition', 'book': 'book', 'poem': 'poem', 'chapter': 'chapter',
                        'section': 'section', 'act': 'act', 'scene': 'scene', 'lg': 'line group', 'sp': 'speech'}
#: Other names for a poem, which every edition means the same way, with the dataset's type for each
_POEM_TYPES_BY_FOLDED_SUBTYPE = {'satire': 'POEM', 'prologue': 'PROL', 'preface': 'PROL'}
#: A printed volume, which is nothing of the work's: the edition cites the books inside it straight through it
_PRINTED_VOLUME_SUBTYPE = 'part'
#: The kinds of division that the edition numbers with their n
_NUMBERED_DIVISION_KINDS = ('book', 'poem', 'chapter', 'section', 'act', 'scene')
#: The kinds of division that the work's configuration can give another type by their n, such as a prologue
_DIVISION_KINDS_TYPED_BY_N = ('poem', 'act')
#: The kind that a division is read as when the work's configuration gives its subtype a type
_DIVISION_KINDS_BY_TYPE = {_DIVISION_TYPES_BY_KIND[kind]: kind for kind in _NUMBERED_DIVISION_KINDS}
_BLOCK_TYPES_BY_TAG = {'head': 'TITL', 'speaker': 'TITL', 'l': 'VERS', 'p': 'PARA'}
#: Layout and numberings between the parts of the edition or of a division, which are left out wherever they are
_LEFT_OUT_BETWEEN_PARTS_TAGS = ('milestone', 'lb', 'pb')
#: The elements with a division's own text, which a division that holds divisions doesn't have
_TEXT_OF_ITS_OWN_TAGS = ('l', 'lg', 'sp', 'p')
#: A <quote> isn't always a quotation, so it gets no marks yet. A <reg> outside a <choice> has no other spelling
#: beside it to keep
_READ_AS_PLAIN_TEXT_TAGS = ('quote', 'reg')
_TYPOGRAPHY_TAGS = ('hi', 'emph')
_TYPOGRAPHY_RENDS_READ_AS_TEXT = ('uppercase',)
_EDITORIAL_MARKS_BY_TAG = {'add': 'addition', 'del': 'deletion', 'corr': 'correction', 'sic': 'sic'}
_READ_AS_MARKED_TEXT_TAGS = (*_EDITORIAL_MARKS_BY_TAG, 'num')
_READ_AS_TEXT_TAGS = (*_READ_AS_PLAIN_TEXT_TAGS, *_TYPOGRAPHY_TAGS, *_READ_AS_MARKED_TEXT_TAGS)
_QUOTATION_TAGS = ('q',)
_READ_EACH_IN_ITS_OWN_WAY_TAGS = ('choice', 'abbr', 'lb', 'gap', 'note')
_LEFT_OUT_TAGS = ('milestone', 'pb')
#: Read only where it prints another numbering, which is left out like the milestone beside it
_LABEL_TAGS = ('label',)
_INLINE_TAGS = (*_READ_AS_TEXT_TAGS, *_QUOTATION_TAGS, *_READ_EACH_IN_ITS_OWN_WAY_TAGS, *_LEFT_OUT_TAGS, *_LABEL_TAGS)
_LEFT_OUT_OF_AN_ABBREVIATION_TAGS = ('expan',)
_PRINTED_READING_TAGS_BY_CHOICE: Dict[Tuple[str, ...], str] = {('abbr', 'expan'): 'abbr', ('orig', 'reg'): 'orig'}
_OPENING_MARK_PLACEHOLDER, _CLOSING_MARK_PLACEHOLDER = '“', '”'
_LOST_PASSAGE_REASONS_BY_GAP_REASON = {'lost': 'lost', 'omitted': 'omitted', 'ellipsis': 'omitted'}
_BLOCK_TYPES_NO_EDITION_PRINTS_A_DIGIT_IN = ('VERS', 'PARA')
_DIGIT_WITH_THE_WORDS_AROUND_IT = re.compile(r'(?:\S+\s+)?\S*\d\S*(?:\s+\S+)?')
#: A poet can divide a word between two verses, so a verse's hyphen is a printed line's only with a letter after it
_PRINTED_LINE_S_HYPHEN_BY_BLOCK_TYPE = {'PARA': re.compile(r'(?<=[^\W\d_])-'),
                                        'VERS': re.compile(r'(?<=[^\W\d_])-(?=\s*[^\W\d_])')}
_WORD = re.compile(r'\w+')
_LEMMA_ELLIPSIS = re.compile(r'\.\s*\.')


class LostPassage(NamedTuple):
    """A place where the edition marks the text as lost, or as left out"""
    #: lost or omitted
    reason: str


class EditorialMark(NamedTuple):
    """Part of a block's text that the editor added, corrected or marked for deletion, or that the edition prints as
    its source has it (sic): a range of characters in one of its pieces"""
    #: addition, correction, deletion or sic
    kind: str
    piece: int
    start: int
    end: int


class Numeral(NamedTuple):
    """Part of a block's text that the edition tags as a numeral: a range of characters in one of its pieces"""
    piece: int
    start: int
    end: int


class Expansion(NamedTuple):
    """An <expan>'s text, and where its abbreviation is printed: a range of characters in one of its block's pieces"""
    text: str
    piece: int
    start: int
    end: int


class RegularizedSpelling(NamedTuple):
    """A <reg>'s text, and where the spelling that it regularizes is printed: a range of characters in one of its
    block's pieces"""
    text: str
    piece: int
    start: int
    end: int


class AddedQuotationMark(NamedTuple):
    """Where the producer adds a mark to a tagged quotation, before its chain's first element or after its last: a
    character in one of its block's pieces"""
    opens: bool
    pair_by_rend: str | None
    piece: int
    start: int
    end: int


class LemmaMatch(NamedTuple):
    """Where a note's lemma matches the words before it: a range of characters in one of its block's pieces"""
    piece: int
    start: int
    end: int


class Note(NamedTuple):
    """A note of a block's: its text, and the lemma that says which of the block's words it's about, when it has one"""
    text: str
    #: The words of the text that an apparatus's note is about, as its <lem> or <w type="lemma"> repeats them
    lemma: str | None = None
    #: Where the lemma matches the last words before the note, compared without punctuation or case, when it does
    lemma_match: LemmaMatch | None = None


class NoteToCheckAgainstThePage(NamedTuple):
    reference: str
    text: str
    shapes: Tuple[str, ...]


class TextBlock(NamedTuple):
    """A verse, title or paragraph: text that the reader starts on a line of its own"""
    typ: str
    #: A verse's TEI n
    edition_label: str | None
    #: The reference of its tokens: the TEI n of each division above it that the edition cites, then a verse's own.
    #: A speaker's is the reference of the first verse or paragraph of its speech, and that of a heading above which
    #: no division is cited is its division's first verse's or paragraph's
    reference: str
    #: Its text in reading order, without its notes
    pieces: Tuple[Union[str, LostPassage], ...]
    #: Whether the edition marks the whole block for deletion
    deleted: bool
    notes: Tuple[Note, ...]
    #: The parts of its text that the editor added, corrected or marked for deletion (unless the whole block is), and
    #: those that the edition prints as its source has them
    marks: Tuple[EditorialMark, ...] = ()
    numerals: Tuple[Numeral, ...] = ()
    expansions: Tuple[Expansion, ...] = ()
    added_quotation_marks: Tuple[AddedQuotationMark, ...] = ()
    regularized_spellings: Tuple[RegularizedSpelling, ...] = ()
    notes_to_check_against_the_page: Tuple[NoteToCheckAgainstThePage, ...] = ()

    @property
    def name(self) -> str:
        return _name_of(self.pieces)

    def place_in_name_of_the_mark_at(self, piece: int, place_in_piece: int) -> int:
        name_that_ends_with_the_mark = _name_of(
            (*self.pieces[:piece], cast(str, self.pieces[piece])[:place_in_piece + 1]))
        return len(name_that_ends_with_the_mark) - 1


# Editions type dots as text, and none has them between square brackets
_LOST_PASSAGE_IN_A_NAME = '[...]'


def _name_of(pieces: Sequence[Union[str, LostPassage]]) -> str:
    """Whitespace in the XML is layout"""
    text_with_its_lost_passages = ''.join(
        _LOST_PASSAGE_IN_A_NAME if isinstance(piece, LostPassage) else piece for piece in pieces)
    return _with_single_spaces_inside_and_none_around(text_with_its_lost_passages)


def _with_single_spaces_inside_and_none_around(text: str) -> str:
    return ' '.join(text.split())


class Division(NamedTuple):
    """A book, poem, prologue, epilogue, chapter, section, act, scene, line group or speech"""
    typ: str
    #: The TEI n of a book, poem, prologue, epilogue, chapter, section, act or scene
    edition_label: str | None
    #: Its title first, when it has one, then its divisions and blocks in reading order
    parts: Tuple[Union['Division', TextBlock], ...]
    #: Its notes, and its headings in a language other than Latin
    notes: Tuple[str, ...]
    notes_to_check_against_the_page: Tuple[NoteToCheckAgainstThePage, ...] = ()

    @property
    def title(self) -> TextBlock | None:
        first = self.parts[0]
        return first if isinstance(first, TextBlock) and first.typ == 'TITL' else None


class _QuotationMarkToAdd(NamedTuple):
    opens: bool
    pair_by_rend: str | None


class _MarkedText(NamedTuple):
    """Some of a block's text and the elements that mark it, innermost first, until it's joined with the text around
    it"""
    text: str
    marking: Tuple[ET.Element, ...] = ()
    holds_the_place_of: _QuotationMarkToAdd | None = None


class _QuotationChains(NamedTuple):
    """By id: the quotation elements that open a chain, with the pair that its rend gives, those that close one, and
    those whose rend has merge with no chain before them to continue"""
    opening: Dict[int, str | None]
    closing: Set[int]
    continuing_nothing: Set[int]


class _InlineNote(NamedTuple):
    """A <note> where it is in a block's text, until it's found where its lemma matches"""
    text: str
    lemma: str | None
    shapes_to_check_against_the_page: Tuple[str, ...]


_InlinePiece = Union[_MarkedText, LostPassage, _InlineNote]
#: A block's text, its lost passages and its notes, in reading order, before the text is joined
_InlinePieces = List[_InlinePiece]


class _MarkedRange(NamedTuple):
    marking: ET.Element
    piece: int
    start: int
    end: int


class _JoinedText(NamedTuple):
    pieces: Tuple[Union[str, LostPassage], ...]
    marked_ranges: Tuple[_MarkedRange, ...]
    notes: Tuple[Note, ...]
    added_quotation_marks: Tuple[AddedQuotationMark, ...]
    texts_and_shapes_of_notes_to_check_against_the_page: Tuple[Tuple[str, Tuple[str, ...]], ...]


def read_edition(root: ET.Element, cited_division_subtypes: Tuple[str, ...], types_by_n: Dict[str, str],
                 types_by_subtype: Dict[str, str]) -> Tuple[Union[Division, TextBlock], ...]:
    """Returns the divisions of the edition, or its verses and speeches when it holds them straight. The references of
    the tokens are made of the TEI n of the divisions whose subtype is one of cited_division_subtypes, and of the
    verse's. A division whose subtype is in types_by_subtype is read as a division of that type, and a poem or an act
    whose n is in types_by_n gets that type instead of POEM or ACT."""
    body = root.find(f'{_TEI}text/{_TEI}body')
    if body is None:
        raise ValueError("The TEI file has no <text><body>.")
    editions = [child for child in _children(body, 'the body') if _tag(child) != 'pb']
    if len(editions) != 1 or _tag(editions[0]) != 'div' or editions[0].get('type') != 'edition':
        raise ValueError('The body must hold one <div type="edition"> and nothing else.')
    children = _without_printed_volumes(_children(editions[0], 'the edition'))
    first = next((child for child in children if _tag(child) not in _LEFT_OUT_BETWEEN_PARTS_TAGS), None)
    if first is not None and _tag(first) == 'head':
        children.remove(first)  # the work's title, which its header gives
    parts, _, _ = _parts_and_notes(children, 'edition', 'the edition', (), cited_division_subtypes, types_by_n,
                                types_by_subtype, _quotation_chains(body))
    return parts


def _without_printed_volumes(children: List[ET.Element]) -> List[ET.Element]:
    """Returns the edition's children with the children of each printed volume in its place"""
    return [part for child in children
            for part in (_children(child, f"the edition > {_PRINTED_VOLUME_SUBTYPE} {child.get('n')}")
                         if _is_a_printed_volume(child) else (child,))]


def _is_a_printed_volume(element: ET.Element) -> bool:
    return (_tag(element) == 'div' and element.get('type') == 'textpart'
            and element.get('subtype') == _PRINTED_VOLUME_SUBTYPE)


def _quotation_chains(body: ET.Element) -> _QuotationChains:
    """Returns the body's chains of quotations: one whose rend has merge continues the last chain in the chain that
    holds it, as Perseus means it"""
    last_chain_in: Dict[int | None, int] = {}
    last_element_of: Dict[int, int] = {}
    opening: Dict[int, str | None] = {}
    continuing_nothing: Set[int] = set()

    def visit(element: ET.Element, holder: int | None):
        for child in element:
            tag = _tag(child)
            rend = child.get('rend') or ''
            merges = re.search(r'\bmerge\b', rend) is not None
            if tag in _QUOTATION_TAGS and merges and holder not in last_chain_in:
                continuing_nothing.add(id(child))
            if tag in _QUOTATION_TAGS:
                chain = last_chain_in.get(holder, id(child)) if merges else id(child)
                if not merges:
                    opening[chain] = next((pair for pair in ('single', 'double')
                                           if re.search(rf'\b{pair}\b', rend)), None)
                last_chain_in[holder] = chain
                last_element_of[chain] = id(child)
                visit(child, chain)
            elif tag not in ('note', 'expan') and not (tag == 'head' and child.get(_XML_LANG, 'lat') != 'lat'):
                visit(child, holder)

    visit(body, None)
    return _QuotationChains(opening, set(last_element_of.values()), continuing_nothing)


def _tag(element: ET.Element) -> str:
    return element.tag.removeprefix(_TEI) if isinstance(element.tag, str) else ''


def _children(element: ET.Element, where: str) -> List[ET.Element]:
    """Returns the element's children, and raises when it has text outside them"""
    if (element.text or '').strip() or any((child.tail or '').strip() for child in element):
        raise ValueError(f"{where} has text outside its parts, which isn't read.")
    return list(element)


def _division_kind_held(children: List[ET.Element], holder: str, where: str,
                        types_by_subtype: Dict[str, str]) -> str | None:
    """Returns the kind of the divisions among the children of the edition or of a division, or None when there are
    none. Raises when one of them isn't of a kind that the holder holds, or when they're of more than one kind"""
    divisions = [child for child in children if _tag(child) == 'div']
    kinds = {_textpart_kind(child, holder, where, types_by_subtype) for child in divisions}
    if len(kinds) > 1:
        subtypes = sorted({cast(str, child.get('subtype')) for child in divisions})
        raise ValueError(f"{where} holds {' and '.join(f'{subtype}s' for subtype in subtypes)}, but only one kind of "
                         f"division is read in the {_DIVISION_KIND_NAMES[holder]}.")
    return kinds.pop() if kinds else None


def _textpart_kind(element: ET.Element, holder: str, where: str, types_by_subtype: Dict[str, str]) -> str:
    """Returns the kind that the division is read as: its subtype's, a poem for another name of one, or, for a subtype
    of a numbered kind, the kind of the type that the work's configuration gives it"""
    subtype = element.get('subtype', '')
    is_typed = subtype in _NUMBERED_DIVISION_KINDS and subtype in types_by_subtype
    kind = (_DIVISION_KINDS_BY_TYPE[types_by_subtype[subtype]] if is_typed
            else 'poem' if subtype in _POEM_TYPES_BY_FOLDED_SUBTYPE else subtype)
    kinds = _DIVISION_KINDS_BY_HOLDER[holder]
    if _tag(element) != 'div' or element.get('type') != 'textpart' or kind not in kinds:
        typed = f", which types_by_subtype makes {types_by_subtype[subtype]}" if is_typed else ''
        raise ValueError(f"{where} holds <{_tag(element)} type=\"{element.get('type', '')}\" subtype=\"{subtype}\">"
                         f"{typed}, but only {_listed(kinds)} are read there.")
    return kind


def _listed(kinds: Tuple[str, ...]) -> str:
    """Returns the kinds in plain words, such as books, poems and acts"""
    names = [f'{kind}s' for kind in kinds]
    return f"{', '.join(names[:-1])} and {names[-1]}" if len(names) > 1 else names[0]


def _with_its_article(name: str) -> str:
    return 'the edition' if name == 'edition' else f"{'an' if name.startswith('a') else 'a'} {name}"


def _division(element: ET.Element, kind: str, where: str, cited: Tuple[str, ...],
              cited_division_subtypes: Tuple[str, ...], types_by_n: Dict[str, str], types_by_subtype: Dict[str, str],
              chains: _QuotationChains) -> Division:
    """Returns the division, read as one of the kind given. The edition cites it, and an error finds it, by its own
    subtype"""
    n = element.get('n')
    subtype = element.get('subtype', '')
    if kind in _NUMBERED_DIVISION_KINDS:
        if not n:
            raise ValueError(f"{'An' if subtype.startswith('a') else 'A'} {subtype} in {where} has no n.")
        where = f"{where} > {subtype} {n}"
        cited = cited + (n,) if subtype in cited_division_subtypes else cited
    else:
        where = f"{where} > {kind}"
    typ = ((types_by_n.get(n or '') if kind in _DIVISION_KINDS_TYPED_BY_N else None)
           or _POEM_TYPES_BY_FOLDED_SUBTYPE.get(subtype) or _DIVISION_TYPES_BY_KIND[kind])
    parts, notes, notes_to_check_against_the_page = _parts_and_notes(
        _children(element, where), kind, where, cited, cited_division_subtypes, types_by_n, types_by_subtype, chains)
    return Division(typ, n if kind in _NUMBERED_DIVISION_KINDS else None, parts, notes,
                    notes_to_check_against_the_page)


def _parts_and_notes(children: List[ET.Element], holder: str, where: str, cited: Tuple[str, ...],
                     cited_division_subtypes: Tuple[str, ...], types_by_n: Dict[str, str],
                     types_by_subtype: Dict[str, str], chains: _QuotationChains
                     ) -> Tuple[Tuple[Union[Division, TextBlock], ...], Tuple[str, ...],
                                Tuple[NoteToCheckAgainstThePage, ...]]:
    """Returns the divisions and blocks that the children of the edition or of a division are, its title first, its
    notes, and its notes to check against the page"""
    for child in children:
        if _tag(child) not in _PARTS_BY_DIVISION_KIND[holder]:
            raise _not_read(child, where, f"in {_with_its_article(_DIVISION_KIND_NAMES[holder])}")
    division_kind = _division_kind_held(children, holder, where, types_by_subtype)
    text_of_its_own = next((child for child in children if _tag(child) in _TEXT_OF_ITS_OWN_TAGS), None)
    if division_kind is not None and text_of_its_own is not None:
        raise ValueError(f"{where} holds divisions and <{_tag(text_of_its_own)}>, but only divisions or text of its "
                         f"own are read in {_with_its_article(_DIVISION_KIND_NAMES[holder])}, not both.")
    parts: List[Union[Division, TextBlock]] = []
    notes: List[str] = []
    notes_to_check_against_the_page: List[NoteToCheckAgainstThePage] = []
    # A speaker, or a heading above which no division is cited
    title_placed_by_its_text: ET.Element | None = None
    for child in children:
        tag = _tag(child)
        if tag == 'note':
            if _lemma(child, where) is not None:
                raise ValueError(f"{where} holds a note with a lemma outside a verse, title or paragraph, which isn't "
                                 "read.")
            text = _note_text(child, where)
            notes.append(text)
            notes_to_check_against_the_page.append(
                NoteToCheckAgainstThePage('.'.join(cited), ' '.join(text.split()), ('outside any block',)))
        elif tag == 'head' and child.get(_XML_LANG, 'lat') != 'lat':
            notes.append(''.join(child.itertext()).strip())
        elif tag in ('head', 'speaker'):
            if parts or title_placed_by_its_text is not None:
                raise ValueError(f"{where} has a title after its text or another title.")
            if tag == 'head' and cited:
                parts.append(_block(child, 'TITL', where, cited, chains))
            else:
                title_placed_by_its_text = child
        elif tag == 'div':
            parts.append(_division(child, cast(str, division_kind), where, cited, cited_division_subtypes,
                                   types_by_n, types_by_subtype, chains))
        elif tag in ('lg', 'sp'):
            parts.append(_division(child, tag, where, cited, cited_division_subtypes, types_by_n, types_by_subtype,
                                   chains))
        elif tag in ('l', 'p'):
            parts.append(_block(child, _BLOCK_TYPES_BY_TAG[tag], where, cited, chains))
    first_said = next(_blocks_said(parts), None)
    if first_said is None and (title_placed_by_its_text is not None or not parts):
        raise ValueError(f"{where} has no text.")
    if title_placed_by_its_text is not None:
        parts.insert(0, _block(title_placed_by_its_text, 'TITL', where, cited, chains,
                               cast(TextBlock, first_said).reference))
    return tuple(parts), tuple(notes), tuple(notes_to_check_against_the_page)


def _blocks_said(parts: Sequence[Union[Division, TextBlock]]) -> Iterator[TextBlock]:
    """Yields the verses and paragraphs among the parts, also inside their divisions, in reading order"""
    for part in parts:
        if isinstance(part, Division):
            yield from _blocks_said(part.parts)
        elif part.typ != 'TITL':
            yield part


def _block(element: ET.Element, typ: str, where: str, cited: Tuple[str, ...], chains: _QuotationChains,
           reference: str | None = None) -> TextBlock:
    """Returns the block, with the reference given, or else one made of what's cited and a verse's n"""
    tag = _tag(element)
    n = element.get('n') if typ == 'VERS' else None
    if typ == 'VERS' and not n:
        raise ValueError(f"A line in {where} has no n.")
    where = f"{where} > {tag}" + (f" {n}" if n else '')
    reference = reference or '.'.join(cited + ((n,) if n else ()))
    if not reference:
        raise ValueError(f"{where} would have no reference: no division above it is cited.")
    deletion = _whole_deletion(element)
    joined = _joined(_inline(deletion if deletion is not None else element, where, _INLINE_TAGS, chains))
    if not any(isinstance(piece, LostPassage) or piece.strip() for piece in joined.pieces):
        raise ValueError(f"{where} has no text.")
    texts = tuple(piece for piece in joined.pieces if isinstance(piece, str))
    digit = _DIGIT_WITH_THE_WORDS_AROUND_IT.search(' '.join(texts))
    if typ in _BLOCK_TYPES_NO_EDITION_PRINTS_A_DIGIT_IN and digit is not None:
        raise ValueError(f"{where} has a digit in its text, in {digit.group()!r}, which can only be the edition's "
                         f"mistake.")
    hyphen = _first_printed_line_s_hyphen(texts, typ)
    if hyphen is not None:
        raise ValueError(f"{where} has a hyphen after a letter in its text, in {_words_around(hyphen)!r}, which can "
                         f"only be the edition's mistake.")
    combining_mark = _first_combining_mark(texts)
    if combining_mark is not None:
        raise ValueError(f"{where} has a combining mark in its text, in {_words_around(combining_mark)!r}, which "
                         f"isn't read yet.")
    marks = tuple(EditorialMark(_EDITORIAL_MARKS_BY_TAG[_tag(marking)], piece, start, end)
                  for marking, piece, start, end in joined.marked_ranges if _tag(marking) in _EDITORIAL_MARKS_BY_TAG)
    numerals = tuple(Numeral(piece, start, end)
                     for marking, piece, start, end in joined.marked_ranges if _tag(marking) == 'num')
    expansions = tuple(Expansion(text, piece, start, end)
                       for text, piece, start, end in _kept_readings(joined, 'expan'))
    regularized_spellings = tuple(RegularizedSpelling(text, piece, start, end)
                                  for text, piece, start, end in _kept_readings(joined, 'reg'))
    notes_to_check_against_the_page = tuple(
        NoteToCheckAgainstThePage(reference, ' '.join(text.split()), shapes)
        for text, shapes in joined.texts_and_shapes_of_notes_to_check_against_the_page)
    return TextBlock(typ, n, reference, joined.pieces, deletion is not None, joined.notes, marks, numerals, expansions,
                     joined.added_quotation_marks, regularized_spellings, notes_to_check_against_the_page)


class _CharacterOfAText(NamedTuple):
    text: str
    place: int


def _first_printed_line_s_hyphen(texts: Tuple[str, ...], typ: str) -> _CharacterOfAText | None:
    pattern = _PRINTED_LINE_S_HYPHEN_BY_BLOCK_TYPE.get(typ)
    return None if pattern is None else next(
        (_CharacterOfAText(text, hyphen.start()) for text in texts for hyphen in pattern.finditer(text)), None)


def _first_combining_mark(texts: Tuple[str, ...]) -> _CharacterOfAText | None:
    return next((_CharacterOfAText(text, place) for text in texts for place, character in enumerate(text)
                 if unicodedata.category(character).startswith('M')), None)


def _words_around(character: _CharacterOfAText) -> str:
    """Returns the word that holds the character, with the word before it and the word after it"""
    before = cast(re.Match[str], re.search(r'(?:\S+\s+)?\S*\Z', character.text[:character.place])).group()
    after = cast(re.Match[str], re.match(r'\S*(?:\s+\S+)?', character.text[character.place + 1:])).group()
    return _with_single_spaces_inside_and_none_around(before + character.text[character.place] + after)


def _whole_deletion(element: ET.Element) -> ET.Element | None:
    """Returns the <del> that holds all of the element's text, if one does"""
    children = list(element)
    whole = (len(children) == 1 and _tag(children[0]) == 'del' and not (element.text or '').strip()
             and not (children[0].tail or '').strip())
    return children[0] if whole else None


def _inline(element: ET.Element, where: str, tags: Tuple[str, ...], chains: _QuotationChains) -> _InlinePieces:
    """Returns the element's text, with its lost passages and its notes where they are and the elements that mark
    its parts. Raises on any element that isn't one of tags, and on typography whose rend isn't read.
    A line break separates two words, a page break joins the text around it, an abbreviation is read as printed,
    without its expansion, and so is a word without the regularized spelling beside it, and a quotation has the
    places of the marks that open and close its chain."""
    pieces: _InlinePieces = [_MarkedText(element.text or '')]
    for child in element:
        tag = _tag(child)
        if tag not in tags or tag in _LABEL_TAGS and not _is_a_label_of_another_numbering(child):
            raise _not_read(child, where, 'there')
        if tag in _TYPOGRAPHY_TAGS and child.get('rend') not in _TYPOGRAPHY_RENDS_READ_AS_TEXT:
            raise ValueError(f"{where} holds <{tag} rend=\"{child.get('rend', '')}\">, but only "
                             f"{' and '.join(_TYPOGRAPHY_RENDS_READ_AS_TEXT)} typography is read there.")
        if tag in _READ_AS_TEXT_TAGS:
            pieces.extend(_marked_by(piece, child) if tag in _READ_AS_MARKED_TEXT_TAGS else piece
                          for piece in _inline(child, where, tags, chains))
        elif tag in _QUOTATION_TAGS:
            pieces.extend(_quoted(child, where, tags, chains))
        elif tag == 'choice':
            pieces.extend(_marked_by(piece, child)
                          for piece in _inline(_printed_reading_of(child, where), where, (), chains))
        elif tag == 'abbr':
            # TODO(whothefluff): Amphitruo, Curculio and Menaechmi put the <expan> inside its <abbr>, where TEI has the
            #  two side by side in a <choice>. Read as a <choice> until their editions are fixed
            if child.find(f'{_TEI}expan') is None:
                raise ValueError(f"{where} holds an <abbr> without an <expan>, which isn't read there.")
            pieces.extend(_marked_by(piece, child)
                          for piece in _inline(child, where, _LEFT_OUT_OF_AN_ABBREVIATION_TAGS, chains))
        elif tag == 'lb':
            pieces.append(_MarkedText(' '))
        elif tag == 'gap':
            reason = _LOST_PASSAGE_REASONS_BY_GAP_REASON.get(child.get('reason', ''))
            if reason is None:
                *reasons, last = _LOST_PASSAGE_REASONS_BY_GAP_REASON
                raise ValueError(f"{where} has a gap whose reason isn't {', '.join(reasons)} or {last}.")
            pieces.append(LostPassage(reason))
        elif tag == 'note':
            pieces.append(_InlineNote(_note_text(child, where), _lemma(child, where),
                                      _shapes_to_check_against_the_page(child)))
        pieces.append(_MarkedText(child.tail or ''))
    return pieces


def _is_a_label_of_another_numbering(label: ET.Element) -> bool:
    return (label.get('type') or '').startswith('alt_') or label.get('place') == 'margin'


def _not_read(element: ET.Element, where: str, place: str) -> ValueError:
    """Returns the error for an element that isn't read in the place given, which names the edition's fix for a label
    without a type: code can't tell its heading from a number"""
    if _tag(element) in _LABEL_TAGS and element.get('type') is None and not _is_a_label_of_another_numbering(element):
        return ValueError(f"{where} holds a <label> without a type, which the edition should give one, or the element "
                          f"that it stands for.")
    return ValueError(f"{where} holds <{_tag(element)}>, which isn't read {place}.")


def _quoted(element: ET.Element, where: str, tags: Tuple[str, ...], chains: _QuotationChains) -> _InlinePieces:
    """Returns the quotation's text between the places of its chain's marks, where it opens or closes the chain.
    Raises on a merge with no chain to continue"""
    if id(element) in chains.continuing_nothing:
        raise ValueError(f"{where} holds a <{_tag(element)} rend=\"{element.get('rend')}\"> that continues no "
                         f"quotation before it, which isn't read.")
    opening_mark = _QuotationMarkToAdd(opens=True, pair_by_rend=chains.opening.get(id(element)))
    closing_mark = _QuotationMarkToAdd(opens=False, pair_by_rend=None)
    opening = [_MarkedText(_OPENING_MARK_PLACEHOLDER, holds_the_place_of=opening_mark)] \
        if id(element) in chains.opening else []
    closing = [_MarkedText(_CLOSING_MARK_PLACEHOLDER, holds_the_place_of=closing_mark)] \
        if id(element) in chains.closing else []
    return [*opening, *_inline(element, where, tags, chains), *closing]


def _marked_by(piece: _InlinePiece, element: ET.Element) -> _InlinePiece:
    """Returns the text with the element among those that mark it, or the lost passage or note as it is"""
    return piece._replace(marking=piece.marking + (element,)) if isinstance(piece, _MarkedText) else piece


def _printed_reading_of(choice: ET.Element, where: str) -> ET.Element:
    """Returns the reading of a <choice> that the edition prints: the <abbr> of an abbreviation and its <expan>, or
    the <orig> of a spelling and its <reg>. Raises on any other <choice>"""
    readings = tuple(sorted(_tag(reading) for reading in _children(choice, where)))
    if readings not in _PRINTED_READING_TAGS_BY_CHOICE:
        raise ValueError(f"{where} holds a <choice> of {' and '.join(f'<{tag}>' for tag in readings)}, which isn't "
                         f"read there.")
    return cast(ET.Element, choice.find(f'{_TEI}{_PRINTED_READING_TAGS_BY_CHOICE[readings]}'))


def _kept_readings(joined: _JoinedText, tag: str) -> Iterator[Tuple[str, int, int, int]]:
    """Yields the text of each <expan> or <reg>, whichever the tag is, that a <choice> has beside the reading that
    the edition prints, or that an <abbr> holds, with its spaces collapsed, and the piece and the range of
    characters of that printed reading"""
    for marking, piece, start, end in joined.marked_ranges:
        reading = marking.find(f'{_TEI}{tag}') if _tag(marking) in ('choice', 'abbr') else None
        if reading is not None:
            yield ' '.join(''.join(reading.itertext()).split()), piece, start, end


def _joined(inline_pieces: _InlinePieces) -> _JoinedText:
    joined: List[Union[str, LostPassage]] = []
    ranges_by_element_id_and_piece: Dict[Tuple[int, int], Tuple[ET.Element, int, int]] = {}
    notes: List[Note] = []
    texts_and_shapes_of_notes_to_check_against_the_page: List[Tuple[str, Tuple[str, ...]]] = []
    added_quotation_marks: List[AddedQuotationMark] = []
    for position, inline_piece in enumerate(inline_pieces):
        last = joined[-1] if joined else None
        if isinstance(inline_piece, _InlineNote):
            text_before = last if isinstance(last, str) else ''
            notes.append(_note(inline_piece, text_before, len(joined) - 1))
            text_after = _text_joined_after(inline_pieces, position)
            stands_between_two_letters = text_before[-1:].isalpha() and text_after[:1].isalpha()
            shapes = (*inline_piece.shapes_to_check_against_the_page,
                      *(('between two letters',) if stands_between_two_letters else ()))
            if shapes:
                texts_and_shapes_of_notes_to_check_against_the_page.append((inline_piece.text, shapes))
        elif isinstance(inline_piece, LostPassage):
            joined.append(inline_piece)
        elif inline_piece.text and isinstance(last, str):
            joined[-1] = last + inline_piece.text
        elif inline_piece.text:
            joined.append(inline_piece.text)
        if isinstance(inline_piece, _MarkedText) and inline_piece.text:
            index, end = len(joined) - 1, len(cast(str, joined[-1]))
            for element in inline_piece.marking:
                start = ranges_by_element_id_and_piece.get((id(element), index),
                                                           (element, end - len(inline_piece.text), end))[1]
                ranges_by_element_id_and_piece[(id(element), index)] = (element, start, end)
            if inline_piece.holds_the_place_of is not None:
                added_quotation_marks.append(AddedQuotationMark(
                    inline_piece.holds_the_place_of.opens, inline_piece.holds_the_place_of.pair_by_rend, index,
                    end - 1, end))
    marked_ranges = tuple(_MarkedRange(element, index, start, end)
                          for (_, index), (element, start, end) in ranges_by_element_id_and_piece.items())
    return _JoinedText(tuple(joined), marked_ranges, tuple(notes), tuple(added_quotation_marks),
                       tuple(texts_and_shapes_of_notes_to_check_against_the_page))


def _text_joined_after(inline_pieces: _InlinePieces, position: int) -> str:
    """Returns the first text after the piece at the position, which the walker joins to the text before it, or nothing
    where a lost passage comes first"""
    following = next((piece for piece in inline_pieces[position + 1:]
                      if isinstance(piece, LostPassage) or isinstance(piece, _MarkedText) and piece.text), None)
    return following.text if isinstance(following, _MarkedText) else ''


def _lemma(note: ET.Element, where: str) -> str | None:
    """Returns the words of the text that the note is about, as its <lem> or <w type="lemma"> repeats them. Raises on a
    note with more than one"""
    lemmas = [*note.iterfind(f'.//{_TEI}app/{_TEI}lem'), *note.iterfind(f'.//{_TEI}w[@type="lemma"]')]
    if len(lemmas) > 1:
        raise ValueError(f"{where} holds a note with {len(lemmas)} lemmas, but only one is read.")
    return ''.join(lemmas[0].itertext()) if lemmas else None


def _note(note: _InlineNote, text_before: str, piece_index: int) -> Note:
    """Returns the note, with where its lemma matches text_before, when it does. text_before is the block's text before
    the note since its last lost passage, so a lemma that matches only words before that matches nothing"""
    match_range = _range_of_last_words_matching(note.lemma, text_before) if note.lemma is not None else None
    return Note(note.text, note.lemma, LemmaMatch(piece_index, *match_range) if match_range is not None else None)


def _range_of_last_words_matching(lemma: str, text: str) -> Tuple[int, int] | None:
    """Returns the characters of text from the first to the last of the words that the lemma matches, compared
    without punctuation or case: the last such words, when it matches more than once. When two dots or more, spaced
    or not (... or . .), split the lemma into runs of words, each run matches before the next one, without sharing a
    word with it"""
    text_words = list(_WORD.finditer(text))
    lowered_text_words = [word.group().lower() for word in text_words]
    lemma_runs = [run for run in (_WORD.findall(stretch.lower()) for stretch in _LEMMA_ELLIPSIS.split(lemma)) if run]
    if not lemma_runs:
        return None
    run_starts: List[int] = []
    next_run_start = len(text_words)
    for run in reversed(lemma_runs):
        run_start = next((index for index in range(next_run_start - len(run), -1, -1)
                          if lowered_text_words[index:index + len(run)] == run), None)
        if run_start is None:
            return None
        run_starts.insert(0, run_start)
        next_run_start = run_start
    return text_words[run_starts[0]].start(), text_words[run_starts[-1] + len(lemma_runs[-1]) - 1].end()


def _shapes_to_check_against_the_page(note: ET.Element) -> Tuple[str, ...]:
    is_marginal = any('marg' in note.get(attribute, '').lower() for attribute in ('n', 'type', 'place'))
    holds_a_verse_or_a_paragraph = note.find(f'.//{_TEI}l') is not None or note.find(f'.//{_TEI}p') is not None
    return tuple(shape for shape, applies in (('marginal', is_marginal),
                                              ('holding a verse or a paragraph', holds_a_verse_or_a_paragraph))
                 if applies)


def _note_text(note: ET.Element, where: str) -> str:
    text = ''.join(note.itertext()).strip()
    if not text:
        raise ValueError(f"{where} holds an empty note, which the edition should fill or leave out.")
    return text
