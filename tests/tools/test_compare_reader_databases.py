import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple, cast

import pytest

from scripts.tools.compare_reader_databases import ComparisonError, compare, main, report

READER_TABLES_THAT_THE_COMPARISON_READS = '''
CREATE TABLE Works( id TEXT PRIMARY KEY, name TEXT NOT NULL );
CREATE TABLE Authors( id TEXT PRIMARY KEY, name TEXT NOT NULL );
CREATE TABLE AuthorsAndWorks( authorId TEXT NOT NULL, workId TEXT NOT NULL );
CREATE TABLE WorkContents( workId TEXT, idx INTEGER, word TEXT, sourceReference TEXT, properNounState INTEGER,
                           tokenType INTEGER, sentenceIdx INTEGER, wordIdx INTEGER, enclitic TEXT, expansion TEXT,
                           macronizedWord TEXT, uncertaintyBitMask INTEGER );
CREATE TABLE WorkContentSubdivisions( workId TEXT, node TEXT, typ TEXT, cnt INTEGER, name TEXT, parent TEXT,
                                      fromIndex INTEGER, toIndex INTEGER );
CREATE TABLE MorphologicalDetails( form TEXT, item INTEGER, dictionaryRef TEXT, PRIMARY KEY( form, item ) );
'''
CANDIDATE_TABLE = 'CREATE TABLE {}( workId TEXT, idx INTEGER, componentOrdinal INTEGER, form TEXT, item INTEGER{} );'


def _token(reference, word, **values):
    is_word = word.isalpha()
    token = dict(reference=reference, word=word, tokenType=1 if is_word else 4, macronizedWord=word,
                 uncertaintyBitMask=0, properNounState=0 if is_word else None, enclitic=None, expansion=None,
                 lemmas_by_component_ordinal={0: {word.lower()}} if is_word else {}, ends_sentence=word == '.')
    token.update(values)
    return token


def _tokens(*verses):
    return [_token(reference, word) for reference, text in verses for word in text.split()]


class SubdivisionRow(NamedTuple):
    typ: str
    cnt: int
    name: str
    parent_position: Optional[int]
    first_token_position: int
    last_token_position: int


def _one_book_with_one_poem_with_a_verse_per_reference(tokens) -> List[SubdivisionRow]:
    positions_by_reference = {}
    for position, token in enumerate(tokens):
        positions_by_reference.setdefault(token['reference'], []).append(position)
    last = len(tokens) - 1
    verses = [SubdivisionRow('VERS', int(reference.rsplit('.', 1)[1]) - 1,
                            ' '.join(tokens[p]['word'] for p in positions), 1, positions[0], positions[-1])
              for reference, positions in positions_by_reference.items()]
    return [SubdivisionRow('BOOK', 0, '', None, 0, last),
            SubdivisionRow('POEM', 0, 'Carmen', 0, 0, last), *verses]


@dataclass
class _Work:
    tokens: list
    name: str = 'Carmina'
    authors: Tuple[str, ...] = ('Fictor',)
    subdivisions: Optional[List[SubdivisionRow]] = None

    def __post_init__(self):
        if self.subdivisions is None:
            self.subdivisions = _one_book_with_one_poem_with_a_verse_per_reference(self.tokens)


ARMA = ('1.1.1', 'arma virumque cano .')
TROIAE = ('1.1.2', 'Troiae qui primus ab oris .')
ITALIAM = ('1.1.3', 'Italiam fato profugus .')


