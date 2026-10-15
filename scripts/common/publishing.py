import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List

#: The file that a publication writes before it moves any file, and removes once it has moved them all or undone them
UNFINISHED_PUBLICATION = '.unfinished-publication.txt'


def raise_for_publication_leftovers(directory: Path):
    """Raises when a publication into directory didn't finish, so that its files can be from two versions, or when one
    finished but couldn't remove the .<name>.old files that it set aside."""
    record = directory / UNFINISHED_PUBLICATION
    if record.exists():
        raise FileExistsError(f"{record}:\n{record.read_text(encoding='utf-8')}")
    files_set_aside = sorted(path.name for path in directory.glob('.*.csv.old'))
    if files_set_aside:
        raise FileExistsError(
            f"{directory} has files that a publication replaced and couldn't remove: "
            + ", ".join(f"{name}, the {name.removeprefix('.').removesuffix('.old')} from before it"
                        for name in files_set_aside)
            + ". The publication finished, so the files there are the new version. Each of these is the only copy of "
              "the version it replaced: remove it once you're sure you don't want that version back")


def _unfinished_publication(output_dir: Path, names_to_replace: List[str], names_to_add: List[str]) -> str:
    return (f"A publication into {output_dir} didn't finish, so the CSV files there can be from two versions. It "
            f"replaces {', '.join(names_to_replace) or 'no file'}, setting each aside as .<name>.old while it runs, "
            f"and adds {', '.join(names_to_add) or 'no file'}. To have the files from before it, put each .<name>.old "
            f"that's there back over its file and remove each file that it adds. Then remove this file.\n")


def _undo(output_dir: Path, names_replaced: List[str], names_added: List[str], copies: Dict[str, Path],
          replaced: Dict[str, Path]) -> List[str]:
    """Removes the files that output_dir didn't have, puts back the ones it had and removes the copies, each step on
    its own. Returns the steps that failed."""
    failures = []
    for name in names_added:
        try:
            (output_dir / name).unlink()
        except OSError as e:
            failures.append(f"{output_dir / name} couldn't be removed, and {output_dir} didn't have it before: {e}")
    for name in names_replaced:
        try:
            os.replace(replaced[name], output_dir / name)
        except OSError as e:
            failures.append(f"{replaced[name]}, the {name} that {output_dir} had, couldn't be put back over the new "
                            f"one: {e}")
    for copy in copies.values():
        try:
            copy.unlink(missing_ok=True)
        except OSError as e:
            failures.append(f"{copy} couldn't be removed: {e}")
    return failures


def publish(working_dir: Path, output_dir: Path):
    """Moves the CSV files of working_dir into output_dir, replacing the files with the same names, all of them or none.
    Copies them next to their targets first, writes UNFINISHED_PUBLICATION, renames each target to .<name>.old and the
    copy to the target, and removes UNFINISHED_PUBLICATION and then the .<name>.old files. When UNFINISHED_PUBLICATION
    can't be removed, the .<name>.old files stay with it, so that what it says still holds. When a copy or a rename
    fails, removes the new files, puts back the ones that output_dir had and raises; whatever can't be undone is in the
    error and in UNFINISHED_PUBLICATION, which stays. While it's there, or a .<name>.old file, every later publication
    into output_dir, and every script that reads it, refuses to start (raise_for_publication_leftovers)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    raise_for_publication_leftovers(output_dir)
    names = sorted(path.name for path in working_dir.glob('*.csv'))
    copies = {name: output_dir / f'.{name}.new' for name in names}
    replaced = {name: output_dir / f'.{name}.old' for name in names}
    record = output_dir / UNFINISHED_PUBLICATION
    names_to_replace = [name for name in names if (output_dir / name).exists()]
    unfinished_publication = _unfinished_publication(output_dir, names_to_replace,
                                                     [name for name in names if name not in names_to_replace])
    names_replaced: List[str] = []
    names_added: List[str] = []
    try:
        for name in names:
            shutil.copyfile(working_dir / name, copies[name])
        record.write_text(unfinished_publication, encoding='utf-8')
        for name in names:
            if name in names_to_replace:
                os.replace(output_dir / name, replaced[name])
                names_replaced.append(name)
                os.replace(copies[name], output_dir / name)
            else:
                os.replace(copies[name], output_dir / name)
                names_added.append(name)
    except BaseException as e:
        failures = _undo(output_dir, names_replaced, names_added, copies, replaced)
        try:
            if failures:
                with record.open('a', encoding='utf-8') as unfinished:
                    unfinished.write(("" if record.stat().st_size else unfinished_publication)
                                     + "It failed, and these couldn't be undone:\n"
                                     + "".join(f"    {failure}\n" for failure in failures))
            else:
                record.unlink(missing_ok=True)
        except OSError as record_error:
            failures.append(f"{record} couldn't be written or removed: {record_error}")
        if failures:
            raise OSError("Publishing failed and couldn't be undone:\n"
                          + "\n".join(f"    {failure}" for failure in failures)) from e
        raise
    try:
        record.unlink()
    except OSError as e:
        logging.warning(f"Published, but {record} couldn't be removed: {e}. The files that this publication replaced "
                        f"stay with it, set aside as .<name>.old, so that what it says still holds. Publications into "
                        f"{output_dir} and the scripts that read it refuse to start until they're gone. This "
                        f"publication finished: to keep its files, remove {record}, and then each .<name>.old once "
                        f"you're sure you don't want that version back")
    else:
        for name in names_replaced:
            try:
                replaced[name].unlink()
            except OSError as e:
                logging.warning(f"Published, but {replaced[name]}, the {name} that it replaced, couldn't be removed: "
                                f"{e}. Publications into {output_dir} and the scripts that read it refuse to start "
                                f"until it's gone; remove it once you're sure you don't want that version back")
