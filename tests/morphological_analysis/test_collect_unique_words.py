import csv

import pytest

from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer


def _write_work_contents(tmp_path, columns, rows):
    input_file = tmp_path / "output" / "library" / "work_contents.csv"
    input_file.parent.mkdir(parents=True)
    with input_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


@pytest.mark.parametrize(
    "columns, rows, expected",
    [
        (
            ["word", "expansion"],
            [["M.", "Mārcus"], ["I", "ūnum"], ["VENIT", ""]],
            {"m.", "marcus", "i", "unum", "venit"},
        ),
        (
            ["word", "expansion"],
            [["M.", "Mārcus"], ["M.", "MĀRCUS"], ["Marcus", ""], ["marcus", ""]],
            {"m.", "marcus"},
        ),
        (
            ["word", "expansion"],
            [["", "Mārcus"], ["", ""], ["Roma"]],
            {"marcus", "roma"},
        ),
        (
            ["word"],
            [["Roma"], ["ROMA"], [""]],
            {"roma"},
        ),
        (
            ["word", "enclitic"],
            [["populusque", "que"], ["Tune", "ne"], ["ne", ""], ["agedum", "dum"]],
            {"populusque", "-que", "tune", "-ne", "ne", "agedum", "-dum"},
        ),
    ],
    ids=["expansions", "deduplication", "empty-fields", "no-expansion-column", "enclitics"],
)
def test_collect_unique_words(tmp_path, columns, rows, expected):
    _write_work_contents(tmp_path, columns, rows)

    analyzer = MorphologicalAnalyzer(str(tmp_path))

    assert analyzer.unique_words == expected


def test_a_detached_enclitic_needs_a_full_override(tmp_path):
    _write_work_contents(tmp_path, ["word", "enclitic"], [["uirumue", "ue"]])

    with pytest.raises(ValueError, match="'-ue'"):
        MorphologicalAnalyzer(str(tmp_path))
