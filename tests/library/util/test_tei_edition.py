import re
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET

import pytest

from scripts.library.util.tei_edition import (Division, EditorialMark, LemmaMatch, LostPassage, Note, Numeral,
                                              TextBlock, read_edition)

_BOOKS_AND_POEMS = ('book', 'poem')
_POEMS = ('poem',)
_BOOKS_CHAPTERS_AND_SECTIONS = ('book', 'chapter', 'section')
_LINES_ONLY = ()


def _edition(body: str) -> ET.Element:
    return ET.fromstring(f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                         f'<div type="edition" xml:lang="lat">{body}</div></body></text></TEI>')


def _book(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="book" n="{n}">{content}</div>'


def _poem(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="poem" n="{n}">{content}</div>'


def _chapter(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="chapter" n="{n}">{content}</div>'


def _section(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="section" n="{n}">{content}</div>'


def _act(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="act" n="{n}">{content}</div>'


def _scene(n: str, content: str) -> str:
    return f'<div type="textpart" subtype="scene" n="{n}">{content}</div>'


def _notes(notes) -> tuple:
    """Returns the notes, each text that covers its whole block as a Note"""
    return tuple(Note(note) if isinstance(note, str) else note for note in notes)


def _verse(n: str, reference: str, *pieces, deleted=False, notes=(), marks=()) -> TextBlock:
    return TextBlock('VERS', n, reference, pieces, deleted, _notes(notes), marks)


def _paragraph(reference: str, *pieces, notes=(), marks=(), numerals=()) -> TextBlock:
    return TextBlock('PARA', None, reference, pieces, False, _notes(notes), marks, numerals)


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
            Division('SPCH', None, (_title('8.3', 'Damon'), _verse('3', '8.3', 'Nascere'),
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
        Division('POEM', '64', (_verse('23b', '64.23b', 'progenies, salvete iterum ', LostPassage('lost')),
                                _verse('23c', '64.23c', LostPassage('lost'), notes=('Lost.',))), ()),)


def test_a_verse_that_the_edition_marks_for_deletion_keeps_its_text():
    edition = _edition(_poem('3', '<l n="13">\n  <del>Hac re probatur.</del>\n</l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '3', (_verse('13', '3.13', 'Hac re probatur.', deleted=True),), ()),)


def test_books_of_chapters_of_sections_hold_paragraphs_with_the_references_of_book_chapter_and_section():
    edition = _edition(_book('1', '<head>COMMENTARIUS PRIMUS</head>'
                                  + _chapter('1', _section('1', '<p>Gallia est omnis divisa.</p>')
                                             + _section('2', '<p>Hi omnes lingua differunt.</p>'))
                                  + _chapter('2', _section('1', '<p>Apud Helvetios.</p>'))))

    assert read_edition(edition, _BOOKS_CHAPTERS_AND_SECTIONS, {}) == (
        Division('BOOK', '1', (
            _title('1', 'COMMENTARIUS PRIMUS'),
            Division('CHAP', '1', (Division('SECT', '1', (_paragraph('1.1.1', 'Gallia est omnis divisa.'),), ()),
                                   Division('SECT', '2', (_paragraph('1.1.2', 'Hi omnes lingua differunt.'),), ())),
                     ()),
            Division('CHAP', '2', (Division('SECT', '1', (_paragraph('1.2.1', 'Apud Helvetios.'),), ()),), ())), ()),)


def test_acts_of_scenes_hold_speeches_whose_speakers_take_the_reference_of_their_first_line():
    edition = _edition(_act('prologue', _scene('pr', '<milestone unit="card" n="1"/>'
                                                     '<sp><speaker>Mercvrivs</speaker><l n="1">Vt vos</l>'
                                                     '<lb ed="actscene" n="5"/><l n="2">emundis</l></sp>'))
                       + _act('1', _scene('1', '<sp><speaker>Sosia</speaker><lg><l n="153">Qui me</l></lg></sp>')))

    assert read_edition(edition, _LINES_ONLY, {'prologue': 'PROL'}) == (
        Division('PROL', 'prologue', (
            Division('SCEN', 'pr', (
                Division('SPCH', None, (_title('1', 'Mercvrivs'), _verse('1', '1', 'Vt vos'),
                                        _verse('2', '2', 'emundis')), ()),), ()),), ()),
        Division('ACT', '1', (
            Division('SCEN', '1', (
                Division('SPCH', None, (_title('153', 'Sosia'),
                                        Division('LGRP', None, (_verse('153', '153', 'Qui me'),), ())), ()),), ()),),
                 ()))


def test_the_editors_additions_are_read_where_they_are_and_marked():
    edition = _edition(_book('1', _chapter('1', _section('1', '<p>Hoc <add>ab</add> illo.</p>')))
                       + _book('2', _chapter('1', _section('1', '<p>Erus Amphitruo<add>st</add> occupatus.</p>'))))

    first = _paragraph('1.1.1', 'Hoc ab illo.', marks=(EditorialMark('addition', 0, 4, 6),))
    second = _paragraph('2.1.1', 'Erus Amphitruost occupatus.', marks=(EditorialMark('addition', 0, 14, 16),))
    assert read_edition(edition, _BOOKS_CHAPTERS_AND_SECTIONS, {}) == (
        Division('BOOK', '1', (Division('CHAP', '1', (Division('SECT', '1', (first,), ()),), ()),), ()),
        Division('BOOK', '2', (Division('CHAP', '1', (Division('SECT', '1', (second,), ()),), ()),), ()))


def test_an_addition_after_a_lost_passage_is_found_in_the_piece_after_it():
    edition = _edition(_poem('1', '<l n="1">quo <gap reason="omitted"/> te <add>avortisti</add>?</l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (_verse('1', '1.1', 'quo ', LostPassage('omitted'), ' te avortisti?',
                                      marks=(EditorialMark('addition', 2, 4, 13),)),), ()),)


def test_a_word_that_the_edition_marks_for_deletion_inside_a_verse_is_read_and_marked():
    edition = _edition(_poem('1', '<l n="237"> <del>vicimus</del> vi feroces.</l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (_verse('237', '1.237', ' vicimus vi feroces.',
                                      marks=(EditorialMark('deletion', 0, 1, 8),)),), ()),)


def test_an_abbreviation_is_read_without_its_expansion_and_a_line_break_separates_words():
    edition = _edition(_poem('1', '<l n="1">coicerent si <abbr>exercituru\'s<expan> <ex>exerciturus es'
                                  '</ex> </expan></abbr>, quaeso</l><l n="2">Quid hoc sit<lb/>hominis?</l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (_verse('1', '1.1', "coicerent si exercituru's, quaeso"),
                               _verse('2', '1.2', 'Quid hoc sit hominis?')), ()),)


def test_sic_and_a_correction_of_the_editors_are_read_and_marked():
    edition = _edition(_poem('8', '<l n="19">quod ut superbo <corr>provoces</corr> ab inguine,</l>')
                       + _poem('9', '<l n="1">lapides ac tela <sic>coicerent</sic></l>')
                       + _poem('10', '<p>Milia passuum <sic>XV</sic>.</p>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '8', (_verse('19', '8.19', 'quod ut superbo provoces ab inguine,',
                                      marks=(EditorialMark('correction', 0, 16, 24),)),), ()),
        Division('POEM', '9', (_verse('1', '9.1', 'lapides ac tela coicerent',
                                      marks=(EditorialMark('sic', 0, 16, 25),)),), ()),
        Division('POEM', '10', (_paragraph('10', 'Milia passuum XV.', marks=(EditorialMark('sic', 0, 14, 16),)),), ()))


def test_an_omitted_passage_is_a_lost_passage_with_its_reason_in_a_verse_or_a_paragraph():
    edition = _edition(_poem('1', '<l n="45">deorum <gap reason="omitted"/> architectus</l>'
                                  '<p>tamen <gap reason="lost"/> Caesar</p>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (_verse('45', '1.45', 'deorum ', LostPassage('omitted'), ' architectus'),
                               _paragraph('1', 'tamen ', LostPassage('lost'), ' Caesar')), ()),)


