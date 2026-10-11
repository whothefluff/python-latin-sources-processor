import pandas as pd

from scripts.library.process_library_aggregate import find_repeated_works


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
