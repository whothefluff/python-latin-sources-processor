"""Compares two databases built by the reader's importer, work by work and token by token.

Usage: python -m scripts.tools.compare_reader_databases OLD.db NEW.db [--same-work OLD NEW]... [--allow-added-works]
       [--examples N]

Exit status: 0 when nothing differs, 1 when something does, 2 when the databases can't be compared.
"""
import argparse
import bisect
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple, cast

COMPARED_WORK_CONTENTS_COLUMNS = ('word', 'tokenType', 'macronizedWord', 'uncertaintyBitMask', 'properNounState',
                                  'enclitic', 'expansion', 'wordIdx')
CANDIDATE_LEMMAS_BY_COMPONENT_ORDINAL = {0: 'candidate lemmas of the lookup form',
                                         1: 'candidate lemmas of the enclitic'}
COMPARED_TOKEN_FIELDS = ('word', 'tokenType', 'macronizedWord', 'uncertaintyBitMask', 'properNounState', 'enclitic',
                         'expansion', 'sentenceStart', 'wordIdx', *CANDIDATE_LEMMAS_BY_COMPONENT_ORDINAL.values())
CANDIDATE_TABLE_NAMES = ('CountableWordCandidateAnalyses', 'CountableWordCandidateInflections')
REQUIRED_TABLE_NAMES = {'Works', 'Authors', 'AuthorsAndWorks', 'WorkContents', 'WorkContentSubdivisions',
                        'MorphologicalDetails'}


class ComparisonError(Exception):
    pass


class WorkIdentity(NamedTuple):
    authors: str
    name: str

    def __str__(self):
        return f'{self.authors}: {self.name}' if self.authors else self.name


@dataclass(frozen=True)
class Token:
    idx: int
    reference: str
    position_in_reference: int
    compared_values: Dict[str, object]

    @property
    def location(self) -> str:
        return f'{self.reference}#{self.position_in_reference}'

    @property
    def word(self) -> str:
        return cast(str, self.compared_values['word'])


@dataclass(frozen=True)
class Subdivision:
    node: str
    parent: Optional[str]
    typ: str
    cnt: int
    name: str
    from_idx: int
    to_idx: int
    depth: int
    #: None in a database without edition labels
    edition_label: Optional[str]


@dataclass
class Work:
    identity: WorkIdentity
    tokens: List[Token]
    subdivisions: List[Subdivision]
    tokens_by_idx: Dict[int, Token] = field(init=False)

    def __post_init__(self):
        self.tokens_by_idx = {token.idx: token for token in self.tokens}

    def location_of(self, idx: int) -> str:
        token = self.tokens_by_idx.get(idx)
        return token.location if token else f'idx {idx}'

    def label_of(self, subdivision: Optional[Subdivision]) -> str:
        if subdivision is None:
            return 'none'
        return f'{subdivision.typ} {subdivision.cnt + 1} at {self.location_of(subdivision.from_idx)}'


class TokenPair(NamedTuple):
    old: Token
    new: Token


class SubdivisionChange(NamedTuple):
    new: Subdivision
    old_value: str
    new_value: str


@dataclass
class WorkDiff:
    old: Work
    new: Work
    added_tokens: List[Token] = field(default_factory=list)
    removed_tokens: List[Token] = field(default_factory=list)
    moved_tokens: List[TokenPair] = field(default_factory=list)
    changed_token_pairs_by_field: Dict[str, List[TokenPair]] = field(default_factory=lambda: defaultdict(list))
    added_subdivisions: List[Subdivision] = field(default_factory=list)
    removed_subdivisions: List[Subdivision] = field(default_factory=list)
    subdivision_changes_by_field: Dict[str, List[SubdivisionChange]] = field(
        default_factory=lambda: defaultdict(list))

    @property
    def differs(self) -> bool:
        return bool(self.added_tokens or self.removed_tokens or self.moved_tokens
                    or self.changed_token_pairs_by_field or self.added_subdivisions or self.removed_subdivisions
                    or self.subdivision_changes_by_field)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ComparisonError(f'{path} is not a file')
    return sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)