def _database_with_new_ids(path: Path, *works: _Work, candidate_table='CountableWordCandidateAnalyses') -> Path:
    db = sqlite3.connect(path)
    db.executescript(READER_TABLES_THAT_THE_COMPARISON_READS)
    db.execute(CANDIDATE_TABLE.format(candidate_table, ', cnt INTEGER' if 'Inflections' in candidate_table else ''))
    for work in works:
        work_id = str(uuid.uuid4())
        db.execute('INSERT INTO Works VALUES ( ?, ? )', (work_id, work.name))
        for author in work.authors:
            author_id = str(uuid.uuid4())
            db.execute('INSERT INTO Authors VALUES ( ?, ? )', (author_id, author))
            db.execute('INSERT INTO AuthorsAndWorks VALUES ( ?, ? )', (author_id, work_id))
        sentence_idx, word_idx = 0, 0
        for idx, token in enumerate(work.tokens):
            is_counted = token['tokenType'] <= 3
            db.execute('INSERT INTO WorkContents VALUES ( ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? )',
                       (work_id, idx, token['word'], token['reference'], token['properNounState'],
                        token['tokenType'], sentence_idx, word_idx if is_counted else None, token['enclitic'],
                        token['expansion'], token['macronizedWord'], token['uncertaintyBitMask']))
            word_idx += is_counted
            if token['ends_sentence']:
                sentence_idx, word_idx = sentence_idx + 1, 0
            for component_ordinal, lemmas in token['lemmas_by_component_ordinal'].items():
                for lemma in lemmas:
                    db.execute('INSERT OR IGNORE INTO MorphologicalDetails VALUES ( ?, 0, ? )', (lemma, lemma))
                    db.execute(f'INSERT INTO {candidate_table}( workId, idx, componentOrdinal, form, item ) '
                               f'VALUES ( ?, ?, ?, ?, 0 )', (work_id, idx, component_ordinal, lemma))
        subdivisions = cast(List[SubdivisionRow], work.subdivisions)
        nodes = [str(uuid.uuid4()) for _ in subdivisions]
        for node, row in zip(nodes, subdivisions):
            parent_position = row.parent_position
            parent = None if parent_position is None else nodes[parent_position]
            db.execute('INSERT INTO WorkContentSubdivisions VALUES ( ?, ?, ?, ?, ?, ?, ?, ? )',
                       (work_id, node, row.typ, row.cnt, row.name, parent, row.first_token_position,
                        row.last_token_position))
    db.commit()
    db.close()
    return path


@pytest.fixture
def compared(tmp_path):
    def compare_databases_of(old_works, new_works, **options):
        directory = Path(tempfile.mkdtemp(dir=tmp_path))
        return compare(_database_with_new_ids(directory / 'old.db', *old_works),
                       _database_with_new_ids(directory / 'new.db', *new_works), **options)
    return compare_databases_of


def _changed_locations_by_field(diff):
    return {name: [pair.new.location for pair in pairs] for name, pairs in diff.changed_token_pairs_by_field.items()}


def test_the_same_works_under_new_ids_have_no_differences(compared):
    comparison = compared([_Work(_tokens(ARMA, TROIAE, ITALIAM))], [_Work(_tokens(ARMA, TROIAE, ITALIAM))])

    assert not comparison.differs
    assert report(comparison)[-1] == 'No differences'


def test_works_with_the_same_name_are_told_apart_by_their_authors(compared):
    changed = _tokens(ARMA, TROIAE, ITALIAM)
    changed[1]['macronizedWord'] = 'virūmque'

    comparison = compared([_Work(_tokens(ARMA, TROIAE, ITALIAM), authors=('Catullus',)),
                           _Work(_tokens(ARMA, TROIAE, ITALIAM), authors=('Horatius',))],
                          [_Work(_tokens(ARMA, TROIAE, ITALIAM), authors=('Catullus',)),
                           _Work(changed, authors=('Horatius',))])

    assert {diff.new.identity: diff.differs for diff in comparison.work_diffs} == {('Catullus', 'Carmina'): False,
                                                                                    ('Horatius', 'Carmina'): True}


def test_two_works_with_the_same_authors_and_name_cant_be_compared(compared):
    with pytest.raises(ComparisonError, match='Fictor: Carmina'):
        compared([_Work(_tokens(ARMA)), _Work(_tokens(ARMA))], [_Work(_tokens(ARMA))])


def test_a_change_is_reported_at_its_reference_and_position(compared):
    changed = _tokens(ARMA, TROIAE, ITALIAM)
    changed[5]['macronizedWord'] = 'quī'

    diff = compared([_Work(_tokens(ARMA, TROIAE, ITALIAM))], [_Work(changed)]).work_diffs[0]

    assert _changed_locations_by_field(diff) == {'macronizedWord': ['1.1.2#2']}


