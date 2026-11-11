"""Reads the text of a TEI edition, as Perseus encodes its poetry, prose and plays, into divisions and blocks of text.
Raises on any structure that it doesn't read, rather than guessing what the structure means."""
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
from typing import Dict, Iterator, List, NamedTuple, Sequence, Tuple, Union, cast

TEI_NAMESPACE = 'http://www.tei-c.org/ns/1.0'
_TEI = f'{{{TEI_NAMESPACE}}}'
_XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'

#: The kinds of division that the edition and each kind of division can hold, one kind at a time
_DIVISION_KINDS_BY_HOLDER: Dict[str, Tuple[str, ...]] = {
    'edition': ('book', 'poem', 'act'),
    'book': ('poem', 'chapter'),
    'chapter': ('section',),
    'act': ('scene',),
}
#: The elements that each kind of division can hold
_PARTS_BY_DIVISION_KIND: Dict[str, Tuple[str, ...]] = {
    'book': ('head', 'div', 'note', 'milestone', 'lb', 'pb'),
    'poem': ('head', 'l', 'lg', 'sp', 'p', 'note', 'milestone', 'lb', 'pb'),
    'chapter': ('head', 'div', 'note', 'milestone', 'lb', 'pb'),
    'section': ('head', 'p', 'note', 'milestone', 'lb', 'pb'),
    'act': ('head', 'div', 'note', 'milestone', 'lb', 'pb'),
    'scene': ('head', 'sp', 'note', 'milestone', 'lb', 'pb'),
    'lg': ('head', 'l', 'lg', 'note', 'milestone', 'lb', 'pb'),
    'sp': ('speaker', 'l', 'lg', 'p', 'note', 'milestone', 'lb', 'pb'),
}
_DIVISION_TYPES_BY_KIND = {'book': 'BOOK', 'poem': 'POEM', 'chapter': 'CHAP', 'section': 'SECT', 'act': 'ACT',
                           'scene': 'SCEN', 'lg': 'LGRP', 'sp': 'SPCH'}
_DIVISION_KIND_NAMES = {'edition': 'edition', 'book': 'book', 'poem': 'poem', 'chapter': 'chapter',
                        'section': 'section', 'act': 'act', 'scene': 'scene', 'lg': 'line group', 'sp': 'speech'}
#: The kinds of division that the edition numbers with their n
_NUMBERED_DIVISION_KINDS = ('book', 'poem', 'chapter', 'section', 'act', 'scene')
#: The kinds of division that the work's configuration can give another type by their n, such as a prologue
_DIVISION_KINDS_TYPED_BY_N = ('poem', 'act')
_BLOCK_TYPES_BY_TAG = {'head': 'TITL', 'speaker': 'TITL', 'l': 'VERS', 'p': 'PARA'}
#: The elements that a block can hold in its text
_INLINE_TAGS = ('q', 'quote', 'hi', 'emph', 'gap', 'note', 'milestone', 'add', 'del', 'sic', 'num', 'abbr', 'lb', 'pb')
#: The elements whose text is read as the text around it
_READ_AS_TEXT_TAGS = ('q', 'quote', 'hi', 'emph', 'sic', 'add', 'del', 'num')
#: The reasons for a gap that are read, which the gap's supplementary entry keeps
_GAP_REASONS = ('lost', 'omitted')
_TYPOGRAPHY_TAGS = ('hi', 'emph')
_TYPOGRAPHY_RENDS_READ_AS_TEXT = ('uppercase',)


class LostPassage(NamedTuple):
    """A place where the edition marks the text as lost, or as left out"""
    #: lost or omitted
    reason: str


class EditorialMark(NamedTuple):
    """Part of a block's text that the editor added or marked for deletion: a range of characters in one of its
    pieces"""
    #: addition or deletion
    kind: str
    piece: int
    start: int
    end: int


class Numeral(NamedTuple):
    """Part of a block's text that the edition tags as a numeral: a range of characters in one of its pieces"""
    piece: int
    start: int
    end: int