def test_a_note_with_a_lemma_is_about_the_last_words_before_it_that_match_the_lemma():
    edition = _edition(_poem('1', '<p>cum tot, cum<note><app><lem>cum</lem></app> quom A</note> summi oratores</p>'
                                  '<p>Postea, cum ut hoc intellegatis'
                                  '<note><app><lem>postea cum ut... intellegatis</lem></app> ut om. P</note>'
                                  ' cum<note><w type="lemma">quod</w> quod vos</note>'
                                  '<note><app><lem>nemo ... cum</lem></app> nemo B</note>'
                                  '<note><app><lem/></app> om. C</note>.</p>'
                                  '<p>et levis est<note><app><lem>et levis ... levis est</lem></app> om. D</note></p>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (
            _paragraph('1', 'cum tot, cum summi oratores', notes=(Note('cum quom A', 'cum', LemmaMatch(0, 9, 12)),)),
            _paragraph('1', 'Postea, cum ut hoc intellegatis cum.', notes=(
                Note('postea cum ut... intellegatis ut om. P', 'postea cum ut... intellegatis', LemmaMatch(0, 0, 31)),
                Note('quod quod vos', 'quod'), Note('nemo ... cum nemo B', 'nemo ... cum'), Note('om. C', ''))),
            _paragraph('1', 'et levis est', notes=(Note('et levis ... levis est om. D', 'et levis ... levis est'),)),
        ), ()),)


