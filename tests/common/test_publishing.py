import os
import shutil
from pathlib import Path

import pytest

from scripts.common import publishing
from scripts.common.publishing import UNFINISHED_PUBLICATION, publish


def _write(directory: Path, contents_by_name: dict):
    directory.mkdir(parents=True, exist_ok=True)
    for name, contents in contents_by_name.items():
        (directory / name).write_text(contents, encoding="utf-8")


def _contents(directory: Path) -> dict:
    return {path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()}


@pytest.fixture
def directories(tmp_path):
    """A working directory with a.csv, b.csv and c.csv, and an output directory with an older a.csv and c.csv, and
    d.csv"""
    _write(tmp_path / "working", {"a.csv": "new a", "b.csv": "new b", "c.csv": "new c"})
    _write(tmp_path / "output", {"a.csv": "old a", "c.csv": "old c", "d.csv": "old d"})
    return tmp_path / "working", tmp_path / "output"


def test_the_new_files_replace_those_with_the_same_names_and_the_others_stay(directories):
    working_dir, output_dir = directories

    publish(working_dir, output_dir)

    assert _contents(output_dir) == {"a.csv": "new a", "b.csv": "new b", "c.csv": "new c", "d.csv": "old d"}


def test_the_files_go_to_an_output_directory_that_doesnt_exist_yet(directories, tmp_path):
    working_dir, _ = directories

    publish(working_dir, tmp_path / "new" / "output")

    assert _contents(tmp_path / "new" / "output") == {"a.csv": "new a", "b.csv": "new b", "c.csv": "new c"}


@pytest.mark.parametrize("failing_rename", [("c.csv", ".c.csv.old"), (".c.csv.new", "c.csv"), (".b.csv.new", "b.csv")],
                         ids=["setting an old file aside", "moving a new file in", "adding a file"])
def test_a_rename_that_fails_leaves_the_output_directory_as_it_was(monkeypatch, directories, failing_rename):
    working_dir, output_dir = directories
    rename = os.replace

    def replace(source, target):
        if (Path(source).name, Path(target).name) == failing_rename:
            raise PermissionError(f"{source} is open in another program")
        rename(source, target)

    monkeypatch.setattr(publishing.os, "replace", replace)

    with pytest.raises(PermissionError):
        publish(working_dir, output_dir)
    assert _contents(output_dir) == {"a.csv": "old a", "c.csv": "old c", "d.csv": "old d"}


def test_a_copy_that_fails_leaves_the_output_directory_as_it_was(monkeypatch, directories):
    working_dir, output_dir = directories
    copy = shutil.copyfile

    def copyfile(source, target):
        if Path(source).name == "b.csv":
            raise OSError("No space left on device")
        return copy(source, target)

    monkeypatch.setattr(publishing.shutil, "copyfile", copyfile)

    with pytest.raises(OSError, match="No space left"):
        publish(working_dir, output_dir)
    assert _contents(output_dir) == {"a.csv": "old a", "c.csv": "old c", "d.csv": "old d"}


def _failing_renames(monkeypatch, *failing):
    rename = os.replace

    def replace(source, target):
        if (Path(source).name, Path(target).name) in failing:
            raise PermissionError(f"{source} is open in another program")
        rename(source, target)

    monkeypatch.setattr(publishing.os, "replace", replace)


def _failing_removals(monkeypatch, *failing):
    unlink = Path.unlink

    def unlink_all_but_the_failing(path, missing_ok=False):
        if path.name in failing:
            raise PermissionError(f"{path} is open in another program")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_all_but_the_failing)


def _unfinished_publication(output_dir: Path, *failures: str) -> str:
    """Returns what the record of a publication of a.csv, b.csv and c.csv into the output directory says"""
    return (f"A publication into {output_dir} didn't finish, so the CSV files there can be from two versions. It "
            f"replaces a.csv, c.csv, setting each aside as .<name>.old while it runs, and adds b.csv. To have the "
            f"files from before it, put each .<name>.old that's there back over its file and remove each file that it "
            f"adds. Then remove this file.\n"
            + "It failed, and these couldn't be undone:\n" + "".join(f"    {failure}\n" for failure in failures))