def _table_names_without_shadow_tables(db: sqlite3.Connection) -> List[str]:
    sql_by_name = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' "
                                  "AND name NOT LIKE 'sqlite_%'").fetchall())
    virtual_tables = [name for name, sql in sql_by_name.items()
                      if (sql or '').upper().startswith('CREATE VIRTUAL TABLE')]
    return sorted(name for name in sql_by_name if not any(name.startswith(f'{v}_') for v in virtual_tables))


def count_rows_by_table(path: Path) -> Dict[str, int]:
    db = _connect(path)
    try:
        return {name: db.execute(f'SELECT COUNT( * ) FROM "{name}"').fetchone()[0]
                for name in _table_names_without_shadow_tables(db)}
    finally:
        db.close()


def _identities_by_work_id(db: sqlite3.Connection, path: Path) -> Dict[str, WorkIdentity]:
    author_names_by_work_id = defaultdict(list)
    for work_id, author_name in db.execute('''SELECT AuthorsAndWorks.workId, Authors.name
                                                  FROM AuthorsAndWorks
                                                  INNER JOIN Authors ON Authors.id = AuthorsAndWorks.authorId'''):
        author_names_by_work_id[work_id].append(author_name)
    identities = {}
    for work_id, name in db.execute('SELECT id, name FROM Works'):
        identity = WorkIdentity(', '.join(sorted(author_names_by_work_id[work_id])), name)
        if identity in identities.values():
            raise ComparisonError(f'{path} has two works that are {identity}, which can\'t be told apart')
        identities[work_id] = identity
    return identities


def _candidate_lemmas_by_token(db: sqlite3.Connection, candidate_table: str) -> Dict[Tuple[str, int], Dict]:
    lemmas = defaultdict(lambda: defaultdict(set))
    for work_id, idx, component_ordinal, dictionary_ref in db.execute(
            f'''SELECT Candidates.workId, Candidates.idx, Candidates.componentOrdinal, Details.dictionaryRef
                    FROM "{candidate_table}" AS Candidates
                    INNER JOIN MorphologicalDetails AS Details
                        ON Details.form = Candidates.form AND Details.item = Candidates.item'''):
        lemmas[(work_id, idx)][component_ordinal].add(dictionary_ref)
    return lemmas


def _tokens_by_work_id(db: sqlite3.Connection, candidate_table: str) -> Dict[str, List[Token]]:
    lemmas = _candidate_lemmas_by_token(db, candidate_table)
    tokens = defaultdict(list)
    tokens_so_far_by_reference = defaultdict(int)
    previous_sentence_idx_by_work_id = {}
    for work_id, idx, reference, sentence_idx, *columns in db.execute(
            f'''SELECT workId, idx, sourceReference, sentenceIdx, {", ".join(COMPARED_WORK_CONTENTS_COLUMNS)}
                    FROM WorkContents
                    ORDER BY workId, idx'''):
        tokens_so_far_by_reference[(work_id, reference)] += 1
        values = dict(zip(COMPARED_WORK_CONTENTS_COLUMNS, columns))
        # one moved sentence boundary is one difference, while every sentenceIdx after it would change
        values['sentenceStart'] = previous_sentence_idx_by_work_id.get(work_id) != sentence_idx
        previous_sentence_idx_by_work_id[work_id] = sentence_idx
        token_lemmas = lemmas.get((work_id, idx), {})
        for component_ordinal, name in CANDIDATE_LEMMAS_BY_COMPONENT_ORDINAL.items():
            values[name] = frozenset(token_lemmas.get(component_ordinal, ()))
        tokens[work_id].append(Token(idx, reference, tokens_so_far_by_reference[(work_id, reference)], values))
    return tokens