def test_two_dots_or_more_spaced_or_not_even_across_lines_stand_for_the_words_that_a_lemma_leaves_out():
    edition = _edition(_poem('1', '<l n="53">unus in hoc nemo est populo,'
                                  '<note><app><lem>nemo . . populo</lem></app> populo vix est</note></l>'
                                  '<l n="55">ille ego Romanus vates'
                                  '<note><app><lem>ille .\n          . vates</lem></app> om. A</note></l>'
                                  '<l n="59">quia me meruisse videbam'
                                  '<note><app><lem>quia . . . videbam</lem></app> quoniam videbar</note></l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (
            _verse('53', '1.53', 'unus in hoc nemo est populo,',
                   notes=(Note('nemo . . populo populo vix est', 'nemo . . populo', LemmaMatch(0, 12, 27)),)),
            _verse('55', '1.55', 'ille ego Romanus vates',
                   notes=(Note('ille .\n          . vates om. A', 'ille .\n          . vates', LemmaMatch(0, 0, 22)),)),
            _verse('59', '1.59', 'quia me meruisse videbam',
                   notes=(Note('quia . . . videbam quoniam videbar', 'quia . . . videbam', LemmaMatch(0, 0, 24)),)),
        ), ()),)


def test_one_dot_in_a_lemma_is_punctuation_and_leaves_out_no_words():
    edition = _edition(_poem('1', '<l n="1">tum Roma, tum Caesar'
                                  '<note><app><lem>Roma. Caesar</lem></app> om. B</note></l>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (
            _verse('1', '1.1', 'tum Roma, tum Caesar', notes=(Note('Roma. Caesar om. B', 'Roma. Caesar'),)),
        ), ()),)


def test_a_page_break_is_left_out_wherever_it_is_and_one_inside_a_word_leaves_it_whole():
    root = ET.fromstring('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><pb n="1"/><div type="edition">'
                         '<pb n="2"/>' + _book('1', '<pb n="3"/><head>Liber</head>' + _chapter('1', _section('1', (
                             '<pb n="4"/><p>plurima beneficia, sum<pb n="160"/>ma</p>'))))
                         + '</div></body></text></TEI>')

    assert read_edition(root, _BOOKS_CHAPTERS_AND_SECTIONS, {}) == (
        Division('BOOK', '1', (_title('1', 'Liber'), Division('CHAP', '1', (
            Division('SECT', '1', (_paragraph('1.1.1', 'plurima beneficia, summa'),), ()),), ())), ()),)


def test_the_heading_with_the_works_title_straight_in_the_edition_is_left_out():
    edition = _edition('<head>Amores</head>' + _book('1', _poem('1', '<l n="1">Arma gravi numero</l>')))

    assert read_edition(edition, _BOOKS_AND_POEMS, {}) == (
        Division('BOOK', '1', (Division('POEM', '1', (_verse('1', '1.1.1', 'Arma gravi numero'),), ()),), ()),)


def test_titles_and_paragraphs_read_what_verses_read():
    edition = _edition(_poem('1', '<head>Roma <gap reason="lost"/> <add>est</add></head>'
                                  '<p>Fabula<note>Nota.</note> <q>docet</q><lb/>hominem <del>bene</del>.'
                                  '<milestone unit="para"/></p>')
                       + _poem('2', '<p><del>Fabula docet.</del></p>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (
            TextBlock('TITL', None, '1', ('Roma ', LostPassage('lost'), ' est'), False, (),
                      (EditorialMark('addition', 2, 1, 4),)),
            _paragraph('1', 'Fabula docet hominem bene.', notes=('Nota.',),
                       marks=(EditorialMark('deletion', 0, 21, 25),))), ()),
        Division('POEM', '2', (TextBlock('PARA', None, '2', ('Fabula docet.',), True, ()),), ()))


