"""Reads the text of a TEI edition, as Perseus encodes its poetry, into divisions and blocks of text. Raises on any
structure that it doesn't read, rather than guessing what the structure means."""
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
from typing import Dict, List, NamedTuple, Tuple, Union

TEI_NAMESPACE = 'http://www.tei-c.org/ns/1.0'
_TEI = f'{{{TEI_NAMESPACE}}}'
_XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'

#: The elements that each kind of division can hold
_PARTS_BY_DIVISION_KIND: Dict[str, Tuple[str, ...]] = {
    'book': ('head', 'div', 'note', 'milestone'),
    'poem': ('head', 'l', 'lg', 'sp', 'p', 'note', 'milestone'),
    'lg': ('head', 'l', 'lg', 'note', 'milestone'),
    'sp': ('speaker', 'l', 'lg', 'p', 'note', 'milestone'),
}
_DIVISION_TYPES_BY_KIND = {'book': 'BOOK', 'lg': 'LGRP', 'sp': 'SPCH'}
_DIVISION_KIND_NAMES = {'book': 'book', 'poem': 'poem', 'lg': 'line group', 'sp': 'speech'}
_BLOCK_TYPES_BY_TAG = {'head': 'TITL', 'speaker': 'TITL', 'l': 'VERS', 'p': 'PARA'}
#: The elements that each type of block can hold in its text. A paragraph holds none, as its validation compares it
#: with the text of its <p> before any element
_INLINE_TAGS_BY_BLOCK_TYPE: Dict[str, Tuple[str, ...]] = {
    'VERS': ('q', 'quote', 'gap', 'note', 'milestone'),
    'TITL': ('q', 'quote', 'note', 'milestone'),
    'PARA': (),
}


class LostPassage(NamedTuple):
    """A place where the edition marks the text as lost"""


class TextBlock(NamedTuple):
    """A verse, title or paragraph: text that the reader starts on a line of its own"""
    typ: str
    #: A verse's TEI n
    edition_label: str | None
    #: The reference of its tokens: the TEI n of each division above it that the edition cites, then a verse's own
    reference: str
    #: Its text in reading order, without its notes
    pieces: Tuple[Union[str, LostPassage], ...]
    #: Whether the edition marks the whole block for deletion
    deleted: bool
    notes: Tuple[str, ...]

    @property
    def printed_text(self) -> str:
        """Its text as the edition prints it, without its notes and lost passages"""
        return ''.join(piece for piece in self.pieces if isinstance(piece, str))

    @property
    def text(self) -> str:
        """Its printed text without the whitespace around it"""
        return self.printed_text.strip()


class Division(NamedTuple):
    """A book, poem, prologue, epilogue, line group or speech"""
    typ: str
    #: The TEI n of a book, poem, prologue or epilogue
    edition_label: str | None
    #: Its title first, when it has one, then its divisions and blocks in reading order
    parts: Tuple[Union['Division', TextBlock], ...]
    #: Its notes, and its headings in a language other than Latin
    notes: Tuple[str, ...]

    @property
    def title(self) -> TextBlock | None:
        first = self.parts[0]
        return first if isinstance(first, TextBlock) and first.typ == 'TITL' else None


def read_edition(root: ET.Element, cited_division_subtypes: Tuple[str, ...],
                 poem_types_by_n: Dict[str, str]) -> Tuple[Division, ...]:
    """Returns the books of the edition, or its poems when it has no books. The references of the tokens are made of
    the TEI n of the divisions whose subtype is one of cited_division_subtypes, and of the verse's. A poem whose n is in
    poem_types_by_n gets that type instead of POEM."""
    body = root.find(f'{_TEI}text/{_TEI}body')
    if body is None:
        raise ValueError("The TEI file has no <text><body>.")
    editions = _children(body, 'the body')
    if len(editions) != 1 or _tag(editions[0]) != 'div' or editions[0].get('type') != 'edition':
        raise ValueError('The body must hold one <div type="edition"> and nothing else.')
    edition = editions[0]
    kinds = {_textpart_kind(child, 'the edition') for child in _children(edition, 'the edition')}
    if len(kinds) != 1:
        raise ValueError("The edition must hold books, or poems, and not both." if kinds else "The edition is empty.")
    kind = kinds.pop()
    return tuple(_division(child, kind, 'the edition', (), cited_division_subtypes, poem_types_by_n)
                 for child in edition)


def _tag(element: ET.Element) -> str:
    return element.tag.removeprefix(_TEI) if isinstance(element.tag, str) else ''


def _children(element: ET.Element, where: str) -> List[ET.Element]:
    """Returns the element's children, and raises when it has text outside them"""
    if (element.text or '').strip() or any((child.tail or '').strip() for child in element):
        raise ValueError(f"{where} has text outside its parts, which isn't read.")
    return list(element)


def _textpart_kind(element: ET.Element, where: str) -> str:
    kind = element.get('subtype', '')
    if _tag(element) != 'div' or element.get('type') != 'textpart' or kind not in ('book', 'poem'):
        raise ValueError(f"{where} holds <{_tag(element)} type=\"{element.get('type', '')}\" subtype=\"{kind}\">, "
                         f"but only books and poems are read.")
    return kind


