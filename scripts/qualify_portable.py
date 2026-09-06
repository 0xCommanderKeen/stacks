#!/usr/bin/env python3
"""Offline portable round trip for disposable scale fixtures, with per-phase RSS."""

import argparse
import hashlib
import json
import resource
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from stacks.library import Library
from stacks.portable import TABLES, import_catalog, write_catalog


def fingerprints(path):
    result = {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        for name, table in TABLES.items():
            keys = ",".join(column.name for column in table.primary_key.columns)
            digest = hashlib.sha256()
            count = 0
            for row in connection.execute(f"SELECT * FROM {name} ORDER BY {keys}"):
                digest.update(json.dumps(row, ensure_ascii=False).encode())
                digest.update(b"\n")
                count += 1
            result[name] = {"rows": count, "sha256": digest.hexdigest()}
        result["integrity"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        result["foreign_key_errors"] = sum(
            1 for _ in connection.execute("PRAGMA foreign_key_check")
        )
        result["authority_rows"] = sum(
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("login_session", "device_credential")
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=("export", "import"))
    args = parser.parse_args()
    catalog = args.output_dir / "catalog.json"
    restored = args.output_dir / "restored"
    started = time.monotonic()
    if args.phase:
        if args.phase == "export":
            library = Library(args.data_dir)
            try:
                write_catalog(library, catalog)
            finally:
                library.close()
        else:
            import_catalog(catalog, restored, allow_missing_originals=True)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(
            json.dumps(
                {
                    "seconds": round(time.monotonic() - started, 3),
                    "peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
                }
            )
        )
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {}
    for phase in ("export", "import"):
        process = subprocess.run(
            [
                sys.executable,
                __file__,
                "--data-dir",
                str(args.data_dir),
                "--output-dir",
                str(args.output_dir),
                "--phase",
                phase,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        report[phase] = json.loads(process.stdout)
    source = fingerprints(args.data_dir / "catalog.sqlite3")
    destination = fingerprints(restored / "catalog.sqlite3")
    report.update(
        {
            "catalog_bytes": catalog.stat().st_size,
            "tables": destination,
            "mismatched_tables": [name for name in TABLES if source[name] != destination[name]],
            "limitations": "Offline round trip of a settled disposable synthetic catalog; "
            "Original media is omitted. Peak RSS uses a fresh process per phase. "
            "Fingerprints compare all catalog columns ordered by stable primary keys.",
        }
    )
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if (
        report["mismatched_tables"]
        or destination["integrity"] != "ok"
        or destination["foreign_key_errors"]
        or destination["authority_rows"]
    ):
        raise SystemExit("Portable round trip verification failed; inspect aggregate report.")


if __name__ == "__main__":
    main()
