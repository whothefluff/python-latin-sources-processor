import os
import re
import shutil
from pathlib import Path
from typing import List

import pandas as pd
import pytest

from scripts.common import publishing
from scripts.common.publishing import UNFINISHED_PUBLICATION, publish
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


def _files(directory: Path) -> dict:
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def test_aggregating_the_same_works_again_raises_and_saves_nothing(aggregated):
    before = _files(aggregated)

    with pytest.raises(ValueError, match="Works found more than once"):
        aggregate(TWO_WORKS_BY_ONE_AUTHOR, aggregated)
    assert _files(aggregated) == before


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
def test_an_author_that_differs_from_one_work_to_another_raises_and_nothing_is_saved(tmp_path, rows_in_carmina_altera,
                                                                                     runs):
    works = _copy_of_both_works(tmp_path)
    for file_name, rows in rows_in_carmina_altera.items():
        _replace_rows(works / 'carmina_altera' / file_name, rows)
    *earlier_runs, last_run = runs
    _aggregate_in_turn(works, earlier_runs, tmp_path / 'aggregate')
    (tmp_path / 'aggregate').mkdir(exist_ok=True)
    before = _files(tmp_path / 'aggregate')

    with pytest.raises(ValueError, match="Authors whose rows differ from one work to another: \\['Fictor'\\]"):
        aggregate(works / last_run, tmp_path / 'aggregate')
    assert _files(tmp_path / 'aggregate') == before


#: Stands for a file's header without its rows
_ONLY_THE_HEADER = object()


