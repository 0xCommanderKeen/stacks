"""Versioned JSON portability through consistent snapshots and incremental rows."""

import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

import ijson
from sqlalchemy import Boolean, Float, Integer
from sqlalchemy.exc import SQLAlchemyError

from stacks import models
from stacks.db import initialize
from stacks.epub import safe_member
from stacks.schemas import FieldOrigin, PersonalValues, RecordEdit
from stacks.snapshots import flush_directory, snapshot_database

SCHEMA_VERSION = 15
FORMAT_VERSION = 1
TABLE_NAMES = (
    "cover_blob",
    "work",
    "contributor",
    "credit",
    "edition",
    "representation",
    "asset",
    "series",
    "series_membership",
    "work_redirect",
    "catalog_operation",
    "collection",
    "collection_entry",
    "progress",
    "personal_state",
    "reading_record",
    "intake_job",
    "scan_directory",
    "inbox_candidate",
    "intake_item",
    "trash_operation",
    "trash_file",
    "metadata_suggestion",
    "backup_record",
    "import_operation",
)
TABLES = {name: models.Base.metadata.tables[name] for name in TABLE_NAMES}
ROOT = re.compile(r"[a-z][a-z0-9_-]{0,63}")


def roots_in(database):
    roots = {"managed": {"kind": "managed"}}
    for table in ("asset", "inbox_candidate", "intake_job"):
        for (root,) in database.execute(
            f"SELECT DISTINCT root FROM {table} WHERE root IS NOT NULL"
        ):
            if root and root != "managed":
                roots[root] = {"kind": "external"}
    return roots


def write_catalog(library, output):
    """Write one JSON row at a time; never hold the catalog lock while serializing."""
    if output.resolve().is_relative_to(library.managed.resolve()):
        raise ValueError("Catalog output must be outside managed publication storage.")
    if output.exists():
        raise ValueError("Catalog output already exists.")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.name}.{uuid4().hex}.partial")
    try:
        with tempfile.TemporaryDirectory(prefix="stacks-export-", dir=output.parent) as scratch:
            snapshot = Path(scratch) / "catalog.sqlite3"
            with library.lock:
                snapshot_database(library.data_dir / "catalog.sqlite3", snapshot)
            with (
                closing(sqlite3.connect(snapshot)) as database,
                os.fdopen(
                    os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
                ) as target,
            ):
                database.row_factory = sqlite3.Row
                for name in ("import_operation", "trash_operation"):
                    if database.execute(
                        f"SELECT 1 FROM {name} WHERE state!='complete' LIMIT 1"
                    ).fetchone():
                        raise ValueError(
                            "Finish pending file operations before exporting the catalog."
                        )
                target.write('{"format_version":1,"schema_version":15,"roots":')
                json.dump(roots_in(database), target, ensure_ascii=False)
                target.write(',"tables":{')
                for index, (name, table) in enumerate(TABLES.items()):
                    target.write(("," if index else "") + json.dumps(name) + ":[")
                    keys = ",".join(column.name for column in table.primary_key.columns)
                    first = True
                    for row in database.execute(f"SELECT * FROM {name} ORDER BY {keys}"):
                        target.write("" if first else ",")
                        value = dict(row)
                        for column in table.columns:
                            if isinstance(column.type, Boolean) and value[column.name] is not None:
                                value[column.name] = bool(value[column.name])
                        if any(
                            isinstance(field, str) and len(field) > 16 * 1024 * 1024
                            for field in value.values()
                        ):
                            raise ValueError("A catalog field exceeds the portable format limit.")
                        json.dump(value, target, ensure_ascii=False, allow_nan=False)
                        first = False
                    target.write("]")
                target.write("}}\n")
                target.flush()
                os.fsync(target.fileno())
            os.link(partial, output)
            flush_directory(output.parent)
    finally:
        partial.unlink(missing_ok=True)


class Reader:
    """Small grammar for the existing JSON envelope; each table is consumed once."""

    def __init__(self, source):
        self.events = iter(ijson.basic_parse(source, use_float=True))

    def next(self):
        try:
            return next(self.events)
        except StopIteration:
            raise ValueError("The catalog is truncated.") from None

    def expect(self, event, value=None):
        actual, found = self.next()
        if actual != event or (value is not None and found != value):
            raise ValueError("Invalid catalog structure.")
        return found

    def value(self, first=None, depth=0):
        if depth > 8:
            raise ValueError("Catalog JSON nesting exceeds the format limit.")
        event, value = first or self.next()
        if event == "start_map":
            result = {}
            while True:
                event, key = self.next()
                if event == "end_map":
                    return result
                if event != "map_key" or key in result or len(result) >= 1000:
                    raise ValueError("Duplicate or excessive catalog object keys.")
                result[key] = self.value(depth=depth + 1)
        if event in {"string", "number", "boolean", "null"}:
            if isinstance(value, str) and len(value) > 16 * 1024 * 1024:
                raise ValueError("A catalog field exceeds the format limit.")
            return value
        raise ValueError("Invalid catalog value.")


