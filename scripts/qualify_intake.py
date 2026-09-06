"""Measure real-source intake in a fresh disposable catalog; report aggregates only.

Run inside the deployment image with the source bind-mounted read-only. Prefixes
are a private JSON list (or an object containing `prefixes`). Source names, titles,
and machine paths are intentionally omitted from the shareable result.
"""

import argparse
import collections
import json
import statistics
import time
from pathlib import Path

from sqlalchemy import func, or_, select
from stacks.inspection import FORMATS
from stacks.intake import Intake
from stacks.library import Library
from stacks.models import Asset, InboxCandidate, IntakeItem, IntakeJob
from stacks.portable import SCHEMA_VERSION
from stacks.schemas import AcceptanceRequest, JobChange, ScanRequest


def snapshot(source, prefixes, maximum):
    observed = {}
    for prefix in prefixes:
        folder = (source / prefix).resolve()
        if not folder.is_relative_to(source) or not folder.is_dir():
            raise ValueError("A selected source prefix is unavailable or outside its root.")
        for path in folder.rglob("*"):
            if path.suffix.lower().lstrip(".") not in FORMATS or not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError("Qualification requires regular originals inside the source root.")
            stat = path.stat()
            observed[path.relative_to(source).as_posix()] = (
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_dev,
                stat.st_ino,
            )
            if len(observed) > maximum:
                raise ValueError("Selected source prefixes exceed the qualification file limit.")
    if not observed:
        raise ValueError("The selected source prefixes contain no supported files.")
    return observed


def summary(values):
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    return {
        "samples": len(values),
        "median_ms": round(statistics.median(values), 2),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
        "max_ms": round(max(values), 2),
    }


def wait_jobs(library, worker, data, source, restart, deadline, progress):
    started = time.monotonic()
    catalog_ms = []
    restarted = False
    next_report = 0
    try:
        while True:
            with library.sessions() as session:
                active = session.scalar(
                    select(func.count())
                    .select_from(IntakeJob)
                    .where(IntakeJob.state.in_(["queued", "running"]))
                )
                completed = session.scalar(
                    select(func.count())
                    .select_from(IntakeItem)
                    .where(IntakeItem.state.in_(["done", "accepted", "duplicate"]))
                )
            if not active:
                break
            elapsed = time.monotonic() - started
            if elapsed > deadline:
                worker.close()
                raise TimeoutError(
                    "Qualification exceeded its bounded runtime; catalog retained for recovery."
                )
            if restart and not restarted and completed >= restart:
                worker.close()
                library.close()
                library = Library(data, {"sample": source})
                worker = Intake(library)
                worker.start()
                restarted = True
            tick = time.perf_counter()
            library.list(q="a", limit=24, scope="all")
            catalog_ms.append((time.perf_counter() - tick) * 1000)
            if elapsed >= next_report:
                print(
                    json.dumps(
                        {
                            "phase": progress,
                            "elapsed_seconds": round(elapsed, 1),
                            "active_jobs": active,
                            "completed_items": completed,
                        }
                    ),
                    flush=True,
                )
                next_report = elapsed + 30
            time.sleep(0.2)
    except BaseException:
        worker.close()
        library.close()
        raise
    return (
        library,
        worker,
        {
            "seconds": round(time.monotonic() - started, 3),
            "restarted": restarted,
            "catalog_search": summary(catalog_ms),
        },
    )


