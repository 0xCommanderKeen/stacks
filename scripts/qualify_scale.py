"""Disposable synthetic scale fixtures and real HTTP measurements; no private library data."""

import argparse
import hashlib
import http.cookiejar
import io
import json
import statistics
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PIL import Image
from sqlalchemy import insert
from stacks.library import Library
from stacks.models import (
    Asset,
    Collection,
    CollectionEntry,
    Contributor,
    Credit,
    Edition,
    PersonalState,
    Representation,
    Series,
    SeriesMembership,
    Work,
)
from stacks.samples import epub_bytes


def identity(kind, number):
    return str(uuid5(NAMESPACE_URL, f"stacks-scale-v1/{kind}/{number}"))


def seed(data, fixtures, count, audio):
    if data.exists() or fixtures.exists():
        raise ValueError("Scale fixtures require fresh data and fixture directories.")
    fixtures.mkdir(parents=True)
    (fixtures / "catalog").mkdir()
    (fixtures / "intake").mkdir()
    library = Library(data)
    started = time.monotonic()
    try:
        image = io.BytesIO()
        Image.new("RGB", (300, 450), "#78865a").save(image, "JPEG")
        covers = library.managed / ".benchmark"
        covers.mkdir()
        (covers / "cover.jpg").write_bytes(image.getvalue())
        timestamp = "2026-01-01T00:00:00+00:00"
        with library.engine.begin() as connection:
            connection.execute(
                insert(Contributor),
                [{"id": identity("author", i), "name": f"Author {i:04} Vale"} for i in range(1000)],
            )
            connection.execute(
                insert(Series),
                [
                    {
                        "id": identity("series", i),
                        "name": f"Orbit {i % 100:03}",
                        "run": str(1980 + i // 100),
                        "following": i % 10 == 0,
                        "revision": 1,
                    }
                    for i in range((count + 24) // 25)
                ],
            )
            connection.execute(
                insert(Collection),
                [
                    {
                        "id": identity("collection", i),
                        "name": f"Reading shelf {i:03}",
                        "home": i % 10 == 0,
                        "revision": 1,
                        "state_id": identity("state", i),
                    }
                    for i in range((count + 999) // 1000)
                ],
            )
            for start in range(0, count, 1000):
                rows = {
                    model: []
                    for model in (
                        Work,
                        Edition,
                        Representation,
                        Asset,
                        Credit,
                        PersonalState,
                        SeriesMembership,
                        CollectionEntry,
                    )
                }
                for i in range(start, min(count, start + 1000)):
                    medium = "comic" if i % 100 < 80 else "ebook" if i % 100 < 98 else "audio"
                    fmt = {"comic": "cbz", "ebook": "epub", "audio": "m4b"}[medium]
                    title = f"{'Orbit' if medium == 'comic' else 'A Library Story'} {i:06}"
                    work, edition, rep = (
                        identity("work", i),
                        identity("edition", i),
                        identity("representation", i),
                    )
                    rows[Work].append(
                        {
                            "id": work,
                            "title": title,
                            "description": "Synthetic scale qualification publication.",
                            "created_at": timestamp,
                            "updated_at": timestamp,
                            "revision": 1,
                            "metadata_origins_json": "{}",
                        }
                    )
                    rows[Edition].append(
                        {
                            "id": edition,
                            "work_id": work,
                            "medium": medium,
                            "language": "en",
                            "publisher": "Stacks Samples",
                            "identifier": "",
                            "narrator": "",
                            "abridgement": "unknown",
                        }
                    )
                    rows[Representation].append(
                        {
                            "id": rep,
                            "edition_id": edition,
                            "format": fmt,
                            "cover_path": ".benchmark/cover.jpg" if i % 4 else None,
                            "extracted_json": json.dumps(
                                {"medium": medium, "format": fmt, "duration_seconds": 20}
                                if medium == "audio"
                                else {"medium": medium, "format": fmt}
                            ),
                        }
                    )
                    rows[Asset].append(
                        {
                            "id": identity("asset", i),
                            "representation_id": rep,
                            "position": 0,
                            "root": "benchmark",
                            "relative_path": f"{i:06}.{fmt}",
                            "original_name": f"{title}.{fmt}",
                            "sha256": hashlib.sha256(str(i).encode()).hexdigest(),
                            "size": 12345,
                        }
                    )
                    rows[Credit].append(
                        {
                            "id": identity("credit", i),
                            "work_id": work,
                            "contributor_id": identity("author", i % 1000),
                            "role": "author",
                            "position": 0,
                        }
                    )
                    rows[PersonalState].append(
                        {
                            "work_id": work,
                            "default_shelf": "archive" if i % 10 == 0 else "library",
                            "notes": "A synthetic personal note" if i % 20 == 0 else "",
                            "rating": 4 if i % 20 == 0 else None,
                            "tags_json": '["sample"]' if i % 20 == 0 else "[]",
                        }
                    )
                    if i % 10 == 0:
                        rows[CollectionEntry].append(
                            {
                                "id": identity("entry", i),
                                "collection_id": identity("collection", i // 1000),
                                "work_id": work,
                                "position": (i % 1000) // 10,
                            }
                        )
                    if medium == "comic":
                        rows[SeriesMembership].append(
                            {
                                "id": identity("membership", i),
                                "work_id": work,
                                "series_id": identity("series", i // 25),
                                "designation": str(i % 25 + 1),
                                "position": float(i % 25 + 1),
                            }
                        )
                for model, batch in rows.items():
                    if batch:
                        connection.execute(insert(model), batch)
        recording = library.import_file(audio, "Qualification listening.m4b")
        rep = recording.work.editions[0].representations[0]
        for i in range(500):
            (fixtures / "intake" / f"intake-{i:04}.epub").write_bytes(
                epub_bytes(f"Intake sample {i:04}", cover=False)
            )
        with library.engine.connect() as connection:
            connection.exec_driver_sql("ANALYZE")
        return {
            "synthetic_works": count,
            "actual_audio_works": 1,
            "distribution": {
                "comic_percent": 80,
                "ebook_percent": 18,
                "audio_percent": 2,
                "archive_percent": 10,
                "embedded_cover_percent": 75,
            },
            "series": (count + 24) // 25,
            "contributors": 1000,
            "intake_files": 500,
            "audio_representation_id": rep.id,
            "audio_asset_id": rep.assets[0].id,
            "seed_seconds": round(time.monotonic() - started, 3),
            "limitations": "Catalog-scale rows reference intentionally absent synthetic originals; "
            "a verified audiobook and generated EPUB intake fixtures exercise media I/O.",
        }
    finally:
        library.close()


def summary(values):
    ordered = sorted(values)
    return (
        {
            "samples": len(values),
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
            "max_ms": round(max(values), 3),
        }
        if values
        else {"samples": 0}
    )


def measure(url, password, fixture, rounds):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def request(path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url.rstrip("/") + path,
            data=data,
            headers={
                "X-Stacks-Request": "1",
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        start = time.monotonic()
        with opener.open(req, timeout=30) as response:
            content = response.read()
            return (time.monotonic() - start) * 1000, content, response.status

    request("/api/login", {"password": password})
    queries = {
        "catalog": "/api/catalog?limit=24",
        "search_common": "/api/catalog?q=Author&limit=24",
        "search_title": "/api/catalog?q=Orbit%2001&limit=24",
        "search_missing": "/api/catalog?q=absent-needle&limit=24",
        "archive": "/api/catalog?scope=archive&limit=24",
        "series": "/api/browse/series?limit=24",
        "collections": "/api/collections?limit=24",
        "collection_works": f"/api/collections/{identity('collection', 0)}/works?limit=24",
    }
    cold = {}
    for name, path in queries.items():
        elapsed, _, status = request(path)
        cold[name] = {"first_request_ms": round(elapsed, 3), "status": status}
    _, content, _ = request("/api/intake/scans", {"root": "intake", "prefix": ""})
    job_id = json.loads(content)["id"]
    stop = threading.Event()
    ranges, errors = [], []

    def audio_requests():
        while not stop.is_set():
            try:
                elapsed, content, status = request(
                    f"/api/assets/{fixture['audio_asset_id']}/stream",
                    headers={"Range": "bytes=0-65535"},
                )
                if status != 206 or not content:
                    raise ValueError("Invalid audio Range response")
                ranges.append(elapsed)
            except Exception as exc:
                errors.append(type(exc).__name__)
            stop.wait(0.25)

    thread = threading.Thread(target=audio_requests, daemon=True)
    thread.start()
    timings = {name: [] for name in queries}
    try:
        for _ in range(rounds):
            for name, path in queries.items():
                elapsed, _, status = request(path)
                if status != 200:
                    raise ValueError("Catalog HTTP failure")
                timings[name].append(elapsed)
    finally:
        stop.set()
        thread.join()
    _, jobs, _ = request("/api/intake/jobs?limit=10")
    job = next(item for item in json.loads(jobs)["items"] if item["id"] == job_id)
    return {
        "cold_first_requests": cold,
        "warm": {name: summary(values) for name, values in timings.items()},
        "concurrent_audio_ranges": summary(ranges),
        "audio_errors": errors,
        "intake_after_measurement": {
            key: job.get(key) for key in ("state", "discovered", "completed", "remaining", "failed")
        },
        "limitations": "First HTTP requests after process startup are not a flushed "
        "NAS filesystem cache. "
        "Range polling is service continuity evidence, not physical-device acceptance.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("seed")
    command.add_argument("--data-dir", type=Path, required=True)
    command.add_argument("--fixtures", type=Path, required=True)
    command.add_argument("--count", type=int, choices=(100, 50000, 100000), required=True)
    command.add_argument("--audio", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("measure")
    command.add_argument("--url", required=True)
    command.add_argument("--password-file", type=Path, required=True)
    command.add_argument("--fixture-report", type=Path, required=True)
    command.add_argument("--rounds", type=int, default=30)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Report output must not exist.")
    if args.command == "seed":
        report = seed(args.data_dir, args.fixtures, args.count, args.audio)
    else:
        if not 1 <= args.rounds <= 1000:
            parser.error("Rounds must be between 1 and 1000.")
        report = measure(
            args.url,
            args.password_file.read_text().strip(),
            json.loads(args.fixture_report.read_text()),
            args.rounds,
        )
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