class TextBlock(NamedTuple):
    """A verse, title or paragraph: text that the reader starts on a line of its own"""
    typ: str
    #: A verse's TEI n
    edition_label: str | None
    #: The reference of its tokens: the TEI n of each division above it that the edition cites, then a verse's own.
    #: A speaker's is the reference of the first verse or paragraph of its speech
    reference: str
    #: Its text in reading order, without its notes
    pieces: Tuple[Union[str, LostPassage], ...]
    #: Whether the edition marks the whole block for deletion
    deleted: bool
    notes: Tuple[str, ...]
    #: The parts of its text that the editor added or marked for deletion, when not the whole block
    marks: Tuple[EditorialMark, ...] = ()
    numerals: Tuple[Numeral, ...] = ()

    @property
    def printed_text(self) -> str:
        """Its text as the edition prints it, without its notes and lost passages"""
        return ''.join(piece for piece in self.pieces if isinstance(piece, str))

    @property
    def text(self) -> str:
        """Its printed text without the whitespace around it"""
        return self.printed_text.strip()


class Division(NamedTuple):
    """A book, poem, prologue, epilogue, chapter, section, act, scene, line group or speech"""
    typ: str
    #: The TEI n of a book, poem, prologue, epilogue, chapter, section, act or scene
    edition_label: str | None
    #: Its title first, when it has one, then its divisions and blocks in reading order
    parts: Tuple[Union['Division', TextBlock], ...]
    #: Its notes, and its headings in a language other than Latin
    notes: Tuple[str, ...]

    @property
    def title(self) -> TextBlock | None:
        first = self.parts[0]
        return first if isinstance(first, TextBlock) and first.typ == 'TITL' else None


#: The kind of editorial mark of each element that marks part of a block's text
_EDITORIAL_MARKS_BY_TAG = {'add': 'addition', 'del': 'deletion'}
#: The elements that mark part of a block's text: the editor's marks, and numerals
_MARKING_TAGS = (*_EDITORIAL_MARKS_BY_TAG, 'num')


class _MarkedText(NamedTuple):
    """Some of a block's text and the elements that mark it, innermost first, until it's joined with the text around
    it"""
    text: str
    marking: Tuple[ET.Element, ...] = ()


def read_edition(root: ET.Element, cited_division_subtypes: Tuple[str, ...],
                 types_by_n: Dict[str, str]) -> Tuple[Division, ...]:
    """Returns the books, poems or acts of the edition. The references of the tokens are made of the TEI n of the
    divisions whose subtype is one of cited_division_subtypes, and of the verse's. A poem or an act whose n is in
    types_by_n gets that type instead of POEM or ACT."""
    body = root.find(f'{_TEI}text/{_TEI}body')
    if body is None:
        raise ValueError("The TEI file has no <text><body>.")
    editions = [child for child in _children(body, 'the body') if _tag(child) != 'pb']
    if len(editions) != 1 or _tag(editions[0]) != 'div' or editions[0].get('type') != 'edition':
        raise ValueError('The body must hold one <div type="edition"> and nothing else.')
    parts = [child for child in _children(editions[0], 'the edition') if _tag(child) != 'pb']
    children = parts[1:] if parts and _tag(parts[0]) == 'head' else parts  # the work's title, which its header gives
    if not children:
        raise ValueError("The edition is empty.")
    kind = cast(str, _division_kind_held(children, 'edition', 'the edition'))
    return tuple(_division(child, kind, 'the edition', (), cited_division_subtypes, types_by_n) for child in children)


def _tag(element: ET.Element) -> str:
    return element.tag.removeprefix(_TEI) if isinstance(element.tag, str) else ''


def _children(element: ET.Element, where: str) -> List[ET.Element]:
    """Returns the element's children, and raises when it has text outside them"""
    if (element.text or '').strip() or any((child.tail or '').strip() for child in element):
        raise ValueError(f"{where} has text outside its parts, which isn't read.")
    return list(element)


def _division_kind_held(children: List[ET.Element], holder: str, where: str) -> str | None:
    """Returns the kind of the divisions among the children of the edition or of a division, or None when there are
    none. Every child of the edition is a division. Raises when one of them isn't of a kind that the holder holds, or
    when they're of more than one kind"""
    kinds = {_textpart_kind(child, holder, where) for child in children if holder == 'edition' or _tag(child) == 'div'}
    if len(kinds) > 1:
        raise ValueError(f"{where} holds {' and '.join(f'{kind}s' for kind in sorted(kinds))}, but only one kind of "
                         f"division is read in the {_DIVISION_KIND_NAMES[holder]}.")
    return kinds.pop() if kinds else None