def _has_edition_labels(db: sqlite3.Connection) -> bool:
    return any(column == 'editionLabel' for _, column, *_ in db.execute('PRAGMA table_info( WorkContentSubdivisions )'))


def has_edition_labels(path: Path) -> bool:
    db = _connect(path)
    try:
        return _has_edition_labels(db)
    finally:
        db.close()


def _subdivisions_by_work_id(db: sqlite3.Connection) -> Dict[str, List[Subdivision]]:
    edition_label = 'editionLabel' if _has_edition_labels(db) else 'NULL'
    rows = db.execute(f'''SELECT workId, node, parent, typ, cnt, name, fromIndex, toIndex, {edition_label}
                              FROM WorkContentSubdivisions''').fetchall()
    parents = {(work_id, node): parent for work_id, node, parent, *_ in rows}
    subdivisions = defaultdict(list)
    for work_id, node, parent, typ, cnt, name, from_idx, to_idx, label in rows:
        depth, ancestor = 0, parent
        while ancestor and depth <= len(rows):
            depth, ancestor = depth + 1, parents.get((work_id, ancestor))
        subdivisions[work_id].append(Subdivision(node, parent or None, typ, cnt, name, from_idx, to_idx, depth,
                                                 label))
    for work_subdivisions in subdivisions.values():
        work_subdivisions.sort(key=lambda s: (s.from_idx, s.depth, s.cnt))
    return subdivisions


def read_works(path: Path) -> Dict[WorkIdentity, Work]:
    db = _connect(path)
    try:
        table_names = set(_table_names_without_shadow_tables(db))
        candidate_table = next((name for name in CANDIDATE_TABLE_NAMES if name in table_names), None)
        missing = sorted(REQUIRED_TABLE_NAMES - table_names) + (
            [] if candidate_table else [' or '.join(CANDIDATE_TABLE_NAMES)])
        if candidate_table is None or missing:
            raise ComparisonError(f'{path} has no {", ".join(missing)}: is it a reader database?')
        tokens = _tokens_by_work_id(db, candidate_table)
        subdivisions = _subdivisions_by_work_id(db)
        return {identity: Work(identity, tokens[work_id], subdivisions[work_id])
                for work_id, identity in _identities_by_work_id(db, path).items()}
    finally:
        db.close()


def _pair_tokens_within_each_reference(diff: WorkDiff) -> List[TokenPair]:
    old_by_reference, new_by_reference = defaultdict(list), defaultdict(list)
    for token in diff.old.tokens:
        old_by_reference[token.reference].append(token)
    for token in diff.new.tokens:
        new_by_reference[token.reference].append(token)
    pairs = []
    for reference in dict.fromkeys([*new_by_reference, *old_by_reference]):
        old, new = old_by_reference.get(reference, []), new_by_reference.get(reference, [])
        matcher = SequenceMatcher(None, [t.word for t in old], [t.word for t in new], autojunk=False)
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag == 'equal' or (tag == 'replace' and old_end - old_start == new_end - new_start):
                pairs.extend(TokenPair(*pair) for pair in zip(old[old_start:old_end], new[new_start:new_end]))
            else:
                diff.removed_tokens.extend(old[old_start:old_end])
                diff.added_tokens.extend(new[new_start:new_end])
    diff.removed_tokens.sort(key=lambda t: t.idx)
    diff.added_tokens.sort(key=lambda t: t.idx)
    return pairs