def test_a_numeral_that_the_edition_tags_is_marked_also_inside_what_the_editor_marks():
    edition = _edition(_book('3', _chapter('2', _section('3', '<p>anguste <sic><num>xv</num> milia</sic> militum, '
                                                              '<del>circiter <num>d</num></del> equites</p>'))))

    assert read_edition(edition, _BOOKS_CHAPTERS_AND_SECTIONS, {}) == (
        Division('BOOK', '3', (Division('CHAP', '2', (Division('SECT', '3', (_paragraph(
            '3.2.3', 'anguste xv milia militum, circiter d equites',
            marks=(EditorialMark('sic', 0, 8, 16), EditorialMark('deletion', 0, 26, 36)),
            numerals=(Numeral(0, 8, 10), Numeral(0, 35, 36))),), ()),), ()),), ()),)


def test_an_editorial_mark_around_a_page_break_and_a_quotation_is_one_mark():
    edition = _edition(_poem('1', '<p>tum <add>ma<pb n="2"/>gis <q>ait</q></add> ille</p>'))

    assert read_edition(edition, _POEMS, {}) == (
        Division('POEM', '1', (_paragraph('1', 'tum magis ait ille', marks=(EditorialMark('addition', 0, 4, 13),)),),
                 ()),)


def test_typography_in_capitals_is_read_as_its_text_and_a_line_break_between_speeches_is_left_out():
    edition = _edition(_act('1', _scene('1', '<sp><speaker>Lygdamus</speaker><l n="29"><hi rend="uppercase">Lygdamus '
                                             'hic</hi> <emph rend="uppercase">situs</emph> est</l></sp>'
                                             '<lb ed="actscene" n="5"/>'
                                             '<sp><speaker>Neaera</speaker><l n="30">dolor</l></sp>')))

    assert read_edition(edition, _LINES_ONLY, {}) == (
        Division('ACT', '1', (Division('SCEN', '1', (
            Division('SPCH', None, (_title('29', 'Lygdamus'), _verse('29', '29', 'Lygdamus hic situs est')), ()),
            Division('SPCH', None, (_title('30', 'Neaera'), _verse('30', '30', 'dolor')), ())), ()),), ()),)


@pytest.mark.parametrize("typography, opening_tag", [
    ('<hi rend="overline">MM</hi>', '<hi rend="overline">'),
    ('<emph rend="italic">milia</emph>', '<emph rend="italic">'),
    ('<hi>milia</hi>', '<hi rend="">'),
], ids=["an overline", "italics", "no rend"])
def test_typography_of_another_rend_raises(typography, opening_tag):
    with pytest.raises(ValueError, match=re.escape(
            f"the edition > poem 1 > l 1 holds {opening_tag}, but only uppercase typography is read there.")):
        read_edition(_edition(_poem('1', f'<l n="1">sunt {typography} passuum</l>')), _POEMS, {})