def test_a_token_added_inside_a_verse_is_reported_alone(compared):
    added = _tokens(ARMA, TROIAE, ITALIAM)
    added.insert(5, _token('1.1.2', 'et'))

    diff = compared([_Work(_tokens(ARMA, TROIAE, ITALIAM))], [_Work(added)]).work_diffs[0]

    assert [token.location for token in diff.added_tokens] == ['1.1.2#2']
    assert (diff.removed_tokens, diff.moved_tokens) == ([], [])
    assert _changed_locations_by_field(diff) == {'wordIdx': ['1.1.2#3', '1.1.2#4', '1.1.2#5', '1.1.2#6']}
    assert list(diff.subdivision_changes_by_field) == ['name']


def test_verses_swapped_under_their_own_references_are_reported_as_moved(compared):
    comparison = compared([_Work(_tokens(ARMA, TROIAE, ITALIAM))], [_Work(_tokens(ARMA, ITALIAM, TROIAE))])

    diff = comparison.work_diffs[0]
    assert [pair.new.location for pair in diff.moved_tokens] == ['1.1.3#1', '1.1.3#2', '1.1.3#3', '1.1.3#4']
    assert _changed_locations_by_field(diff) == {}
    assert '    1.1.3#1–1.1.3#4 now after 1.1.1#4' in report(comparison)


def test_a_boundary_moving_inside_one_reference_is_reported(compared):
    tokens = [_token('1.1', 'Ad'), _token('1.1', 'amicum'), _token('1.1', 'carmen'), *_tokens(ARMA)]
    last = len(tokens) - 1

    def with_a_title_ending_at(title_end):
        return _Work(tokens, subdivisions=[SubdivisionRow('BOOK', 0, '', None, 0, last),
                                           SubdivisionRow('POEM', 0, 'Ad amicum', 0, 0, last),
                                           SubdivisionRow('TITL', 0, 'Ad amicum', 1, 0, title_end)])

    diff = compared([with_a_title_ending_at(1)], [with_a_title_ending_at(2)]).work_diffs[0]

    assert [(change.new.typ, change.old_value, change.new_value)
            for change in diff.subdivision_changes_by_field['last token']] == [('TITL', '1.1#2', '1.1#3')]


def test_a_verse_moved_to_another_poem_has_another_parent(compared):
    tokens = _tokens(ARMA, TROIAE, ITALIAM)
    last = len(tokens) - 1

    def with_the_first_poem_ending_at(first_poem_end):
        third_verse_parent = 1 if first_poem_end == last else 2
        return _Work(tokens, subdivisions=[SubdivisionRow('BOOK', 0, '', None, 0, last),
                                           SubdivisionRow('POEM', 0, 'Prima', 0, 0, first_poem_end),
                                           SubdivisionRow('POEM', 1, 'Altera', 0, 10, last),
                                           SubdivisionRow('VERS', 0, 'arma', 1, 0, 3),
                                           SubdivisionRow('VERS', 1, 'Troiae', 1, 4, 9),
                                           SubdivisionRow('VERS', 0, 'Italiam', third_verse_parent, 10, last)])

    diff = compared([with_the_first_poem_ending_at(last)], [with_the_first_poem_ending_at(9)]).work_diffs[0]

    changes = diff.subdivision_changes_by_field
    assert [(c.new.typ, c.old_value, c.new_value) for c in changes['parent']] == [
        ('VERS', 'POEM 1 at 1.1.1#1', 'POEM 2 at 1.1.3#1')]
    assert [(c.new.typ, c.old_value, c.new_value) for c in changes['last token']] == [('POEM', '1.1.3#4', '1.1.2#6')]


def test_candidate_lemmas_are_compared_per_component(compared):
    def seque_with(lookup_form_lemma, enclitic_lemma):
        return _Work([_token('1.1.1', 'seque', enclitic='que',
                             lemmas_by_component_ordinal={0: {lookup_form_lemma}, 1: {enclitic_lemma}}),
                      _token('1.1.1', '.')])

    diff = compared([seque_with('sui', 'que')], [seque_with('que', 'sui')]).work_diffs[0]

    assert {name: [(pair.old.compared_values[name], pair.new.compared_values[name]) for pair in pairs]
            for name, pairs in diff.changed_token_pairs_by_field.items()} == {
        'candidate lemmas of the lookup form': [(frozenset({'sui'}), frozenset({'que'}))],
        'candidate lemmas of the enclitic': [(frozenset({'que'}), frozenset({'sui'}))]}