def _textpart_kind(element: ET.Element, holder: str, where: str) -> str:
    kind = element.get('subtype', '')
    kinds = _DIVISION_KINDS_BY_HOLDER[holder]
    if _tag(element) != 'div' or element.get('type') != 'textpart' or kind not in kinds:
        raise ValueError(f"{where} holds <{_tag(element)} type=\"{element.get('type', '')}\" subtype=\"{kind}\">, "
                         f"but only {_listed(kinds)} are read there.")
    return kind


def _listed(kinds: Tuple[str, ...]) -> str:
    """Returns the kinds in plain words, such as books, poems and acts"""
    names = [f'{kind}s' for kind in kinds]
    return f"{', '.join(names[:-1])} and {names[-1]}" if len(names) > 1 else names[0]


def _division(element: ET.Element, kind: str, where: str, cited: Tuple[str, ...],
              cited_division_subtypes: Tuple[str, ...], types_by_n: Dict[str, str]) -> Division:
    n = element.get('n')
    if kind in _NUMBERED_DIVISION_KINDS:
        if not n:
            raise ValueError(f"{'An' if kind.startswith('a') else 'A'} {kind} in {where} has no n.")
        where = f"{where} > {kind} {n}"
        cited = cited + (n,) if kind in cited_division_subtypes else cited
    else:
        where = f"{where} > {kind}"
    typ = (types_by_n.get(n or '') if kind in _DIVISION_KINDS_TYPED_BY_N else None) or _DIVISION_TYPES_BY_KIND[kind]
    children = _children(element, where)
    for child in children:
        if _tag(child) not in _PARTS_BY_DIVISION_KIND[kind]:
            raise ValueError(f"{where} holds <{_tag(child)}>, which isn't read in a {_DIVISION_KIND_NAMES[kind]}.")
    division_kind = _division_kind_held(children, kind, where)
    parts: List[Union[Division, TextBlock]] = []
    notes: List[str] = []
    speaker: ET.Element | None = None
    for child in children:
        tag = _tag(child)
        if tag == 'note':
            notes.append(_note_text(child))
        elif tag == 'head' and child.get(_XML_LANG, 'lat') != 'lat':
            notes.append(''.join(child.itertext()).strip())
        elif tag in ('head', 'speaker'):
            if parts or speaker is not None:
                raise ValueError(f"{where} has a title after its text or another title.")
            if tag == 'head':
                parts.append(_block(child, 'TITL', where, cited))
            else:
                speaker = child
        elif tag == 'div':
            parts.append(_division(child, cast(str, division_kind), where, cited, cited_division_subtypes,
                                   types_by_n))
        elif tag in ('lg', 'sp'):
            parts.append(_division(child, tag, where, cited, cited_division_subtypes, types_by_n))
        elif tag in ('l', 'p'):
            parts.append(_block(child, _BLOCK_TYPES_BY_TAG[tag], where, cited))
    first_said = next(_blocks_said(parts), None)
    if first_said is None and (speaker is not None or not parts):
        raise ValueError(f"{where} has no text.")
    if speaker is not None:
        parts.insert(0, _block(speaker, 'TITL', where, cited, cast(TextBlock, first_said).reference))
    return Division(typ, n if kind in _NUMBERED_DIVISION_KINDS else None, tuple(parts), tuple(notes))


def _blocks_said(parts: Sequence[Union[Division, TextBlock]]) -> Iterator[TextBlock]:
    """Yields the verses and paragraphs among the parts, also inside their divisions, in reading order"""
    for part in parts:
        if isinstance(part, Division):
            yield from _blocks_said(part.parts)
        elif part.typ != 'TITL':
            yield part


