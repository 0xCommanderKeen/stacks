"""Consistent catalog/owned-file backups; external originals are protected separately."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from stacks.epub import safe_member
from stacks.library import Library, digest, sync_dir
from stacks.models import ImportOperation, TrashOperation
from stacks.snapshots import snapshot_database


def backup(library: Library, output: Path, mode="full", checkpoint=lambda size: None):
    if mode not in {"full", "catalog"}:
        raise ValueError("Choose full or catalog backup.")
    if output.resolve().is_relative_to(library.managed.resolve()):
        raise ValueError("Backup output must be outside managed publication storage.")
    if output.exists():
        raise ValueError("Backup destination already exists.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{uuid4().hex}.partial")

    def require_settled_files():
        with library.lock, library.sessions() as session:
            if session.scalar(
                select(ImportOperation.id).where(ImportOperation.state != "complete")
            ):
                raise ValueError("Recover unfinished imports before creating a full backup.")
            if session.scalar(select(TrashOperation.id).where(TrashOperation.state != "complete")):
                raise ValueError("Finish pending trash relocations before creating a full backup.")

    # Reject already-pending publication/moves without waiting for their file I/O.
    require_settled_files()
    try:
        # Serialize file publication/Trash, but release the catalog lock before any
        # hashing or archive I/O. Catalog queries, metadata edits and audio stay usable.
        with (
            library.ingest_lock,
            tempfile.TemporaryDirectory(prefix=".stacks-backup-", dir=output.parent) as scratch,
        ):
            checkpoint(0)
            db = Path(scratch) / "catalog.sqlite3"
            with library.lock:
                require_settled_files()
                snapshot_database(library.data_dir / "catalog.sqlite3", db)
            with closing(sqlite3.connect(db)) as catalog:
                external_roots = dict(
                    catalog.execute(
                        "SELECT root, count(*) FROM asset WHERE root != 'managed' GROUP BY root"
                    )
                )
                managed_count = catalog.execute(
                    "SELECT count(*) FROM asset WHERE root='managed'"
                ).fetchone()[0]
                if mode == "full":
                    for relative, size in catalog.execute(
                        "SELECT relative_path, size FROM asset WHERE root='managed'"
                    ):
                        original = library.resolve(relative)
                        if original.stat().st_size != size:
                            raise ValueError(
                                "An original file has changed; backup verification failed."
                            )
                for cover_id, size in catalog.execute("SELECT id, size FROM cover_blob"):
                    original = library.resolve(f".covers/{cover_id}/original")
                    if original.stat().st_size != size:
                        raise ValueError(
                            "A chosen cover original changed; backup verification failed."
                        )

                def files():
                    yield "catalog.sqlite3", db, None
                    if mode == "catalog":
                        for cover_id, sha, size in catalog.execute(
                            "SELECT id, sha256, size FROM cover_blob ORDER BY id"
                        ):
                            relative = f".covers/{cover_id}/original"
                            yield "managed/" + relative, library.resolve(relative), (sha, size)
                    else:
                        for file in library.managed.rglob("*"):
                            if file.is_symlink():
                                raise ValueError(
                                    "Managed storage contains a symlink; backup stopped."
                                )
                            if file.is_file():
                                relative = file.relative_to(library.managed).as_posix()
                                expected = catalog.execute(
                                    "SELECT sha256, size FROM asset "
                                    "WHERE root='managed' AND relative_path=?",
                                    (relative,),
                                ).fetchone()
                                parts = relative.split("/")
                                if (
                                    expected is None
                                    and len(parts) == 3
                                    and parts[0] == ".covers"
                                    and parts[2] == "original"
                                ):
                                    expected = catalog.execute(
                                        "SELECT sha256, size FROM cover_blob WHERE id=?",
                                        (parts[1],),
                                    ).fetchone()
                                yield "managed/" + relative, file, expected

                manifest = {
                    "version": 3 if mode == "catalog" else 2,
                    "files": {},
                    "external_roots": external_roots,
                }
                if mode == "catalog":
                    manifest.update(mode="catalog", managed_originals_omitted=managed_count)
                processed = 0
                with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_STORED) as archive:
                    for name, source, expected in files():
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
                                processed += len(chunk)
                                checkpoint(processed)
                        if expected is not None and expected != (checksum.hexdigest(), size):
                            raise ValueError(
                                "An original changed while being archived; backup stopped."
                            )
                        manifest["files"][name] = {"sha256": checksum.hexdigest(), "size": size}
                    archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            with temporary.open("rb") as file:
                os.fsync(file.fileno())
            os.link(temporary, output)
            sync_dir(output.parent)
            return manifest
    finally:
        temporary.unlink(missing_ok=True)


def restore(archive_path: Path, destination: Path, allow_missing_originals=False):
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
            if archive.getinfo("manifest.json").file_size > 128 * 1024**2:
                raise ValueError("Backup manifest too large.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("version") not in {1, 2, 3} or set(names) != {
                *manifest["files"],
                "manifest.json",
            }:
                raise ValueError("Unsupported or incomplete backup manifest.")
            catalog_only = manifest.get("version") == 3 and manifest.get("mode") == "catalog"
            if manifest.get("version") == 3 and not catalog_only:
                raise ValueError("Unsupported backup mode.")
            if catalog_only and not allow_missing_originals:
                raise ValueError(
                    "Catalog backup omits media originals. Explicitly allow missing originals "
                    "and restore media separately."
                )
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
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
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
                ("0010",),
                ("0011",),
                ("0012",),
                ("0013",),
                ("0014",),
                ("0015",),
            }:
                raise ValueError("This Stacks version cannot restore the backup schema.")
            external_roots = {}
            managed_count = 0
            for root, relative, sha, size in connection.execute(
                "SELECT root, relative_path, sha256, size FROM asset"
            ):
                if not safe_member(relative):
                    raise ValueError("Backup contains an unsafe asset path.")
                if root != "managed":
                    external_roots[root] = external_roots.get(root, 0) + 1
                    continue
                managed_count += 1
                if catalog_only:
                    continue
                file = scratch / "managed" / relative
                if not file.is_file() or file.stat().st_size != size or digest(file) != sha:
                    raise ValueError("Backup is missing a verified original asset.")
            if external_roots != manifest.get("external_roots", {}):
                raise ValueError("Backup external-original declarations do not match the catalog.")
            if external_roots and manifest["version"] not in {2, 3}:
                raise ValueError("This backup does not declare separately protected originals.")
            if catalog_only and managed_count != manifest.get("managed_originals_omitted"):
                raise ValueError("Backup missing-original declarations do not match the catalog.")
            if connection.execute(
                "SELECT name FROM sqlite_master WHERE name='cover_blob'"
            ).fetchone():
                for cover_id, sha, size in connection.execute(
                    "SELECT id, sha256, size FROM cover_blob"
                ):
                    if not safe_member(cover_id) or "/" in cover_id:
                        raise ValueError("Backup contains an unsafe cover identity.")
                    original = scratch / "managed" / ".covers" / cover_id / "original"
                    if (
                        not original.is_file()
                        or original.stat().st_size != size
                        or digest(original) != sha
                    ):
                        raise ValueError("Backup is missing a verified chosen cover original.")
            if catalog_only:
                (scratch / "MEDIA-RESTORE-REQUIRED.txt").write_text(
                    "Catalog-only recovery: publication originals were not included.\n"
                    "Restore managed originals from their separate snapshot "
                    "and configure external roots.\n"
                    "Rebuild thumbnails after original storage is available.\n"
                )
        if catalog_only:
            with (scratch / "MEDIA-RESTORE-REQUIRED.txt").open("rb") as marker:
                os.fsync(marker.fileno())
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
