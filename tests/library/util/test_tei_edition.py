import re
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET

import pytest

from scripts.library.util.tei_edition import Division, LostPassage, TextBlock, read_edition

_BOOKS_AND_POEMS = ('book', 'poem')
_POEMS = ('poem',)


def _edition(body: str) -> ET.Element:
    return ET.fromstring(f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                         f'<div type="edition" xml:lang="lat">{body}</div></body></text></TEI>')


def _book(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="book" n="{n}">{content}</div>'


def _poem(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="poem" n="{n}">{content}</div>'


def _verse(n: str, reference: str, *pieces, deleted=False, notes=()) -> TextBlock:
    return TextBlock('VERS', n, reference, pieces, deleted, notes)


def _title(reference: str, text: str) -> TextBlock:
    return TextBlock('TITL', None, reference, (text,), False, ())


def test_books_poems_titles_verses_and_paragraphs_get_the_references_of_the_divisions_that_the_edition_cites():
    edition = _edition(_book('1', '<head>Liber Primus</head>'
                                  + _poem('prologus', '<head>PROLOGUS</head><l n="1">Aesopus auctor.</l>')
                                  + _poem('2', '<head>Lupus et agnus.</head><p>Fabula docet.</p>'
                                               '<l n="1">Ad rivum.</l>')))

    assert read_edition(edition, _BOOKS_AND_POEMS, {'prologus': 'PROL'}) == (
        Division('BOOK', '1', (
            _title('1', 'Liber Primus'),
            Division('PROL', 'prologus', (_title('1.prologus', 'PROLOGUS'),
                                          _verse('1', '1.prologus.1', 'Aesopus auctor.')), ()),
            Division('POEM', '2', (_title('1.2', 'Lupus et agnus.'),
                                   TextBlock('PARA', None, '1.2', ('Fabula docet.',), False, ()),
                                   _verse('1', '1.2.1', 'Ad rivum.')), ())), ()),)


def test_a_work_without_books_has_its_poems_at_the_top():
    edition = _edition(_poem('1', '<head>ECLOGA I.</head><l n="1">Tityre, tu</l>')
                       + _poem('2', '<l n="1">Formosum</l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (_title('1', 'ECLOGA I.'), _verse('1', '1.1', 'Tityre, tu')), ()),
        Division('POEM', '2', (_verse('1', '2.1', 'Formosum'),), ()))


def test_books_that_the_edition_doesnt_cite_are_left_out_of_the_references_and_keep_their_edition_label():
    edition = _edition(_book('lyrics', _poem('14a', '<l n="1">Si qui forte</l><l n="3ff">lectores</l>')))

    assert read_edition(edition, _POEMS, {}) == (
        Division('BOOK', 'lyrics', (
            Division('POEM', '14a', (_verse('1', '14a.1', 'Si qui forte'), _verse('3ff', '14a.3ff', 'lectores')), ()),
        ), ()),)


def test_line_groups_and_speeches_hold_their_verses_without_an_edition_label_and_a_speaker_is_the_title_of_a_speech():
    edition = _edition(_poem('8', '<lg n="1"><l n="1">Pastorum musam</l><lg><l n="2">Tu mihi</l></lg></lg>'
                                  '<sp><speaker>Damon</speaker><l n="3">Nascere</l><lg><l n="4">Incipe</l></lg></sp>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '8', (
            Division('LGRP', None, (_verse('1', '8.1', 'Pastorum musam'),
                                    Division('LGRP', None, (_verse('2', '8.2', 'Tu mihi'),), ())), ()),
            Division('SPCH', None, (_title('8', 'Damon'), _verse('3', '8.3', 'Nascere'),
                                    Division('LGRP', None, (_verse('4', '8.4', 'Incipe'),), ())), ())), ()),)


def test_a_heading_in_another_language_than_latin_is_a_note_of_its_division():
    edition = _edition(_poem('62', '<lg><head xml:lang="eng" resp="perseus">Youths</head><l n="1">Vesper adest</l>'
                                   '</lg>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '62', (Division('LGRP', None, (_verse('1', '62.1', 'Vesper adest'),), ('Youths',)),), ()),)


def test_quotations_milestones_and_notes_inside_a_verse_leave_the_text_around_them():
    edition = _edition(_poem('2', '<l n="11"><milestone unit="alt_poem_line" n="2a_1"/>Tam <q>gratum <q>est'
                                  '<note>Quoted.</note></q></q> mihi<note resp="perseus">A note.</note> quam ferunt'
                                  '</l><l n="12"><quote n="inscription">DAPHNIS EGO</quote></l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '2', (_verse('11', '2.11', 'Tam gratum est mihi quam ferunt', notes=('Quoted.', 'A note.')),
                               _verse('12', '2.12', 'DAPHNIS EGO')), ()),)


def test_a_lost_passage_is_where_the_edition_marks_it():
    edition = _edition(_poem('64', '<l n="23b">progenies, salvete iterum <gap reason="lost" rend=". . ."/></l>'
                                   '<l n="23c"><gap reason="lost"/><note>Lost.</note></l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '64', (_verse('23b', '64.23b', 'progenies, salvete iterum ', LostPassage()),
                                _verse('23c', '64.23c', LostPassage(), notes=('Lost.',))), ()),)


def test_a_verse_that_the_edition_marks_for_deletion_keeps_its_text():
    edition = _edition(_poem('3', '<l n="13">\n  <del>Hac re probatur.</del>\n</l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '3', (_verse('13', '3.13', 'Hac re probatur.', deleted=True),), ()),)


@pytest.mark.parametrize("body, cited, error", [
    (_poem('1', '<l n="1">Roma <foreign>est</foreign></l>'), _POEMS,
     "the edition > poem 1 > l 1 holds <foreign>, which isn't read there."),
    (_poem('1', '<l n="1">Roma <del>est</del></l>'), _POEMS, "the edition > poem 1 > l 1 holds <del>, which isn't "
                                                            "read there."),
    (_poem('1', '<head>Roma <gap reason="lost"/></head><l n="1">est</l>'), _POEMS,
     "the edition > poem 1 > head holds <gap>, which isn't read there."),
    (_poem('1', '<l n="1"><gap reason="illegible"/></l>'), _POEMS, "the edition > poem 1 > l 1 has a gap whose reason "
                                                                  "isn't lost."),
    (_poem('1', 'Roma est.<l n="1">Roma</l>'), _POEMS, "the edition > poem 1 has text outside its parts"),
    (_poem('1', '<l>Roma est.</l>'), _POEMS, "A line in the edition > poem 1 has no n."),
    ('<div type="textpart" subtype="poem"><l n="1">Roma</l></div>', _POEMS, "A poem in the edition has no n."),
    (_book('1', _poem('1', '<l n="1">Roma</l>')) + _poem('2', '<l n="1">est</l>'), _POEMS,
     "The edition must hold books, or poems, and not both."),
    (_poem('1', _book('1', '<l n="1">Roma</l>')), _POEMS, "the edition > poem 1 holds <div>, which isn't read in a "
                                                          "poem."),
    (_book('1', _book('2', _poem('1', '<l n="1">Roma</l>'))), _POEMS, "the edition > book 1 holds a book, but a book "
                                                                      "is only read with poems."),
    ('<div type="textpart" subtype="chapter" n="1"><p>Roma</p></div>', _POEMS,
     'the edition holds <div type="textpart" subtype="chapter">, but only books and poems are read.'),
    (_poem('1', '<lg><sp><speaker>Damon</speaker><l n="1">Roma</l></sp></lg>'), _POEMS,
     "the edition > poem 1 > lg holds <sp>, which isn't read in a line group."),
    (_poem('1', '<lg><p>Roma est.</p></lg>'), _POEMS, "the edition > poem 1 > lg holds <p>, which isn't read in a line "
                                                      "group."),
    (_poem('1', '<p>Fabula<note>Nota.</note> docet.</p>'), _POEMS, "the edition > poem 1 > p holds <note>, which "
                                                                   "isn't read there."),
    (_poem('1', '<p><del>Fabula docet.</del></p>'), _POEMS, "the edition > poem 1 > p holds <del>, which isn't read "
                                                            "there."),
    (_poem('1', '<l n="1">Roma</l><head>Carmen</head>'), _POEMS, "the edition > poem 1 has a title after its text or "
                                                                 "another title."),
    (_poem('1', '<head>Carmen</head><head>Alterum</head><l n="1">Roma</l>'), _POEMS,
     "the edition > poem 1 has a title after its text or another title."),
    (_poem('1', '<l n="1"> </l>'), _POEMS, "the edition > poem 1 > l 1 has no text."),
    (_poem('1', '<note>Desunt cetera.</note>'), _POEMS, "the edition > poem 1 has no text."),
    (_book('lyrics', '<head>Polymetra</head>' + _poem('1', '<l n="1">Roma</l>')), _POEMS,
     "the edition > book lyrics > head would have no reference: no division above it is cited."),
    ('', _POEMS, "The edition is empty."),
], ids=["an element in a verse that isn't read", "a deletion of part of a verse", "a lost passage in a title",
        "a gap for another reason", "text outside a verse", "a verse without n", "a poem without n",
        "books and poems at the top", "a book in a poem", "a book in a book", "another subtype",
        "a speech in a line group", "a paragraph in a line group", "a note in a paragraph",
        "a paragraph marked for deletion", "a title after a verse", "two titles",
        "a verse without text", "a poem without text", "a title of a book that the edition doesn't cite",
        "an empty edition"])
def test_a_structure_that_isnt_read_raises(body, cited, error):
    with pytest.raises(ValueError, match=re.escape(error)):
        read_edition(_edition(body), cited, {})


def test_a_body_without_one_edition_raises():
    root = ET.fromstring('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                         '<div type="textpart" subtype="poem" n="1"><l n="1">Roma</l></div></body></text></TEI>')

    with pytest.raises(ValueError, match=re.escape('The body must hold one <div type="edition"> and nothing else.')):
        read_edition(root, _POEMS, {})
