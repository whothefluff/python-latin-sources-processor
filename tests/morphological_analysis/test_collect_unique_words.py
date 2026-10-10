import csv

import pytest

from scripts.morphological_analysis.process_morpheus_perseids_api import MorphologicalAnalyzer


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
    ],
    ids=["expansions", "deduplication", "empty-fields", "no-expansion-column"],
)
def test_collect_unique_words(tmp_path, columns, rows, expected):
    input_file = tmp_path / "output" / "library" / "work_contents.csv"
    input_file.parent.mkdir(parents=True)
    with input_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    analyzer = MorphologicalAnalyzer(str(tmp_path))

    assert analyzer.unique_words == expected