def _pairs_out_of_reading_order(pairs: List[TokenPair]) -> List[TokenPair]:
    """Returns the pairs outside a longest increasing subsequence of their new indices in old order: the fewest
    tokens that explain how the new reading order differs."""
    by_old_order = sorted(pairs, key=lambda pair: pair.old.idx)
    smallest_tail_by_length, tail_position_by_length = [], []
    predecessor_positions: List[Optional[int]] = [None] * len(by_old_order)
    for position, pair in enumerate(by_old_order):
        length = bisect.bisect_left(smallest_tail_by_length, pair.new.idx)
        if length == len(smallest_tail_by_length):
            smallest_tail_by_length.append(pair.new.idx)
            tail_position_by_length.append(position)
        else:
            smallest_tail_by_length[length] = pair.new.idx
            tail_position_by_length[length] = position
        predecessor_positions[position] = tail_position_by_length[length - 1] if length else None
    in_order = set()
    if tail_position_by_length:
        position = tail_position_by_length[-1]
        while True:
            in_order.add(position)
            predecessor = predecessor_positions[position]
            if predecessor is None:
                break
            position = predecessor
    return [pair for position, pair in enumerate(by_old_order) if position not in in_order]


def _compare_tokens(diff: WorkDiff) -> Dict[int, int]:
    pairs = _pair_tokens_within_each_reference(diff)
    for pair in sorted(pairs, key=lambda pair: pair.new.idx):
        for name in COMPARED_TOKEN_FIELDS:
            if pair.old.compared_values[name] != pair.new.compared_values[name]:
                diff.changed_token_pairs_by_field[name].append(pair)
    diff.moved_tokens.extend(sorted(_pairs_out_of_reading_order(pairs), key=lambda pair: pair.new.idx))
    return {pair.old.idx: pair.new.idx for pair in pairs}


def _compare_subdivisions(diff: WorkDiff, new_idx_by_old_idx: Dict[int, int], compares_edition_labels: bool):
    unpaired_by_type_depth_and_first_token = defaultdict(list)
    for subdivision in diff.new.subdivisions:
        unpaired_by_type_depth_and_first_token[(subdivision.typ, subdivision.depth, subdivision.from_idx)].append(
            subdivision)
    pairs = []
    for old in diff.old.subdivisions:
        candidates = unpaired_by_type_depth_and_first_token.get(
            (old.typ, old.depth, new_idx_by_old_idx.get(old.from_idx)))
        if candidates:
            pairs.append((old, candidates.pop(0)))
        else:
            diff.removed_subdivisions.append(old)
    diff.added_subdivisions.extend(sorted((s for unpaired in unpaired_by_type_depth_and_first_token.values()
                                           for s in unpaired), key=lambda s: (s.from_idx, s.depth, s.cnt)))

    new_node_by_old_node = {old.node: new.node for old, new in pairs}
    old_by_node = {s.node: s for s in diff.old.subdivisions}
    new_by_node = {s.node: s for s in diff.new.subdivisions}
    changes = diff.subdivision_changes_by_field
    for old, new in pairs:
        if new_idx_by_old_idx.get(old.to_idx) != new.to_idx:
            changes['last token'].append(
                SubdivisionChange(new, diff.old.location_of(old.to_idx), diff.new.location_of(new.to_idx)))
        if new_node_by_old_node.get(old.parent) != new.parent:
            changes['parent'].append(SubdivisionChange(new, diff.old.label_of(old_by_node.get(old.parent)),
                                                       diff.new.label_of(new_by_node.get(new.parent))))
        if old.cnt != new.cnt:
            changes['cnt'].append(SubdivisionChange(new, str(old.cnt), str(new.cnt)))
        if old.name != new.name:
            changes['name'].append(SubdivisionChange(new, repr(old.name), repr(new.name)))
        if compares_edition_labels and old.edition_label != new.edition_label:
            changes['editionLabel'].append(SubdivisionChange(new, _shown(old.edition_label),
                                                             _shown(new.edition_label)))


def compare_works(old: Work, new: Work, compares_edition_labels: bool = True) -> WorkDiff:
    diff = WorkDiff(old, new)
    _compare_subdivisions(diff, _compare_tokens(diff), compares_edition_labels)
    return diff


