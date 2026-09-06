"""SIGKILL recovery at file checkpoints, exclusively in fresh synthetic directories."""

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import stacks.library as library_module
import stacks.trash as trash_module
from sqlalchemy import select
from stacks.library import Library
from stacks.models import Asset, ImportOperation, TrashFile
from stacks.samples import epub_bytes
from stacks.schemas import TrashRequest
from stacks.trash import Trash

IMPORT_POINTS = ("staged", "journaled", "renamed", "synced", "committed")
MOVE_POINTS = ("queued", "linked", "destination_synced", "unlinked", "source_synced", "receipted")


def kill():
    os.kill(os.getpid(), signal.SIGKILL)


def finish(trash):
    for _ in range(20):
        if not trash.step():
            return
    raise RuntimeError("Recovery did not converge within 20 steps")


def child(root, operation, point):
    library = Library(root / "data")
    if operation == "import":
        publish, rename, sync = library._publish, os.rename, library_module.sync_dir

        def intercepted_publish(operation_id):
            if point == "journaled":
                kill()
            result = publish(operation_id)
            if point == "committed":
                kill()
            return result

        def intercepted_rename(source, destination):
            rename(source, destination)
            if point == "renamed" and Path(source).parent == library.staging:
                kill()

        def intercepted_sync(path):
            sync(path)
            if (point == "staged" and path == library.staging) or (
                point == "synced" and path == library.managed
            ):
                kill()

        library._publish = intercepted_publish
        os.rename = intercepted_rename
        library_module.sync_dir = intercepted_sync
        library.import_file(root / "original.epub", "original.epub")
    else:
        trash = Trash(library)
        with library.sessions() as session:
            file = session.scalar(select(TrashFile).where(TrashFile.done.is_(False)))
            source, destination = library.managed / file.source, library.managed / file.destination
        if point == "queued":
            kill()
        link, unlink, sync = os.link, Path.unlink, trash_module.sync_dir

        def intercepted_link(src, dst):
            link(src, dst)
            if point == "linked" and Path(src) == source:
                kill()

        def intercepted_unlink(path, *args, **kwargs):
            unlink(path, *args, **kwargs)
            if point == "unlinked" and path == source:
                kill()

        def intercepted_sync(path):
            sync(path)
            if (
                point == "destination_synced"
                and path == destination.parent
                and destination.exists()
            ):
                kill()
            if point == "source_synced" and path == source.parent and not source.exists():
                kill()

        os.link, Path.unlink, trash_module.sync_dir = (
            intercepted_link,
            intercepted_unlink,
            intercepted_sync,
        )
        trash.step()
        if point == "receipted":
            kill()
    raise RuntimeError("Requested crash checkpoint was not reached")


def check_database(library):
    with closing(sqlite3.connect(library.data_dir / "catalog.sqlite3")) as database:
        assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert database.execute("PRAGMA foreign_key_check").fetchone() is None


def run_case(root, operation, point):
    root.mkdir()
    original = epub_bytes(f"Crash qualification {operation} {point}")
    source = root / "original.epub"
    source.write_bytes(original)
    expected = hashlib.sha256(original).hexdigest()
    library = Library(root / "data")
    before_ids = None
    if operation != "import":
        work = library.import_file(source, source.name).work
        rep = work.editions[0].representations[0]
        before_ids = (work.id, rep.id, rep.assets[0].id)
        trash = Trash(library)
        trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
        if operation == "restore":
            finish(trash)
            trash.request(
                work.id, TrashRequest(revision=library.get(work.id).revision, action="restore")
            )
    library.close()
    result = subprocess.run(
        [sys.executable, __file__, "--root", str(root), "--child", operation, "--point", point],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != -signal.SIGKILL:
        raise RuntimeError(f"{operation}/{point} did not SIGKILL: {result.stderr[-2000:]}")
    with closing(sqlite3.connect(root / "data/catalog.sqlite3")) as database:
        pending_ids = [row[0] for row in database.execute("SELECT id FROM import_operation")]
    survivors = [
        path
        for parent in (root / "data/staging", root / "data/managed")
        for path in parent.rglob("*")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected
    ]
    assert survivors, "No verified staged or managed original survived the process crash"
    assert source.read_bytes() == original
    library = Library(root / "data")
    try:
        if operation == "import":
            recovered = library.list()
            assert recovered.total == (0 if point == "staged" else 1)
            result = library.import_file(source, source.name)
            work = result.work
            assert result.duplicate == (point != "staged")
            if pending_ids:
                assert result.representation_id == pending_ids[0]
            with library.sessions() as session:
                assert all(
                    item.state == "complete" for item in session.scalars(select(ImportOperation))
                )
        else:
            trash = Trash(library)
            finish(trash)
            work = library.get(before_ids[0])
            current = trash.for_work(work.id)
            assert current.state == "complete"
            assert bool(work.trashed_at) == (operation == "trash")
            if operation == "trash":
                trash.request(work.id, TrashRequest(revision=work.revision, action="restore"))
                finish(trash)
                work = library.get(work.id)
        assert not work.trashed_at
        rep = work.editions[0].representations[0]
        ids = (work.id, rep.id, rep.assets[0].id)
        assert before_ids is None or ids == before_ids
        with library.sessions() as session:
            asset = session.get(Asset, rep.assets[0].id)
            assert library.resolve(asset.relative_path).read_bytes() == original
        assert library.import_file(source, source.name).duplicate
        assert library.list().total == 1
        check_database(library)
        return {
            "operation": operation,
            "checkpoint": point,
            "exit_signal": "SIGKILL",
            "verified_original_names_after_crash": len(survivors),
            "stable_identity": True,
            "duplicate_catalog_growth": 0,
            "original_sha256": expected,
            "integrity": "ok",
            "foreign_key_errors": 0,
        }
    finally:
        library.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--child", choices=("import", "trash", "restore"))
    parser.add_argument("--point")
    args = parser.parse_args()
    if args.child:
        child(args.root, args.child, args.point)
        return
    args.root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    cases = []
    for operation, points in (
        ("import", IMPORT_POINTS),
        ("trash", MOVE_POINTS),
        ("restore", MOVE_POINTS),
    ):
        for point in points:
            cases.append(run_case(args.root / f"{operation}-{point}", operation, point))
    report = {
        "cases": cases,
        "seconds": round(time.monotonic() - started, 3),
        "limitations": "Actual SIGKILL of a separate application-library process at instrumented "
        "file checkpoints. Parent opens a new Library and resumes journals. This is not host "
        "power loss or a storage-controller durability test. All originals are synthetic.",
    }
    (args.root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": len(cases), "seconds": report["seconds"]}))


if __name__ == "__main__":
    main()
