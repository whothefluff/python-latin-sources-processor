import csv

from scripts.dictionary import process_lexica

# The id of urn:cts:pdllex:lat.ls.perseus-eng2
_LEWIS_AND_SHORT_ID = "76fc5af5-1c88-5beb-a606-56ebf5b2c3a2"

_LEXICON = """<TEI.2><text><body><div0>
<entryFree key="amo" type="main"><orth>amo</orth> <sense level="1" n="I">to love</sense></entryFree>
</div0></body></text></TEI.2>"""


def _rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_the_dictionary_gets_the_id_of_its_urn_on_every_run(tmp_path):
    lexicon = tmp_path / "lexicon.xml"
    lexicon.write_text(_LEXICON, encoding="utf-8")

    for run in ("first", "second"):
        process_lexica.parse_xml_and_write_csv(str(lexicon), str(tmp_path / run))

    assert [row[0] for row in _rows(tmp_path / "first" / "dictionaries.csv")] == ["ID", _LEWIS_AND_SHORT_ID]
    for file_name in ("dictionary_entries.csv", "dict_entry_senses.csv"):
        assert [row[0] for row in _rows(tmp_path / "first" / file_name)] == ["dictionary", _LEWIS_AND_SHORT_ID]
    assert {path.name: path.read_bytes() for path in (tmp_path / "first").iterdir()} == {
        path.name: path.read_bytes() for path in (tmp_path / "second").iterdir()}