@dataclass
class Comparison:
    work_diffs: List[WorkDiff]
    removed_works: List[Work]
    added_works: List[Work]
    old_row_counts_by_table: Dict[str, int]
    new_row_counts_by_table: Dict[str, int]
    old_has_edition_labels: bool
    new_has_edition_labels: bool
    allow_added_works: bool = False

    @property
    def differs(self) -> bool:
        return (any(diff.differs for diff in self.work_diffs) or bool(self.removed_works)
                or (bool(self.added_works) and not self.allow_added_works))


def _new_identity_by_old_identity(old_works: Dict[WorkIdentity, Work], new_works: Dict[WorkIdentity, Work],
                                  same_works: Sequence[Tuple[str, str]]) -> Dict[WorkIdentity, WorkIdentity]:
    """Returns each old work's counterpart: the one --same-work names, or else the one with its identity.
    Every work has one counterpart at most."""
    old_by_name = {str(identity): identity for identity in old_works}
    new_by_name = {str(identity): identity for identity in new_works}
    named = {}
    for old_name, new_name in same_works:
        for name, works_by_name, which in ((old_name, old_by_name, 'old'), (new_name, new_by_name, 'new')):
            if name not in works_by_name:
                raise ComparisonError(f'the {which} database has no work "{name}"; '
                                      f'it has {", ".join(sorted(works_by_name))}')
        if old_by_name[old_name] in named:
            raise ComparisonError(f'--same-work names the old "{old_name}" twice')
        if new_by_name[new_name] in named.values():
            raise ComparisonError(f'--same-work names the new "{new_name}" twice')
        named[old_by_name[old_name]] = new_by_name[new_name]
    counterparts = dict(named)
    for identity in old_works:
        if identity not in named and identity in new_works:
            if identity in named.values():
                raise ComparisonError(f'the new "{identity}" is both the old "{identity}" and, by --same-work, the '
                                      f'old "{next(old for old, new in named.items() if new == identity)}"')
            counterparts[identity] = identity
    return counterparts


def compare(old_path: Path, new_path: Path, same_works: Sequence[Tuple[str, str]] = (),
            allow_added_works: bool = False) -> Comparison:
    old_works, new_works = read_works(old_path), read_works(new_path)
    counterparts = _new_identity_by_old_identity(old_works, new_works, same_works)
    old_has_edition_labels, new_has_edition_labels = has_edition_labels(old_path), has_edition_labels(new_path)
    compares_edition_labels = old_has_edition_labels and new_has_edition_labels
    return Comparison(
        work_diffs=[compare_works(old_works[old], new_works[new], compares_edition_labels)
                    for old, new in counterparts.items()],
        removed_works=[work for identity, work in old_works.items() if identity not in counterparts],
        added_works=[work for identity, work in new_works.items() if identity not in counterparts.values()],
        old_row_counts_by_table=count_rows_by_table(old_path),
        new_row_counts_by_table=count_rows_by_table(new_path),
        old_has_edition_labels=old_has_edition_labels,
        new_has_edition_labels=new_has_edition_labels,
        allow_added_works=allow_added_works,
    )


def _shown(value) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, frozenset):
        return '{' + ', '.join(sorted(ref or "''" for ref in value)) + '}'
    return str(value)


def _section(title: str, count: int, items: List[str], examples: int) -> List[str]:
    shown = items if examples <= 0 else items[:examples]
    lines = [f'  {title}: {count}', *(f'    {item}' for item in shown)]
    if len(shown) < len(items):
        lines.append(f'    …and {len(items) - len(shown)} more')
    return lines


def _moved_runs(diff: WorkDiff) -> List[str]:
    runs = []
    for pair in diff.moved_tokens:
        if runs and runs[-1][-1].new.idx + 1 == pair.new.idx and runs[-1][-1].new.reference == pair.new.reference:
            runs[-1].append(pair)
        else:
            runs.append([pair])
    return [f'{run[0].new.location}–{run[-1].new.location} now after '
            f'{diff.new.location_of(run[0].new.idx - 1) if run[0].new.idx else "nothing"}'
            for run in runs]