def run(args):
    source = args.source.resolve()
    if not 1 <= args.max_files <= 2000 or args.timeout <= 0:
        raise ValueError("Use 1–2000 files and a positive per-phase timeout.")
    if args.data.resolve().is_relative_to(source) or args.report.resolve().is_relative_to(source):
        raise ValueError("Disposable catalog and report must be outside the source root.")
    if args.data.exists() or args.report.exists():
        raise ValueError("Use a nonexistent disposable data directory and report path.")
    payload = json.loads(args.prefixes.read_text())
    prefixes = payload["prefixes"] if isinstance(payload, dict) else payload
    if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
        raise ValueError("Prefixes must be a JSON list of relative directory names.")
    before = snapshot(source, prefixes, args.max_files)
    report = {
        "files": len(before),
        "bytes": sum(value[0] for value in before.values()),
        "formats": dict(collections.Counter(Path(name).suffix.lower() for name in before)),
        "image_revision": args.revision,
        "schema_version": None,
        "phases": {},
    }
    library = Library(args.data, {"sample": source})
    worker = Intake(library)
    try:
        for prefix in prefixes:
            worker.scan(ScanRequest(root="sample", prefix=prefix))
        worker.start()
        library, worker, report["phases"]["discovery"] = wait_jobs(
            library, worker, args.data, source, max(1, len(before) // 2), args.timeout, "discovery"
        )
        with library.sessions() as session:
            report["candidate_states"] = dict(
                session.execute(
                    select(InboxCandidate.state, func.count()).group_by(InboxCandidate.state)
                ).all()
            )
        # This disposable measurement explicitly treats audio files as individual recordings.
        # Actual library adoption must choose recording boundaries in its own preview.
        with library.sessions() as session:
            eligible = list(
                session.scalars(
                    select(InboxCandidate.id).where(
                        InboxCandidate.state.in_(["ready", "review", "duplicate"]),
                        InboxCandidate.sha256.is_not(None),
                    )
                )
            )
        report["eligible_files"] = len(eligible)
        preview = worker.preview_acceptance(
            AcceptanceRequest(candidate_ids=eligible, audio_singles_confirmed=True, mode="register")
        )
        worker.change(preview.id, JobChange(action="confirm", revision=preview.revision))
        library, worker, report["phases"]["acceptance"] = wait_jobs(
            library,
            worker,
            args.data,
            source,
            len(before) + max(1, preview.discovered // 2),
            args.timeout,
            "acceptance",
        )
        accepted = worker.acceptance(preview.id).job
        report["acceptance"] = {
            "completed": accepted.completed,
            "duplicates": accepted.skipped,
            "failed": accepted.failed,
            "remaining": accepted.remaining,
        }
        count = library.list(scope="all", limit=1).total
        report["works"] = count
        for prefix in prefixes:
            worker.scan(ScanRequest(root="sample", prefix=prefix))
        library, worker, report["phases"]["rescan"] = wait_jobs(
            library, worker, args.data, source, 0, args.timeout, "rescan"
        )
        repeated = worker.preview_acceptance(
            AcceptanceRequest(
                root="sample", state="", audio_singles_confirmed=True, mode="register"
            )
        )
        worker.change(repeated.id, JobChange(action="confirm", revision=repeated.revision))
        library, worker, report["phases"]["reacceptance"] = wait_jobs(
            library, worker, args.data, source, 0, args.timeout, "reacceptance"
        )
        repeated = worker.acceptance(repeated.id).job
        report["repeat"] = {
            "duplicates": repeated.skipped,
            "failed": repeated.failed,
            "completed": repeated.completed,
            "remaining": repeated.remaining,
        }
        report["no_duplicate_growth"] = library.list(scope="all", limit=1).total == count
        report["source_observations_unchanged"] = (
            snapshot(source, prefixes, args.max_files) == before
        )
        with library.sessions() as session:
            report["managed_originals"] = session.scalar(
                select(func.count()).select_from(Asset).where(Asset.root == "managed")
            )
            report["registered_originals"] = session.scalar(select(func.count()).select_from(Asset))
            report["byte_identity_mismatches"] = session.scalar(
                select(func.count())
                .select_from(Asset)
                .outerjoin(
                    InboxCandidate,
                    (InboxCandidate.root == Asset.root)
                    & (InboxCandidate.relative_path == Asset.relative_path),
                )
                .where(or_(InboxCandidate.id.is_(None), InboxCandidate.sha256 != Asset.sha256))
            )
        report["schema_version"] = SCHEMA_VERSION
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
        if (
            not report["no_duplicate_growth"]
            or not report["source_observations_unchanged"]
            or report["byte_identity_mismatches"]
            or report["eligible_files"] != report["files"]
            or report["acceptance"]["failed"]
            or report["acceptance"]["remaining"]
            or report["repeat"]["failed"]
            or report["repeat"]["remaining"]
            or report["repeat"]["duplicates"] != report["eligible_files"]
            or report["managed_originals"]
            or report["registered_originals"] != report["files"]
        ):
            raise ValueError(
                "Qualification failed an intake, original-identity or duplicate-growth gate."
            )
    finally:
        worker.close()
        library.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prefixes", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=3600, help="Maximum seconds per phase")
    run(parser.parse_args())