def test_the_record_of_the_publication_is_there_while_files_are_moved(monkeypatch, directories):
    working_dir, output_dir = directories
    rename = os.replace
    records = []

    def replace(source, target):
        records.append((output_dir / UNFINISHED_PUBLICATION).read_text(encoding="utf-8"))
        rename(source, target)

    monkeypatch.setattr(publishing.os, "replace", replace)

    publish(working_dir, output_dir)

    assert set(records) == {_unfinished_publication(output_dir).removesuffix(
        "It failed, and these couldn't be undone:\n")}
    assert len(records) == 5
    assert UNFINISHED_PUBLICATION not in _contents(output_dir)


def test_a_file_that_cant_be_put_back_stays_aside_with_the_record_and_the_rest_is_undone(monkeypatch, directories):
    working_dir, output_dir = directories
    _failing_renames(monkeypatch, (".c.csv.new", "c.csv"), (".a.csv.old", "a.csv"))

    with pytest.raises(OSError, match=r"\.a\.csv\.old, the a\.csv that .* had, couldn't be put back over the new one"):
        publish(working_dir, output_dir)
    assert _contents(output_dir) == {
        "a.csv": "new a", ".a.csv.old": "old a", "c.csv": "old c", "d.csv": "old d",
        UNFINISHED_PUBLICATION: _unfinished_publication(
            output_dir, f"{output_dir / '.a.csv.old'}, the a.csv that {output_dir} had, couldn't be put back over the "
                        f"new one: {output_dir / '.a.csv.old'} is open in another program")}


def test_a_publication_that_couldnt_be_undone_stops_every_later_one_even_without_files_set_aside(monkeypatch,
                                                                                                directories):
    working_dir, output_dir = directories
    _failing_renames(monkeypatch, (".c.csv.new", "c.csv"))
    _failing_removals(monkeypatch, "b.csv")
    with pytest.raises(OSError, match=r"b\.csv couldn't be removed, and .* didn't have it before"):
        publish(working_dir, output_dir)
    monkeypatch.undo()
    after_the_failure = _contents(output_dir)

    with pytest.raises(FileExistsError) as raised:
        publish(working_dir, output_dir)
    assert after_the_failure == {
        "a.csv": "old a", "b.csv": "new b", "c.csv": "old c", "d.csv": "old d",
        UNFINISHED_PUBLICATION: _unfinished_publication(
            output_dir, f"{output_dir / 'b.csv'} couldn't be removed, and {output_dir} didn't have it before: "
                        f"{output_dir / 'b.csv'} is open in another program")}
    assert str(raised.value) == f"{output_dir / UNFINISHED_PUBLICATION}:\n{after_the_failure[UNFINISHED_PUBLICATION]}"
    assert _contents(output_dir) == after_the_failure


def test_files_set_aside_by_a_publication_that_finished_stop_every_later_one_and_stay(directories):
    working_dir, output_dir = directories
    _write(output_dir, {".d.csv.old": "older d"})
    before = _contents(output_dir)

    with pytest.raises(FileExistsError) as raised:
        publish(working_dir, output_dir)
    assert str(raised.value) == (
        f"{output_dir} has files that a publication replaced and couldn't remove: .d.csv.old, the d.csv from before "
        f"it. The publication finished, so the files there are the new version. Each of these is the only copy of the "
        f"version it replaced: remove it once you're sure you don't want that version back")
    assert _contents(output_dir) == before


def test_a_replaced_file_that_cant_be_removed_stays_aside_once_published(monkeypatch, directories, caplog):
    working_dir, output_dir = directories
    _failing_removals(monkeypatch, ".a.csv.old")

    publish(working_dir, output_dir)

    assert _contents(output_dir) == {"a.csv": "new a", ".a.csv.old": "old a", "b.csv": "new b", "c.csv": "new c",
                                     "d.csv": "old d"}
    assert ".a.csv.old" in caplog.text