def _block(element: ET.Element, typ: str, where: str, cited: Tuple[str, ...],
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
    pieces, notes = _inline(deletion if deletion is not None else element, where, _INLINE_TAGS)
    joined, marks, numerals = _joined(pieces)
    if not any(isinstance(piece, LostPassage) or piece.strip() for piece in joined):
        raise ValueError(f"{where} has no text.")
    return TextBlock(typ, n, reference, joined, deletion is not None, notes, marks, numerals)


def _whole_deletion(element: ET.Element) -> ET.Element | None:
    """Returns the <del> that holds all of the element's text, if one does"""
    children = list(element)
    whole = (len(children) == 1 and _tag(children[0]) == 'del' and not (element.text or '').strip()
             and not (children[0].tail or '').strip())
    return children[0] if whole else None


def _inline(element: ET.Element, where: str,
            tags: Tuple[str, ...]) -> Tuple[List[Union[_MarkedText, LostPassage]], Tuple[str, ...]]:
    """Returns the element's text, with its lost passages where they are and the elements that mark its parts, and
    its notes. Raises on any element that isn't one of tags, and on typography whose rend isn't read.
    A line break separates two words, a page break joins the text around it, and an abbreviation is read as printed,
    without its expansion."""
    pieces: List[Union[_MarkedText, LostPassage]] = [_MarkedText(element.text or '')]
    notes: List[str] = []
    for child in element:
        tag = _tag(child)
        if tag not in tags:
            raise ValueError(f"{where} holds <{tag}>, which isn't read there.")
        if tag in _TYPOGRAPHY_TAGS and child.get('rend') not in _TYPOGRAPHY_RENDS_READ_AS_TEXT:
            raise ValueError(f"{where} holds <{tag} rend=\"{child.get('rend', '')}\">, but only "
                             f"{' and '.join(_TYPOGRAPHY_RENDS_READ_AS_TEXT)} typography is read there.")
        if tag in _READ_AS_TEXT_TAGS:
            inner, inner_notes = _inline(child, where, tags)
            pieces.extend(_marked_by(piece, child) if tag in _MARKING_TAGS else piece for piece in inner)
            notes.extend(inner_notes)
        elif tag == 'abbr':
            pieces.extend(_inline(child, where, ('expan',))[0])
        elif tag == 'lb':
            pieces.append(_MarkedText(' '))
        elif tag == 'gap':
            if child.get('reason') not in _GAP_REASONS:
                raise ValueError(f"{where} has a gap whose reason isn't {' or '.join(_GAP_REASONS)}.")
            pieces.append(LostPassage(cast(str, child.get('reason'))))
        elif tag == 'note':
            notes.append(_note_text(child))
        pieces.append(_MarkedText(child.tail or ''))
    return pieces, tuple(notes)


def _marked_by(piece: Union[_MarkedText, LostPassage], element: ET.Element) -> Union[_MarkedText, LostPassage]:
    """Returns the text with the element among those that mark it, or the lost passage as it is"""
    return piece._replace(marking=piece.marking + (element,)) if isinstance(piece, _MarkedText) else piece


def _joined(pieces: List[Union[_MarkedText, LostPassage]]) -> Tuple[Tuple[Union[str, LostPassage], ...],
                                                                     Tuple[EditorialMark, ...], Tuple[Numeral, ...]]:
    """Returns the pieces with the text between two lost passages in one piece, and no empty ones, and where the
    editor's marks and the numerals are in them: one range for each marking element in each piece"""
    joined: List[Union[str, LostPassage]] = []
    #: The marking elements, by their id and the piece, with their range in it
    ranges: Dict[Tuple[int, int], Tuple[ET.Element, int, int]] = {}
    for piece in pieces:
        last = joined[-1] if joined else None
        if isinstance(piece, LostPassage):
            joined.append(piece)
        elif piece.text and isinstance(last, str):
            joined[-1] = last + piece.text
        elif piece.text:
            joined.append(piece.text)
        if isinstance(piece, _MarkedText) and piece.text:
            index, end = len(joined) - 1, len(cast(str, joined[-1]))
            for element in piece.marking:
                start = ranges.get((id(element), index), (element, end - len(piece.text), end))[1]
                ranges[(id(element), index)] = (element, start, end)
    marks = tuple(EditorialMark(_EDITORIAL_MARKS_BY_TAG[_tag(element)], index, start, end)
                  for (_, index), (element, start, end) in ranges.items() if _tag(element) != 'num')
    numerals = tuple(Numeral(index, start, end)
                     for (_, index), (element, start, end) in ranges.items() if _tag(element) == 'num')
    return tuple(joined), marks, numerals


def _note_text(note: ET.Element) -> str:
    return ''.join(note.itertext()).strip()