def validate_row(name, row):
    table = TABLES[name]
    if not isinstance(row, dict) or set(row) != {column.name for column in table.columns}:
        raise ValueError(f"Invalid columns in {name}.")
    for column in table.columns:
        value = row[column.name]
        if value is None:
            if not column.nullable:
                raise ValueError(f"Missing required value in {name}.")
            continue
        if isinstance(column.type, Boolean):
            valid = type(value) is bool
        elif isinstance(column.type, Integer):
            valid = type(value) is int and -(2**63) <= value < 2**63
        elif isinstance(column.type, Float):
            valid = type(value) in {int, float} and math.isfinite(value)
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError(f"Invalid value type in {name}.")
        field = column.name
        if field == "id" or field.endswith("_id"):
            if name == "trash_file" and field == "id":
                valid_id = bool(re.fullmatch(r"[0-9a-f]{32}", value))
            else:
                valid_id = str(UUID(value)) == value
            if not valid_id:
                raise ValueError(f"Invalid identity in {name}.")
        if field in {"relative_path", "cover_path", "source", "destination"}:
            if not safe_member(value) or value in {".", ""} or "\x00" in value:
                raise ValueError(f"Unsafe relative path in {name}.")
        if field == "root" and value and not ROOT.fullmatch(value):
            raise ValueError("Invalid source alias.")
        if field == "sha256" and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Invalid original checksum.")
        if field in {"size", "bytes", "position"} and name != "series_membership" and value < 0:
            raise ValueError("Negative size or position.")
        if field == "revision" and value < 1:
            raise ValueError("Invalid revision.")
        if field.endswith("_json"):
            parsed = json.loads(value)
            if not isinstance(parsed, (dict, list)):
                raise ValueError("Invalid embedded catalog JSON.")
    enums = {
        ("edition", "medium"): {"ebook", "comic", "audio"},
        ("edition", "abridgement"): {"unknown", "abridged", "unabridged"},
        ("representation", "format"): {
            "epub",
            "pdf",
            "cbz",
            "cbr",
            "mp3",
            "m4a",
            "m4b",
            "audio-set",
        },
        ("personal_state", "default_shelf"): {"library", "archive"},
        ("cover_blob", "media_type"): {"image/jpeg", "image/png", "image/webp"},
        ("cover_blob", "origin"): {"manual"},
        ("trash_operation", "action"): {"trash", "restore"},
        ("intake_job", "kind"): {"scan", "accept"},
        ("intake_job", "state"): {
            "queued",
            "running",
            "completed",
            "error",
            "cancelled",
            "preview",
        },
        ("backup_record", "mode"): {"catalog", "full"},
        ("backup_record", "state"): {"queued", "running", "complete", "error"},
    }
    for (table_name, field), choices in enums.items():
        if name == table_name and row[field] not in choices:
            raise ValueError(f"Invalid {field} in {name}.")
    if name == "personal_state":
        PersonalValues.model_validate({**row, "tags": json.loads(row["tags_json"])})
    if name == "reading_record":
        RecordEdit.model_validate(row)
    if name == "work":
        origins = json.loads(row["metadata_origins_json"])
        if not isinstance(origins, dict) or set(origins) - {"title", "authors", "description"}:
            raise ValueError("Invalid selected metadata origins.")
        for origin in origins.values():
            FieldOrigin.model_validate(origin)
    if name == "progress" and not 0.5 <= row["speed"] <= 3:
        raise ValueError("Invalid playback speed.")
    if name == "scan_directory" and row["path"] and not safe_member(row["path"]):
        raise ValueError("Unsafe scan directory.")
    if name == "intake_job" and row["prefix"] and not safe_member(row["prefix"]):
        raise ValueError("Unsafe intake prefix.")
    if name in {"import_operation", "trash_operation"} and row["state"] != "complete":
        raise ValueError("Portable catalogs cannot replay unfinished file operations.")
    if name == "trash_file" and not row["done"]:
        raise ValueError("Portable catalogs cannot replay unfinished file moves.")
    # Operational queues are preserved as stopped history, never automatically resumed.
    if name == "intake_job" and row["state"] in {"queued", "running"}:
        row["state"] = "cancelled"
    if name == "backup_record" and row["state"] in {"queued", "running"}:
        row["state"] = "error"
        row["error"] = "Imported history; create a new backup in this installation."
    return row