def test_a_record_that_cant_be_removed_once_published_stays_with_the_replaced_files_so_they_can_be_put_back(
        monkeypatch, directories, caplog):
    working_dir, output_dir = directories
    _failing_removals(monkeypatch, UNFINISHED_PUBLICATION)

    publish(working_dir, output_dir)
    monkeypatch.undo()
    after_publishing = _contents(output_dir)
    with pytest.raises(FileExistsError):
        publish(working_dir, output_dir)
    os.replace(output_dir / ".a.csv.old", output_dir / "a.csv")
    os.replace(output_dir / ".c.csv.old", output_dir / "c.csv")
    (output_dir / "b.csv").unlink()
    (output_dir / UNFINISHED_PUBLICATION).unlink()

    assert after_publishing == {"a.csv": "new a", ".a.csv.old": "old a", "b.csv": "new b", "c.csv": "new c",
                                ".c.csv.old": "old c", "d.csv": "old d",
                                UNFINISHED_PUBLICATION: _unfinished_publication(output_dir).removesuffix(
                                    "It failed, and these couldn't be undone:\n")}
    assert f"Published, but {output_dir / UNFINISHED_PUBLICATION} couldn't be removed" in caplog.text
    assert _contents(output_dir) == {"a.csv": "old a", "c.csv": "old c", "d.csv": "old d"}


def test_a_copy_that_cant_be_removed_is_in_the_error_and_the_record_and_the_rest_is_undone(monkeypatch, directories):
    working_dir, output_dir = directories
    _failing_renames(monkeypatch, (".c.csv.new", "c.csv"))
    _failing_removals(monkeypatch, ".c.csv.new")

    with pytest.raises(OSError, match=r"\.c\.csv\.new couldn't be removed"):
        publish(working_dir, output_dir)
    assert _contents(output_dir) == {
        "a.csv": "old a", ".c.csv.new": "new c", "c.csv": "old c", "d.csv": "old d",
        UNFINISHED_PUBLICATION: _unfinished_publication(
            output_dir, f"{output_dir / '.c.csv.new'} couldn't be removed: {output_dir / '.c.csv.new'} is open in "
                        f"another program")}


def test_a_publication_that_fails_before_moving_a_file_records_what_it_couldnt_undo(monkeypatch, directories):
    working_dir, output_dir = directories
    copy = shutil.copyfile

    def copyfile(source, target):
        if Path(source).name == "b.csv":
            raise OSError("No space left on device")
        return copy(source, target)

    monkeypatch.setattr(publishing.shutil, "copyfile", copyfile)
    _failing_removals(monkeypatch, ".a.csv.new")

    with pytest.raises(OSError, match=r"\.a\.csv\.new couldn't be removed"):
        publish(working_dir, output_dir)
    assert _contents(output_dir) == {
        "a.csv": "old a", ".a.csv.new": "new a", "c.csv": "old c", "d.csv": "old d",
        UNFINISHED_PUBLICATION: _unfinished_publication(
            output_dir, f"{output_dir / '.a.csv.new'} couldn't be removed: {output_dir / '.a.csv.new'} is open in "
                        f"another program")}


def test_a_record_that_cant_be_removed_after_a_complete_undo_is_in_the_error_and_stays(monkeypatch, directories):
    working_dir, output_dir = directories
    _failing_renames(monkeypatch, (".c.csv.new", "c.csv"))
    _failing_removals(monkeypatch, UNFINISHED_PUBLICATION)

    with pytest.raises(OSError, match=rf"{UNFINISHED_PUBLICATION} couldn't be written or removed"):
        publish(working_dir, output_dir)
    assert _contents(output_dir) == {"a.csv": "old a", "c.csv": "old c", "d.csv": "old d",
                                     UNFINISHED_PUBLICATION: _unfinished_publication(output_dir).removesuffix(
                                         "It failed, and these couldn't be undone:\n")}