def _division(element: ET.Element, kind: str, where: str, cited: Tuple[str, ...],
              cited_division_subtypes: Tuple[str, ...], poem_types_by_n: Dict[str, str]) -> Division:
    n = element.get('n')
    if kind in ('book', 'poem'):
        if not n:
            raise ValueError(f"A {kind} in {where} has no n.")
        where = f"{where} > {kind} {n}"
        cited = cited + (n,) if kind in cited_division_subtypes else cited
    else:
        where = f"{where} > {kind}"
    typ = _DIVISION_TYPES_BY_KIND.get(kind) or poem_types_by_n.get(n or '', 'POEM')
    parts: List[Union[Division, TextBlock]] = []
    notes: List[str] = []
    for child in _children(element, where):
        tag = _tag(child)
        if tag not in _PARTS_BY_DIVISION_KIND[kind]:
            raise ValueError(f"{where} holds <{tag}>, which isn't read in a {_DIVISION_KIND_NAMES[kind]}.")
        if tag == 'note':
            notes.append(_note_text(child))
        elif tag == 'head' and child.get(_XML_LANG, 'lat') != 'lat':
            notes.append(''.join(child.itertext()).strip())
        elif tag in ('head', 'speaker'):
            if parts:
                raise ValueError(f"{where} has a title after its text or another title.")
            parts.append(_block(child, 'TITL', where, cited))
        elif tag == 'div':
            parts.append(_division(child, _poem_in_book(child, where), where, cited, cited_division_subtypes,
                                   poem_types_by_n))
        elif tag in ('lg', 'sp'):
            parts.append(_division(child, tag, where, cited, cited_division_subtypes, poem_types_by_n))
        elif tag in ('l', 'p'):
            parts.append(_block(child, _BLOCK_TYPES_BY_TAG[tag], where, cited))
    if not parts:
        raise ValueError(f"{where} has no text.")
    return Division(typ, n if kind in ('book', 'poem') else None, tuple(parts), tuple(notes))


def _poem_in_book(element: ET.Element, where: str) -> str:
    kind = _textpart_kind(element, where)
    if kind != 'poem':
        raise ValueError(f"{where} holds a {kind}, but a book is only read with poems.")
    return kind


def _block(element: ET.Element, typ: str, where: str, cited: Tuple[str, ...]) -> TextBlock:
    tag = _tag(element)
    n = element.get('n') if typ == 'VERS' else None
    if typ == 'VERS' and not n:
        raise ValueError(f"A line in {where} has no n.")
    where = f"{where} > {tag}" + (f" {n}" if n else '')
    reference = '.'.join(cited + ((n,) if n else ()))
    if not reference:
        raise ValueError(f"{where} would have no reference: no division above it is cited.")
    deletion = _whole_deletion(element) if typ != 'PARA' else None
    pieces, notes = _inline(deletion if deletion is not None else element, where, _INLINE_TAGS_BY_BLOCK_TYPE[typ])
    if not any(isinstance(piece, LostPassage) or piece.strip() for piece in pieces):
        raise ValueError(f"{where} has no text.")
    return TextBlock(typ, n, reference, pieces, deletion is not None, notes)


def _whole_deletion(element: ET.Element) -> ET.Element | None:
    """Returns the <del> that holds all of the element's text, if one does"""
    children = list(element)
    whole = (len(children) == 1 and _tag(children[0]) == 'del' and not (element.text or '').strip()
             and not (children[0].tail or '').strip())
    return children[0] if whole else None


def _inline(element: ET.Element, where: str,
            tags: Tuple[str, ...]) -> Tuple[Tuple[Union[str, LostPassage], ...], Tuple[str, ...]]:
    """Returns the element's text, with its lost passages where they are, and its notes. Raises on any element that
    isn't one of tags"""
    pieces: List[Union[str, LostPassage]] = [element.text or '']
    notes: List[str] = []
    for child in element:
        tag = _tag(child)
        if tag not in tags:
            raise ValueError(f"{where} holds <{tag}>, which isn't read there.")
        if tag in ('q', 'quote'):
            quoted, quoted_notes = _inline(child, where, tags)
            pieces.extend(quoted)
            notes.extend(quoted_notes)
        elif tag == 'gap':
            if child.get('reason') != 'lost':
                raise ValueError(f"{where} has a gap whose reason isn't lost.")
            pieces.append(LostPassage())
        elif tag == 'note':
            notes.append(_note_text(child))
        pieces.append(child.tail or '')
    return _joined(pieces), tuple(notes)


def _joined(pieces: List[Union[str, LostPassage]]) -> Tuple[Union[str, LostPassage], ...]:
    """Returns the pieces with the text between two lost passages in one piece, and no empty ones"""
    joined: List[Union[str, LostPassage]] = []
    for piece in pieces:
        if isinstance(piece, str) and joined and isinstance(joined[-1], str):
            joined[-1] += piece
        elif piece != '':
            joined.append(piece)
    return tuple(joined)


def _note_text(note: ET.Element) -> str:
    return ''.join(note.itertext()).strip()