@pytest.mark.parametrize("body, cited, error", [
    (_poem('1', '<l n="1">Roma <foreign>est</foreign></l>'), _POEMS,
     "the edition > poem 1 > l 1 holds <foreign>, which isn't read there."),
    (_poem('1', '<l n="1"><gap reason="illegible"/></l>'), _POEMS, "the edition > poem 1 > l 1 has a gap whose reason "
                                                                  "isn't lost or omitted."),
    (_poem('1', 'Roma est.<l n="1">Roma</l>'), _POEMS, "the edition > poem 1 has text outside its parts"),
    (_poem('1', '<l>Roma est.</l>'), _POEMS, "A line in the edition > poem 1 has no n."),
    ('<div type="textpart" subtype="poem"><l n="1">Roma</l></div>', _POEMS, "A poem in the edition has no n."),
    (_book('1', _poem('1', '<l n="1">Roma</l>')) + _poem('2', '<l n="1">est</l>'), _POEMS,
     "the edition holds books and poems, but only one kind of division is read in the edition."),
    (_poem('1', _book('1', '<l n="1">Roma</l>')), _POEMS, "the edition > poem 1 holds <div>, which isn't read in a "
                                                          "poem."),
    (_book('1', _book('2', _poem('1', '<l n="1">Roma</l>'))), _POEMS,
     'the edition > book 1 holds <div type="textpart" subtype="book">, but only poems and chapters are read there.'),
    ('<div type="textpart" subtype="speech" n="1"><p>Roma</p></div>', _POEMS,
     'the edition holds <div type="textpart" subtype="speech">, but only books, poems and acts are read there.'),
    (_poem('1', '<lg><sp><speaker>Damon</speaker><l n="1">Roma</l></sp></lg>'), _POEMS,
     "the edition > poem 1 > lg holds <sp>, which isn't read in a line group."),
    (_poem('1', '<lg><p>Roma est.</p></lg>'), _POEMS, "the edition > poem 1 > lg holds <p>, which isn't read in a line "
                                                      "group."),
    (_poem('1', '<l n="1">Roma</l><head>Carmen</head>'), _POEMS, "the edition > poem 1 has a title after its text or "
                                                                 "another title."),
    (_poem('1', '<head>Carmen</head><head>Alterum</head><l n="1">Roma</l>'), _POEMS,
     "the edition > poem 1 has a title after its text or another title."),
    (_poem('1', '<l n="1"> </l>'), _POEMS, "the edition > poem 1 > l 1 has no text."),
    (_poem('1', '<note>Desunt cetera.</note>'), _POEMS, "the edition > poem 1 has no text."),
    (_book('lyrics', '<head>Polymetra</head>' + _poem('1', '<l n="1">Roma</l>')), _POEMS,
     "the edition > book lyrics > head would have no reference: no division above it is cited."),
    ('', _POEMS, "The edition is empty."),
    (_book('1', _poem('1', '<l n="1">Roma</l>') + _chapter('1', _section('1', '<p>est</p>'))), _POEMS,
     "the edition > book 1 holds chapters and poems, but only one kind of division is read in the book."),
    (_book('1', _chapter('1', _section('1', '<l n="1">Roma</l>'))), _BOOKS_CHAPTERS_AND_SECTIONS,
     "the edition > book 1 > chapter 1 > section 1 holds <l>, which isn't read in a section."),
    (_book('1', _chapter('1', _chapter('2', _section('1', '<p>Roma</p>')))), _BOOKS_CHAPTERS_AND_SECTIONS,
     'the edition > book 1 > chapter 1 holds <div type="textpart" subtype="chapter">, but only sections are read '
     'there.'),
    (_scene('1', '<sp><speaker>Sosia</speaker><l n="1">Roma</l></sp>'), _LINES_ONLY,
     'the edition holds <div type="textpart" subtype="scene">, but only books, poems and acts are read there.'),
    ('<div type="textpart" subtype="act">' + _scene('1', '<sp><l n="1">Roma</l></sp>') + '</div>', _LINES_ONLY,
     "An act in the edition has no n."),
    (_poem('1', '<sp><speaker>Sosia</speaker></sp>'), _POEMS, "the edition > poem 1 > sp has no text."),
    (_poem('1', '<l n="1">Roma <expan>est</expan></l>'), _POEMS,
     "the edition > poem 1 > l 1 holds <expan>, which isn't read there."),
    (_poem('1', '<l n="1">Roma<note><app><lem>Roma</lem></app> <w type="lemma">Roma</w> A</note></l>'), _POEMS,
     "the edition > poem 1 > l 1 holds a note with 2 lemmas, but only one is read."),
    (_poem('1', '<l n="1">Roma</l><note><app><lem>Roma</lem></app> A</note>'), _POEMS,
     "the edition > poem 1 holds a note with a lemma outside a verse, title or paragraph, which isn't read."),
    ('<head>M. Tulli Ciceroni in Q. Caecilium Oratio</head><head>Quae Divinatio Dicitur</head>'
     + _poem('1', '<l n="1">Roma</l>'), _POEMS,
     'the edition holds <head type="" subtype="">, but only books, poems and acts are read there.'),
], ids=["an element in a verse that isn't read",
        "a gap for another reason", "text outside a verse", "a verse without n", "a poem without n",
        "books and poems at the top", "a book in a poem", "a book in a book", "another subtype",
        "a speech in a line group", "a paragraph in a line group",
        "a title after a verse", "two titles",
        "a verse without text", "a poem without text", "a title of a book that the edition doesn't cite",
        "an empty edition", "a book of poems and chapters", "a verse in a section", "a chapter in a chapter",
        "a scene at the top", "an act without n", "a speech without what is said",
        "an expansion outside an abbreviation", "a note with two lemmas", "a note with a lemma between verses",
        "a second heading in the edition"])
def test_a_structure_that_isnt_read_raises(body, cited, error):
    with pytest.raises(ValueError, match=re.escape(error)):
        read_edition(_edition(body), cited, {})


def test_a_body_without_one_edition_raises():
    root = ET.fromstring('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                         '<div type="textpart" subtype="poem" n="1"><l n="1">Roma</l></div></body></text></TEI>')

    with pytest.raises(ValueError, match=re.escape('The body must hold one <div type="edition"> and nothing else.')):
        read_edition(root, _POEMS, {})