@pytest.mark.parametrize('runs', list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
@pytest.mark.parametrize('file_name, contents, problem', [
    ('work_abbreviations.csv', None, r'carmina_altera/work_abbreviations\.csv is missing'),
    ('work_contents.csv', None, r'carmina_altera/work_contents\.csv is missing'),
    ('works.csv', '', r"carmina_altera/works\.csv can't be read"),
    ('works.csv', _ONLY_THE_HEADER, r'carmina_altera/works\.csv has no rows'),
    ('work_contents.csv', _ONLY_THE_HEADER, r'carmina_altera/work_contents\.csv has no rows'),
    ('work_content_subdivisions.csv', _ONLY_THE_HEADER, r'carmina_altera/work_content_subdivisions\.csv has no rows'),
    ('authors.csv', _ONLY_THE_HEADER, r'carmina_altera/authors\.csv has no rows'),
    ('authors_and_works.csv', _ONLY_THE_HEADER, r'carmina_altera/authors_and_works\.csv has no rows'),
    ('work_abbreviations.csv', 'workId,id,value\n',
     r"carmina_altera/work_abbreviations\.csv has the columns \['workId', 'id', 'value'\] instead of "
     r"\['workId', 'id', 'val'\]"),
    ('work_abbreviations.csv', 'workId,id,val,lang\n',
     r"carmina_altera/work_abbreviations\.csv has the columns \['workId', 'id', 'val', 'lang'\] instead of "
     r"\['workId', 'id', 'val'\]"),
], ids=['a file missing', 'the contents missing', 'a file that can\'t be read', 'works without rows',
        'contents without rows', 'subdivisions without rows', 'authors without rows', 'authorships without rows',
        'other columns', 'one more column'])
def test_a_work_file_that_cant_be_aggregated_raises_and_nothing_is_saved(tmp_path, file_name, contents, problem, runs):
    works = _copy_of_both_works(tmp_path)
    path = works / 'carmina_altera' / file_name
    if contents is None:
        path.unlink()
    elif contents is _ONLY_THE_HEADER:
        path.write_text(path.read_text(encoding='utf-8').splitlines(keepends=True)[0], encoding='utf-8')
    else:
        path.write_text(contents, encoding='utf-8')
    *earlier_runs, last_run = runs
    _aggregate_in_turn(works, earlier_runs, tmp_path / 'aggregate')
    (tmp_path / 'aggregate').mkdir(exist_ok=True)
    before = _files(tmp_path / 'aggregate')

    with pytest.raises(ValueError, match=problem):
        aggregate(works / last_run, tmp_path / 'aggregate')
    assert _files(tmp_path / 'aggregate') == before


@pytest.mark.parametrize('file_name, contents, problem', [
    ('work_macronizations.csv', None, 'work_macronizations.csv is missing'),
    ('authors.csv', '', "authors.csv can't be read"),
    ('authors.csv', 'id,name,about,image\n', "authors.csv has no rows"),
    ('works.csv', 'id,name,about\n00000000-0000-4000-8000-000000000010,Carmina Prima,\n',
     "works.csv has the columns ['id', 'name', 'about'] instead of ['id', 'name', 'about', 'uvLowercase', "
     "'uvCapitals', 'ijLowercase', 'ijCapitals']"),
], ids=['a file missing', 'a file that can\'t be read', 'authors without rows', 'the columns of an older version'])
def test_an_aggregate_file_that_cant_be_aggregated_raises_and_nothing_is_saved(tmp_path, file_name, contents, problem):
    aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_prima', tmp_path)
    if contents is None:
        (tmp_path / file_name).unlink()
    else:
        (tmp_path / file_name).write_text(contents, encoding='utf-8')
    before = _files(tmp_path)

    with pytest.raises(ValueError, match=re.escape(problem)):
        aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_altera', tmp_path)
    assert _files(tmp_path) == before


def test_a_directory_without_library_files_isnt_a_work(tmp_path):
    works = _copy_of_both_works(tmp_path)
    (works / 'notes').mkdir()
    (works / 'notes' / 'readings.csv').write_text('word,reading\n', encoding='utf-8')

    aggregate(works, tmp_path / 'aggregate')

    assert _rows(_read(tmp_path / 'aggregate', 'works.csv')) == _rows_of_both_works('works.csv')


def _reverse_the_columns_of_every_file(directory: Path):
    for csv_path in directory.glob('*.csv'):
        data_frame = _read(directory, csv_path.name)
        data_frame[list(reversed(data_frame.columns))].to_csv(csv_path, index=False)


@pytest.mark.parametrize('runs', list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
def test_work_files_with_their_columns_in_another_order_are_aggregated_as_in_the_reader_order(tmp_path, runs):
    works = _copy_of_both_works(tmp_path)
    _reverse_the_columns_of_every_file(works / 'carmina_prima')
    _reverse_the_columns_of_every_file(works / 'carmina_altera')
    _aggregate_in_turn(TWO_WORKS_BY_ONE_AUTHOR, runs, tmp_path / 'from_the_reader_order')

    _aggregate_in_turn(works, runs, tmp_path / 'aggregate')

    assert list(_read(tmp_path / 'aggregate', 'work_macronizations.csv').columns) == [
        'workId', 'idx', 'macronizedWord', 'uncertaintyBitMask']
    assert _files(tmp_path / 'aggregate') == _files(tmp_path / 'from_the_reader_order')


def test_aggregate_files_with_their_columns_in_another_order_are_saved_as_in_the_reader_order(tmp_path):
    for output_dir in (tmp_path / 'aggregate', tmp_path / 'from_the_reader_order'):
        aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_prima', output_dir)
    _reverse_the_columns_of_every_file(tmp_path / 'aggregate')
    aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_altera', tmp_path / 'from_the_reader_order')

    aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_altera', tmp_path / 'aggregate')

    assert _files(tmp_path / 'aggregate') == _files(tmp_path / 'from_the_reader_order')


def test_a_work_is_added_after_the_works_already_aggregated_and_their_author_keeps_its_id(tmp_path):
    aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_altera', tmp_path)

    aggregate(TWO_WORKS_BY_ONE_AUTHOR / 'carmina_prima', tmp_path)

    assert list(_read(tmp_path, 'works.csv')['id']) == [CARMINA_ALTERA_ID, CARMINA_PRIMA_ID]
    assert list(_read(tmp_path, 'authors.csv')['id']) == [CARMINA_ALTERA_AUTHOR_ID]


def test_a_work_that_a_finished_publication_left_a_replaced_file_in_raises_and_nothing_is_saved(tmp_path):
    works = _copy_of_both_works(tmp_path)
    shutil.copyfile(works / 'carmina_altera' / 'work_contents.csv', works / 'carmina_altera' / '.work_contents.csv.old')

    with pytest.raises(FileExistsError, match=r"carmina_altera has files that a publication replaced and couldn't "
                                              r"remove: \.work_contents\.csv\.old"):
        aggregate(works, tmp_path / 'aggregate')
    assert _files(tmp_path / 'aggregate') == {}


def test_a_work_whose_publication_couldnt_be_undone_raises_and_nothing_is_saved(monkeypatch, tmp_path):
    # Carmina Prima has no work_macronizations.csv. Publishing Carmina Altera's files over it fails to move works.csv
    # in, and then to remove the work_macronizations.csv it added: Carmina Prima is left with its own files and Carmina
    # Altera's macronizations
    works = _copy_of_both_works(tmp_path)
    carmina_prima = works / 'carmina_prima'
    (carmina_prima / 'work_macronizations.csv').unlink()
    rename = os.replace
    unlink = Path.unlink

    def replace(source, target):
        if Path(source).name == '.works.csv.new':
            raise PermissionError(f"{target} is open in another program")
        rename(source, target)

    def unlink_all_but_the_macronizations(path, missing_ok=False):
        if path == carmina_prima / 'work_macronizations.csv':
            raise PermissionError(f"{path} is open in another program")
        unlink(path, missing_ok=missing_ok)

    with monkeypatch.context() as failing:
        failing.setattr(publishing.os, 'replace', replace)
        failing.setattr(Path, 'unlink', unlink_all_but_the_macronizations)
        with pytest.raises(OSError, match="couldn't be undone"):
            publish(works / 'carmina_altera', carmina_prima)
    assert not list(carmina_prima.glob('.*.old'))

    with pytest.raises(FileExistsError, match=rf"carmina_prima/{UNFINISHED_PUBLICATION}:\nA publication into "
                                              rf"{carmina_prima} didn't finish"):
        aggregate(works, tmp_path / 'aggregate')
    assert _files(tmp_path / 'aggregate') == {}


def _carmina_altera_by_the_author_id_of_carmina_prima(works: Path, name: str):
    _replace_rows(works / 'carmina_altera' / 'authors.csv',
                  [(CARMINA_PRIMA_AUTHOR_ID, name, 'An invented poet.', 'Zml4dHVyZQ==')])
    _replace_rows(works / 'carmina_altera' / 'authors_and_works.csv', [(CARMINA_PRIMA_AUTHOR_ID, CARMINA_ALTERA_ID)])
    _replace_rows(works / 'carmina_altera' / 'author_abbreviations.csv', [(CARMINA_PRIMA_AUTHOR_ID, 0, 'Fict.')])


@pytest.mark.parametrize('runs', list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
def test_an_author_id_under_two_names_raises_and_nothing_is_saved(tmp_path, runs):
    works = _copy_of_both_works(tmp_path)
    _carmina_altera_by_the_author_id_of_carmina_prima(works, 'Fictor Alter')
    *earlier_runs, last_run = runs
    _aggregate_in_turn(works, earlier_runs, tmp_path / 'aggregate')
    (tmp_path / 'aggregate').mkdir(exist_ok=True)
    before = _files(tmp_path / 'aggregate')

    with pytest.raises(ValueError, match=f"Author ids with more than one name: \\['{CARMINA_PRIMA_AUTHOR_ID}'\\]"):
        aggregate(works / last_run, tmp_path / 'aggregate')
    assert _files(tmp_path / 'aggregate') == before


@pytest.mark.parametrize('runs', list(AGGREGATION_RUNS.values()), ids=list(AGGREGATION_RUNS))
def test_an_author_id_under_one_name_in_both_works_is_one_author(tmp_path, runs):
    works = _copy_of_both_works(tmp_path)
    _carmina_altera_by_the_author_id_of_carmina_prima(works, 'Fictor')

    _aggregate_in_turn(works, runs, tmp_path / 'aggregate')

    assert _rows(_read(tmp_path / 'aggregate', 'authors.csv')) == [
        (CARMINA_PRIMA_AUTHOR_ID, 'Fictor', 'An invented poet.', 'Zml4dHVyZQ==')]
    assert _rows(_read(tmp_path / 'aggregate', 'authors_and_works.csv')) == [
        (CARMINA_PRIMA_AUTHOR_ID, CARMINA_PRIMA_ID), (CARMINA_PRIMA_AUTHOR_ID, CARMINA_ALTERA_ID)]


def test_the_work_directories_are_aggregated_in_path_order_whatever_order_they_are_listed_in(monkeypatch, tmp_path):
    rglob = Path.rglob
    monkeypatch.setattr(Path, 'rglob', lambda path, pattern: reversed(sorted(rglob(path, pattern))))

    aggregate(TWO_WORKS_BY_ONE_AUTHOR, tmp_path)

    assert list(_read(tmp_path, 'works.csv')['id']) == [CARMINA_ALTERA_ID, CARMINA_PRIMA_ID]
    assert list(_read(tmp_path, 'authors.csv')['id']) == [CARMINA_ALTERA_AUTHOR_ID]
