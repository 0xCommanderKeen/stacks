"""Consistent catalog/owned-file backups; external originals are protected separately."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from stacks.epub import safe_member
from stacks.library import Library, digest, sync_dir
from stacks.models import Asset, ImportOperation


def backup(library: Library, output: Path):
    if output.exists():
        raise ValueError("Backup destination already exists.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{uuid4().hex}.partial")
    try:
        with library.lock, tempfile.TemporaryDirectory() as scratch:
            with library.sessions() as session:
                pending = session.scalar(
                    select(ImportOperation.id).where(ImportOperation.state != "complete")
                )
                if pending:
                    raise ValueError("Recover unfinished imports before creating a full backup.")
                external_roots = {}
                for asset in session.scalars(select(Asset)):
                    if asset.root != "managed":
                        external_roots[asset.root] = external_roots.get(asset.root, 0) + 1
                        continue
                    original = library.resolve_asset(asset)
                    if original.stat().st_size != asset.size or digest(original) != asset.sha256:
                        raise ValueError(
                            "An original file has changed; backup verification failed."
                        )
            db = Path(scratch) / "catalog.sqlite3"
            with sqlite3.connect(library.data_dir / "catalog.sqlite3") as source:
                with sqlite3.connect(db) as target:
                    source.backup(target)
                    target.execute("DELETE FROM login_session")
                    target.commit()
            files = {"catalog.sqlite3": db}
            for file in library.managed.rglob("*"):
                if file.is_symlink():
                    raise ValueError("Managed storage contains a symlink; backup stopped.")
                if file.is_file():
                    files[file.relative_to(library.data_dir).as_posix()] = file
            manifest = {"version": 2, "files": {}, "external_roots": external_roots}
            with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_STORED) as archive:
                for name, source in sorted(files.items()):
                    checksum = hashlib.sha256()
                    size = 0
                    with (
                        source.open("rb") as reader,
                        archive.open(name, "w", force_zip64=True) as writer,
                    ):
                        while chunk := reader.read(1024**2):
                            writer.write(chunk)
                            checksum.update(chunk)
                            size += len(chunk)
                    manifest["files"][name] = {"sha256": checksum.hexdigest(), "size": size}
                archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            with temporary.open("rb") as file:
                os.fsync(file.fileno())
            # Hard-link publication cannot overwrite a concurrently created destination.
            os.link(temporary, output)
            sync_dir(output.parent)
    finally:
        temporary.unlink(missing_ok=True)


def restore(archive_path: Path, destination: Path):
    """Restore only into a nonexistent directory. Existing libraries cannot be overwritten."""
    if destination.exists():
        raise ValueError(
            "Restore destination must not exist. Stop Stacks and choose a new directory."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".stacks-restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if len(names) != len(set(names)) or any(not safe_member(n) for n in names):
                raise ValueError("Invalid backup paths.")
            if archive.getinfo("manifest.json").file_size > 20 * 1024**2:
                raise ValueError("Backup manifest too large.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("version") not in {1, 2} or set(names) != {
                *manifest["files"],
                "manifest.json",
            }:
                raise ValueError("Unsupported or incomplete backup manifest.")
            for name, expected in manifest["files"].items():
                if name != "catalog.sqlite3" and not name.startswith("managed/"):
                    raise ValueError("Unexpected backup content.")
                if archive.getinfo(name).file_size != expected["size"]:
                    raise ValueError("Backup file size mismatch.")
                target = scratch / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("xb") as writer:
                    shutil.copyfileobj(source, writer, 1024**2)
                    writer.flush()
                    os.fsync(writer.fileno())
                if digest(target) != expected["sha256"]:
                    raise ValueError("Backup checksum mismatch.")
        db = scratch / "catalog.sqlite3"
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Backup database failed integrity checking.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Backup database has broken relationships.")
            if connection.execute("SELECT version_num FROM alembic_version").fetchone() not in {
                ("0001",),
                ("0002",),
                ("0003",),
                ("0004",),
                ("0005",),
                ("0006",),
                ("0007",),
                ("0008",),
                ("0009",),
            }:
                raise ValueError("This Stacks version cannot restore the backup schema.")
            external_roots = {}
            for root, relative, sha, size in connection.execute(
                "SELECT root, relative_path, sha256, size FROM asset"
            ):
                if not safe_member(relative):
                    raise ValueError("Backup contains an unsafe asset path.")
                if root != "managed":
                    external_roots[root] = external_roots.get(root, 0) + 1
                    continue
                file = scratch / "managed" / relative
                if not file.is_file() or file.stat().st_size != size or digest(file) != sha:
                    raise ValueError("Backup is missing a verified original asset.")
            if external_roots != manifest.get("external_roots", {}):
                raise ValueError("Backup external-original declarations do not match the catalog.")
            if external_roots and manifest["version"] != 2:
                raise ValueError("This backup does not declare separately protected originals.")
        # Flush names as well as bytes before publishing the complete data directory.
        for directory in sorted((p for p in scratch.rglob("*") if p.is_dir()), reverse=True):
            sync_dir(directory)
        sync_dir(scratch)
        if destination.exists():
            raise ValueError("Restore destination was created while restoring.")
        os.rename(scratch, destination)
        sync_dir(destination.parent)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
