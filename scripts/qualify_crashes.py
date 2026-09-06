"""SIGKILL recovery at file checkpoints, exclusively in fresh synthetic directories."""

import argparse
import errno
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
from unittest.mock import patch

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


def fault_case(root, fault):
    root.mkdir()
    source = root / "original.epub"
    original = epub_bytes(f"Storage fault {fault}")
    source.write_bytes(original)
    library = Library(root / "data")
    try:
        work = library.import_file(source, source.name).work
        rep = work.editions[0].representations[0]
        ids = (work.id, rep.id, rep.assets[0].id)
        trash = Trash(library)
        operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
        with library.sessions() as session:
            file = session.scalar(select(TrashFile))
        managed, destination = library.managed / file.source, library.managed / file.destination
        if fault in ("enospc", "eacces"):
            code = errno.ENOSPC if fault == "enospc" else errno.EACCES
            with patch.object(trash_module.os, "link", side_effect=OSError(code, "Injected")):
                assert trash.step()
            assert managed.read_bytes() == original and not destination.exists()
        elif fault == "collision":
            destination.parent.mkdir(parents=True)
            destination.write_bytes(original)
            assert not managed.samefile(destination)
            assert trash.step()
            assert managed.read_bytes() == destination.read_bytes() == original
            destination.unlink()  # Only the deliberately created unrelated fixture collision.
        elif fault == "changed_original":
            managed.write_bytes(b"synthetic unexpected replacement")
            assert trash.step()
            assert managed.read_bytes() == b"synthetic unexpected replacement"
            assert not destination.exists()
            managed.write_bytes(original)  # Restore this synthetic fault fixture before retry.
        failed = trash.operation(operation.id)
        assert failed.state == "error" and failed.completed == 0
    finally:
        library.close()
    library = Library(root / "data")
    try:
        trash = Trash(library)
        failed = trash.operation(operation.id)
        trash.retry(operation.id, failed.revision)
        finish(trash)
        assert trash.operation(operation.id).state == "complete"
        hidden = library.get(work.id)
        trash.request(work.id, TrashRequest(revision=hidden.revision, action="restore"))
        finish(trash)
        work = library.get(work.id)
        rep = work.editions[0].representations[0]
        assert (work.id, rep.id, rep.assets[0].id) == ids
        with library.sessions() as session:
            asset = session.get(Asset, rep.assets[0].id)
            assert library.resolve_asset(asset).read_bytes() == original
        check_database(library)
        return {
            "fault": fault,
            "classification": "simulated errno"
            if fault in ("enospc", "eacces")
            else "actual synthetic filesystem condition",
            "explicit_error": True,
            "retry_after_restart": "complete",
            "identity_preserved": True,
        }
    finally:
        library.close()


def source_faults(root):
    root.mkdir()
    external = root / "external"
    external.mkdir()
    original = epub_bytes("External fault qualification")
    (external / "book.epub").write_bytes(original)
    library = Library(root / "data", {"archive": external})
    try:
        work = library.register_files("archive", ["book.epub"]).work
        rep = work.editions[0].representations[0]
        with library.sessions() as session:
            asset = session.get(Asset, rep.assets[0].id)
        relocated = root / "relocated"
        external.rename(relocated)
        try:
            library.resolve_asset(asset).read_bytes()
        except (OSError, ValueError):
            pass
        else:
            raise AssertionError("Missing source root unexpectedly resolved")
        assert library.get(work.id).id == work.id
        library.sources["archive"] = relocated
        assert library.resolve_asset(asset).read_bytes() == original
        path = relocated / "book.epub"
        path.chmod(0)
        try:
            try:
                library.resolve_asset(asset).read_bytes()
            except PermissionError:
                pass
            else:
                raise AssertionError("Permission fault requires an unprivileged process")
            assert library.get(work.id).id == work.id
        finally:
            path.chmod(0o444)
        assert library.resolve_asset(asset).read_bytes() == original
        assert library.register_files("archive", ["book.epub"]).duplicate
        check_database(library)
        return {
            "missing_root": "catalog retained; relocated root restored byte access",
            "unreadable_original": "actual mode000 read denied; bytes retained",
            "duplicate_catalog_growth": 0,
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
    faults = [
        fault_case(args.root / fault, fault)
        for fault in ("enospc", "eacces", "collision", "changed_original")
    ]
    sources = source_faults(args.root / "source-faults")
    report = {
        "cases": cases,
        "storage_faults": faults,
        "source_faults": sources,
        "seconds": round(time.monotonic() - started, 3),
        "limitations": "Actual SIGKILL of a separate application-library process at instrumented "
        "file checkpoints. Parent opens a new Library and resumes journals. This is not host "
        "power loss or a storage-controller durability test. All originals are synthetic.",
    }
    (args.root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": len(cases), "seconds": report["seconds"]}))


if __name__ == "__main__":
    main()
