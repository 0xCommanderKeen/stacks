"""Consistent SQLite copies and private pre-upgrade recovery points."""

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4


def flush_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def snapshot_database(source, destination):
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(destination)) as writer:
                reader.backup(writer, pages=256)
                tables = {
                    row[0]
                    for row in writer.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                for table in ("login_session", "device_credential"):
                    if table in tables:
                        writer.execute(f"DELETE FROM {table}")
                if "backup_record" in tables:
                    writer.execute("DELETE FROM backup_record WHERE state IN ('queued', 'running')")
                writer.commit()
        with destination.open("rb") as snapshot:
            os.fsync(snapshot.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def before_upgrade(path, expected):
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as database:
        table = database.execute(
            "SELECT name FROM sqlite_master WHERE name='alembic_version'"
        ).fetchone()
        if table is None:
            if database.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("An unversioned catalog cannot be upgraded automatically.")
            return None
        row = database.execute("SELECT version_num FROM alembic_version").fetchone()
        current = row[0] if row else None
    if current == expected:
        return None
    directory = path.parent / "schema-backups"
    if directory.is_symlink():
        raise ValueError("Schema backup storage must not be a symlink.")
    directory.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # Versions come from the catalog; never interpolate them into a filesystem path.
    destination = directory / f"{stamp}-{uuid4().hex}.sqlite3"
    snapshot_database(path, destination)
    flush_directory(directory)
    flush_directory(path.parent)
    return destination
