import shutil
from pathlib import Path
from typing import List

import pandas as pd
import pytest

from scripts.library.process_library_aggregate import aggregate, find_repeated_works

TWO_WORKS_BY_ONE_AUTHOR = Path(__file__).parent / 'fixtures' / 'two_works_by_one_author'
CARMINA_PRIMA_ID = '00000000-0000-4000-8000-000000000010'
CARMINA_ALTERA_ID = '00000000-0000-4000-8000-000000000020'
CARMINA_PRIMA_AUTHOR_ID = '00000000-0000-4000-8000-000000000011'
CARMINA_ALTERA_AUTHOR_ID = '00000000-0000-4000-8000-000000000021'

READER_PRIMARY_KEYS = {
    'works.csv': ['id'],
    'authors.csv': ['id'],
    'authors_and_works.csv': ['authorId', 'workId'],
    'author_abbreviations.csv': ['authorId', 'id'],
    'work_abbreviations.csv': ['workId', 'id'],
    'work_contents.csv': ['workId', 'idx'],
    'work_content_subdivisions.csv': ['workId', 'node'],
    'work_content_supplementary.csv': ['workId', 'typ', 'cnt'],
    'work_macronizations.csv': ['workId', 'idx'],
    'unambiguous_macronizations.csv': ['word'],
}

AGREED_UNAMBIGUOUS_MACRONIZATIONS = {
    'ad': 'ad', 'amicum': 'amīcum', 'et': 'et', 'Roma': 'Rōma', 'est': 'est', 'aura': 'aura', '.': '.',
    'de': 'dē', 'speculo': 'speculō', 'speculum': 'speculum',
}
# levis is lĕvis wherever Carmina Prima is certain of it, and lēvis wherever Carmina Altera is
CERTAIN_MACRONIZATIONS_OF_LEVIS = {
    (CARMINA_PRIMA_ID, '2', 'Levis', '0'),
    (CARMINA_PRIMA_ID, '8', 'levis', '0'),
    (CARMINA_ALTERA_ID, '2', 'lēvis', '0'),
}
# The directories of the two works to aggregate, one run each
AGGREGATION_RUNS = {'both works at once': ['.'], 'one work after the other': ['carmina_prima', 'carmina_altera']}


def _library(work_id, work_name, *author_names):
    return {
        'works.csv': pd.DataFrame({'id': [work_id], 'name': [work_name]}),
        'authors.csv': pd.DataFrame({'id': [f'{work_id}-{name}' for name in author_names],
                                     'name': list(author_names)}),
        'authors_and_works.csv': pd.DataFrame({'authorId': [f'{work_id}-{name}' for name in author_names],
                                               'workId': [work_id] * len(author_names)}),
    }


def test_a_work_already_aggregated_is_repeated_under_a_new_id():
    existing = _library('old-id', 'Fabulae Aesopiae', 'Phaedrus')
    again = _library('new-id', 'Fabulae Aesopiae', 'Phaedrus')

    assert find_repeated_works([existing, again]) == [('Phaedrus', 'Fabulae Aesopiae')]


def test_works_with_the_same_name_by_other_authors_are_not_repeated():
    catullus = _library('a', 'Carmina', 'Catullus')
    horace = _library('b', 'Carmina', 'Horatius')

    assert find_repeated_works([catullus, horace]) == []


def test_nothing_is_repeated_without_existing_aggregate_files():
    assert find_repeated_works([{}, _library('a', 'Fabulae Aesopiae', 'Phaedrus')]) == []


def _read(directory: Path, file_name: str) -> pd.DataFrame:
    return pd.read_csv(directory / file_name, dtype=str, keep_default_na=False)


def _rows(data_frame: pd.DataFrame) -> list:
    return sorted(map(tuple, data_frame.values))


def _rows_of_both_works(file_name: str) -> list:
    return _rows(pd.concat([_read(work_dir, file_name)
                            for work_dir in TWO_WORKS_BY_ONE_AUTHOR.iterdir() if work_dir.is_dir()]))


def _aggregate_in_turn(works: Path, runs: List[str], output_dir: Path):
    for directory in runs:
        aggregate(works / directory, output_dir)