def test_a_moved_sentence_end_is_one_sentence_start(compared):
    joined = _tokens(ARMA, TROIAE, ITALIAM)
    joined[3]['ends_sentence'] = False

    diff = compared([_Work(_tokens(ARMA, TROIAE, ITALIAM))], [_Work(joined)]).work_diffs[0]

    assert [pair.new.location for pair in diff.changed_token_pairs_by_field['sentenceStart']] == ['1.1.2#1']
    assert {pair.new.reference for pair in diff.changed_token_pairs_by_field['wordIdx']} == {'1.1.2'}


def test_an_added_work_is_a_difference_unless_allowed(compared):
    old = [_Work(_tokens(ARMA))]
    new = [_Work(_tokens(ARMA)), _Work(_tokens(ARMA), name='Epigrammata')]

    assert compared(old, new).differs
    allowed = compared(old, new, allow_added_works=True)
    assert not allowed.differs
    assert 'Added work (allowed): Fictor: Epigrammata (4 tokens)' in report(allowed)


def test_a_work_whose_name_changed_is_paired_when_named(compared):
    old, new = [_Work(_tokens(ARMA))], [_Work(_tokens(ARMA), name='Carmina Selecta')]

    unpaired = compared(old, new)
    paired = compared(old, new, same_works=[('Fictor: Carmina', 'Fictor: Carmina Selecta')])

    assert (len(unpaired.removed_works), len(unpaired.added_works)) == (1, 1)
    assert (paired.removed_works, paired.added_works, paired.differs) == ([], [], False)


def test_a_new_work_paired_both_by_name_and_by_its_identity_is_refused(compared):
    old = [_Work(_tokens(ARMA), name='Prima'), _Work(_tokens(ARMA), name='Altera')]
    new = [_Work(_tokens(ARMA), name='Altera')]

    with pytest.raises(ComparisonError, match='both the old "Fictor: Altera" and, by --same-work, the old '
                                              '"Fictor: Prima"'):
        compared(old, new, same_works=[('Fictor: Prima', 'Fictor: Altera')])


@pytest.mark.parametrize('same_works, refused', [
    ([('Fictor: Prima', 'Fictor: Una'), ('Fictor: Altera', 'Fictor: Una')], 'names the new "Fictor: Una" twice'),
    ([('Fictor: Prima', 'Fictor: Una'), ('Fictor: Prima', 'Fictor: Duo')], 'names the old "Fictor: Prima" twice'),
])
def test_a_work_named_twice_is_refused(compared, same_works, refused):
    old = [_Work(_tokens(ARMA), name='Prima'), _Work(_tokens(ARMA), name='Altera')]
    new = [_Work(_tokens(ARMA), name='Una'), _Work(_tokens(ARMA), name='Duo')]

    with pytest.raises(ComparisonError, match=refused):
        compared(old, new, same_works=same_works)


def test_the_candidate_table_of_certain_macrons_is_read_too(tmp_path):
    work = _Work(_tokens(ARMA, TROIAE, ITALIAM))
    old = _database_with_new_ids(tmp_path / 'old.db', work)
    new = _database_with_new_ids(tmp_path / 'new.db', work, candidate_table='CountableWordCandidateInflections')

    assert not compare(old, new).differs


def test_main_says_whether_the_databases_differ(tmp_path, capsys):
    changed = _tokens(ARMA)
    changed[0]['properNounState'] = 2
    old = _database_with_new_ids(tmp_path / 'old.db', _Work(_tokens(ARMA)))
    same = _database_with_new_ids(tmp_path / 'same.db', _Work(_tokens(ARMA)))
    different = _database_with_new_ids(tmp_path / 'different.db', _Work(changed))
    not_a_reader_database = tmp_path / 'empty.db'
    sqlite3.connect(not_a_reader_database).close()

    assert [main([str(old), str(path)]) for path in (same, different, not_a_reader_database)] == [0, 1, 2]
    assert '1.1.1#1 arma: 0 → 2' in capsys.readouterr().out