def read_catalog(source, connection):
    reader = Reader(source)
    reader.expect("start_map")
    header = {}
    seen = set()
    while True:
        event, key = reader.next()
        if event == "end_map":
            break
        if (
            event != "map_key"
            or key in header
            or key not in {"format_version", "schema_version", "roots", "tables"}
        ):
            raise ValueError("Unknown or duplicate catalog envelope field.")
        if key != "tables":
            header[key] = reader.value()
            continue
        header[key] = True
        reader.expect("start_map")
        while True:
            event, name = reader.next()
            if event == "end_map":
                break
            if event != "map_key" or name not in TABLES or name in seen:
                raise ValueError("Unknown or duplicate catalog table.")
            seen.add(name)
            reader.expect("start_array")
            while True:
                event, value = reader.next()
                if event == "end_array":
                    break
                row = validate_row(name, reader.value((event, value)))
                connection.execute(TABLES[name].insert(), row)
    if header.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported portable catalog format version.")
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported portable catalog schema version.")
    roots = header.get("roots")
    if not isinstance(roots, dict) or roots.get("managed") != {"kind": "managed"}:
        raise ValueError("Invalid root declarations.")
    for alias, declaration in roots.items():
        if not ROOT.fullmatch(alias) or declaration != {
            "kind": "managed" if alias == "managed" else "external"
        }:
            raise ValueError("Invalid root declarations.")
    if next(reader.events, None) is not None or seen != set(TABLES):
        raise ValueError("The catalog has trailing data or missing tables.")
    return roots


def import_catalog(source, destination, *, allow_missing_originals=False):
    if not allow_missing_originals:
        raise ValueError("Catalog import omits original files; explicitly allow missing originals.")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Import destination must not exist.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".stacks-catalog-", dir=destination.parent))
    engine = None
    try:
        engine, _ = initialize(scratch / "catalog.sqlite3")
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            with connection.begin(), source.open("rb") as stream:
                roots = read_catalog(stream, connection)
                if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Catalog relationships are incomplete.")
                actual_roots = {"managed"}
                for table in ("asset", "inbox_candidate", "intake_job"):
                    actual_roots.update(
                        row[0]
                        for row in connection.exec_driver_sql(f"SELECT DISTINCT root FROM {table}")
                        if row[0]
                    )
                if set(roots) != actual_roots:
                    raise ValueError("Catalog root declarations do not match its references.")
                bad_progress = connection.exec_driver_sql(
                    "SELECT 1 FROM progress p JOIN asset a ON a.id=p.asset_id "
                    "WHERE a.representation_id!=p.representation_id LIMIT 1"
                ).fetchone()
                if bad_progress:
                    raise ValueError("Audio progress refers to a different recording.")
                redirects = connection.exec_driver_sql(
                    "WITH RECURSIVE settled(source_id) AS ("
                    "SELECT r.source_id FROM work_redirect r WHERE NOT EXISTS "
                    "(SELECT 1 FROM work_redirect t WHERE t.source_id=r.target_id) "
                    "UNION ALL SELECT r.source_id FROM work_redirect r "
                    "JOIN settled s ON r.target_id=s.source_id) "
                    "SELECT (SELECT count(*) FROM work_redirect)-(SELECT count(*) FROM settled)"
                ).scalar()
                if redirects:
                    raise ValueError("Catalog redirects contain a cycle.")
            if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                raise ValueError("Catalog integrity validation failed.")
        engine.dispose()
        engine = None
        (scratch / "managed").mkdir()
        marker = scratch / "MEDIA-RESTORE-REQUIRED.txt"
        marker.write_text(
            "Catalog import contains no media or chosen cover originals.\n"
            "Restore managed storage separately and configure external roots before use.\n"
        )
        for file in (scratch / "catalog.sqlite3", marker):
            with file.open("rb") as handle:
                os.fsync(handle.fileno())
        flush_directory(scratch / "managed")
        flush_directory(scratch)
        if destination.exists() or destination.is_symlink():
            raise ValueError("Import destination appeared while importing.")
        os.rename(scratch, destination)
        flush_directory(destination.parent)
    except (
        ijson.JSONError,
        sqlite3.Error,
        SQLAlchemyError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ) as exc:
        raise ValueError("The portable catalog is invalid or incomplete.") from exc
    finally:
        if engine is not None:
            engine.dispose()
        if scratch.exists():
            shutil.rmtree(scratch)