@pytest.fixture(params=list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
def aggregated(request, tmp_path):
    _aggregate_in_turn(TWO_WORKS_BY_ONE_AUTHOR, request.param, tmp_path)
    return tmp_path


@pytest.mark.parametrize('file_name', ['works.csv', 'work_contents.csv', 'work_content_subdivisions.csv'])
def test_both_works_keep_their_rows(aggregated, file_name):
    assert _rows(_read(aggregated, file_name)) == _rows_of_both_works(file_name)


def test_both_works_keep_their_own_macronizations(aggregated):
    assert set(_rows_of_both_works('work_macronizations.csv')) <= set(
        _rows(_read(aggregated, 'work_macronizations.csv')))


def test_aggregating_the_same_works_again_saves_nothing(aggregated):
    before = {path.name: path.read_bytes() for path in aggregated.glob('*.csv')}

    aggregate(TWO_WORKS_BY_ONE_AUTHOR, aggregated)

    assert {path.name: path.read_bytes() for path in aggregated.glob('*.csv')} == before


def test_the_aggregate_keeps_the_reader_primary_keys_unique(aggregated):
    repeated = {file_name: _read(aggregated, file_name)[key].duplicated().sum()
                for file_name, key in READER_PRIMARY_KEYS.items()}

    assert {file_name: count for file_name, count in repeated.items() if count} == {}


def test_only_the_macronizations_that_both_works_agree_on_are_unambiguous(aggregated):
    assert _rows(_read(aggregated, 'unambiguous_macronizations.csv')) == sorted(
        AGREED_UNAMBIGUOUS_MACRONIZATIONS.items())


def test_each_certain_occurrence_of_a_word_that_the_works_disagree_on_gets_its_own_macronization(aggregated):
    added = set(_rows(_read(aggregated, 'work_macronizations.csv'))) - set(
        _rows_of_both_works('work_macronizations.csv'))

    assert added == CERTAIN_MACRONIZATIONS_OF_LEVIS


def test_the_author_of_both_works_is_one_author(aggregated):
    authors = _read(aggregated, 'authors.csv')
    authorships = _read(aggregated, 'authors_and_works.csv')
    abbreviations = _read(aggregated, 'author_abbreviations.csv')

    assert list(authors['name']) == ['Fictor']
    assert set(authorships['authorId']) == set(authors['id'])
    assert len(authorships) == 2
    assert list(abbreviations['val']) == ['Fict.']


def _copy_of_both_works(tmp_path: Path) -> Path:
    works = tmp_path / 'works'
    shutil.copytree(TWO_WORKS_BY_ONE_AUTHOR, works)
    return works


def _add_rows(csv_path: Path, rows: list):
    existing = _read(csv_path.parent, csv_path.name)
    pd.concat([existing, pd.DataFrame(rows, columns=existing.columns)]).to_csv(csv_path, index=False)


def _replace_rows(csv_path: Path, rows: list):
    pd.DataFrame(rows, columns=_read(csv_path.parent, csv_path.name).columns).to_csv(csv_path, index=False)


@pytest.mark.parametrize('runs', list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
def test_a_word_that_the_reader_would_look_up_under_a_numeral_gets_its_own_macronization(tmp_path, runs):
    # Carmina Prima is certain of i as ī ("go!") and has it capitalized mid-sentence, which the reader looks up as I
    # before i. Carmina Altera has the numeral I, unambiguous as I.
    works = _copy_of_both_works(tmp_path)
    _add_rows(works / 'carmina_prima' / 'work_contents.csv', [
        (CARMINA_PRIMA_ID, 11, 'et', '1.1.3', 0, 1, 3, 0, None, None),
        (CARMINA_PRIMA_ID, 12, 'I', '1.1.3', None, 1, 3, 1, None, None)])
    _add_rows(works / 'carmina_prima' / 'unambiguous_macronizations.csv', [('i', 'ī')])
    _add_rows(works / 'carmina_altera' / 'work_contents.csv', [
        (CARMINA_ALTERA_ID, 10, 'I', '1.1.3', 0, 3, 3, 0, None, 'ūnus')])
    _add_rows(works / 'carmina_altera' / 'unambiguous_macronizations.csv', [('I', 'I')])

    _aggregate_in_turn(works, runs, tmp_path / 'aggregate')

    added = set(_rows(_read(tmp_path / 'aggregate', 'work_macronizations.csv'))) - set(
        _rows_of_both_works('work_macronizations.csv'))
    assert added == CERTAIN_MACRONIZATIONS_OF_LEVIS | {(CARMINA_PRIMA_ID, '12', 'Ī', '0')}


@pytest.mark.parametrize('runs', list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
@pytest.mark.parametrize('rows_in_carmina_altera', [
    {'authors.csv': [(CARMINA_ALTERA_AUTHOR_ID, 'Fictor', 'Another poet.', 'Zml4dHVyZQ==')]},
    {'author_abbreviations.csv': [(CARMINA_ALTERA_AUTHOR_ID, 0, 'Fic.')]},
    {'author_abbreviations.csv': [(CARMINA_ALTERA_AUTHOR_ID, 0, 'Fict.'), (CARMINA_ALTERA_AUTHOR_ID, 1, 'Fic.')]},
    {'author_abbreviations.csv': [(CARMINA_ALTERA_AUTHOR_ID, 1, 'Fict.')]},
    {'authors.csv': [(CARMINA_PRIMA_AUTHOR_ID, 'Fictor', 'An invented poet.', 'Zml4dHVyZQ==')],
     'authors_and_works.csv': [(CARMINA_PRIMA_AUTHOR_ID, CARMINA_ALTERA_ID)],
     'author_abbreviations.csv': [(CARMINA_PRIMA_AUTHOR_ID, 0, 'Fic.')]},
], ids=['another about', 'another abbreviation', 'one more abbreviation', 'the abbreviation under another id',
        'another abbreviation under the same author id'])
def test_nothing_is_saved_when_an_author_differs_from_one_work_to_another(tmp_path, rows_in_carmina_altera, runs):
    works = _copy_of_both_works(tmp_path)
    for file_name, rows in rows_in_carmina_altera.items():
        _replace_rows(works / 'carmina_altera' / file_name, rows)
    *earlier_runs, last_run = runs
    _aggregate_in_turn(works, earlier_runs, tmp_path / 'aggregate')
    before = {path.name: path.read_bytes() for path in (tmp_path / 'aggregate').glob('*.csv')}

    aggregate(works / last_run, tmp_path / 'aggregate')

    assert {path.name: path.read_bytes() for path in (tmp_path / 'aggregate').glob('*.csv')} == before