def _work_report(diff: WorkDiff, examples: int) -> List[str]:
    title = str(diff.new.identity) if diff.old.identity == diff.new.identity \
        else f'{diff.old.identity} → {diff.new.identity}'
    lines = [f'{title}: {len(diff.old.tokens):,} → {len(diff.new.tokens):,} tokens']
    if not diff.differs:
        return lines + ['  no differences']
    for section_title, tokens in (('tokens removed', diff.removed_tokens), ('tokens added', diff.added_tokens)):
        if tokens:
            lines += _section(section_title, len(tokens), [f'{t.location} {t.word}' for t in tokens], examples)
    if diff.moved_tokens:
        lines += _section('tokens moved', len(diff.moved_tokens), _moved_runs(diff), examples)
    for name in COMPARED_TOKEN_FIELDS:
        pairs = diff.changed_token_pairs_by_field.get(name, [])
        if pairs:
            lines += _section(name, len(pairs), [f'{new.location} {new.word}: {_shown(old.compared_values[name])} → '
                                                 f'{_shown(new.compared_values[name])}' for old, new in pairs],
                              examples)
    for section_title, work, subdivisions in (('subdivisions removed', diff.old, diff.removed_subdivisions),
                                              ('subdivisions added', diff.new, diff.added_subdivisions)):
        if subdivisions:
            lines += _section(section_title, len(subdivisions), [work.label_of(s) for s in subdivisions], examples)
    for name, changes in diff.subdivision_changes_by_field.items():
        lines += _section(f'subdivision {name}', len(changes),
                          [f'{diff.new.label_of(change.new)}: {change.old_value} → {change.new_value}'
                           for change in changes], examples)
    return lines


def report(comparison: Comparison, examples: int = 10) -> List[str]:
    lines = [f'Removed work: {work.identity} ({len(work.tokens):,} tokens)' for work in comparison.removed_works]
    allowed = ' (allowed)' if comparison.allow_added_works else ''
    lines += [f'Added work{allowed}: {work.identity} ({len(work.tokens):,} tokens)' for work in comparison.added_works]
    for diff in comparison.work_diffs:
        lines += _work_report(diff, examples)
    old_counts, new_counts = comparison.old_row_counts_by_table, comparison.new_row_counts_by_table
    changed_counts = [f'  {name}: {old_counts.get(name, 0):,} → {new_counts.get(name, 0):,}'
                      for name in sorted(set(old_counts) | set(new_counts))
                      if old_counts.get(name) != new_counts.get(name)]
    if changed_counts:
        lines += ['Row counts that changed (for information)', *changed_counts]
    without_edition_labels = [which for which, has_them in (('old', comparison.old_has_edition_labels),
                                                            ('new', comparison.new_has_edition_labels)) if not has_them]
    if without_edition_labels:
        lines.append('Edition labels not compared: ' + (f'the {without_edition_labels[0]} database has none'
                                                        if len(without_edition_labels) == 1
                                                        else 'neither database has them'))
    return lines + ['Differences found' if comparison.differs else 'No differences']


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Compares two databases built by the reader\'s importer.')
    parser.add_argument('old', type=Path)
    parser.add_argument('new', type=Path)
    parser.add_argument('--same-work', nargs=2, action='append', default=[], metavar=('OLD', 'NEW'),
                        help='pairs an old work with a new one whose authors or name changed ("Authors: Name")')
    parser.add_argument('--allow-added-works', action='store_true',
                        help='doesn\'t count works only in the new database as differences')
    parser.add_argument('--examples', type=int, default=10, help='examples shown per difference, 0 for all')
    options = parser.parse_args(arguments)
    try:
        comparison = compare(options.old, options.new, options.same_work, options.allow_added_works)
    except (ComparisonError, sqlite3.Error) as error:
        print(f'Can\'t compare: {error}', file=sys.stderr)
        return 2
    print('\n'.join(report(comparison, options.examples)))
    return 1 if comparison.differs else 0


if __name__ == '__main__':
    sys.exit(main())
