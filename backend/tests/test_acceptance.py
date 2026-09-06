import json

import pytest
from sqlalchemy import select
from stacks.library import Library, digest
from stacks.models import ImportOperation, Representation, Series
from stacks.samples import epub_bytes
from stacks.schemas import AcceptedMetadata, SeriesEdit


@pytest.fixture
def source_library(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    library = Library(tmp_path / "data", {"books": source})
    yield library, source
    library.close()


@pytest.mark.parametrize("mode", ["register", "copy"])
def test_accept_metadata_and_series_atomically_without_changing_raw_facts(source_library, mode):
    library, source = source_library
    publication = source / "book.epub"
    original = epub_bytes("Embedded title")
    publication.write_bytes(original)
    before = publication.stat()
    series = library.save_series(SeriesEdit(name="Chosen run", run="2026"))
    with library.sessions.begin() as session:
        session.get(Series, series.id).following = True
    result = library.accept_sources(
        "books",
        ["book.epub"],
        {"book.epub": digest(publication)},
        AcceptedMetadata(
            title="Accepted title",
            authors=["Owner choice"],
            series_id=series.id,
            designation="Annual",
            position=1.5,
        ),
        mode,
    )
    work = result.work
    assert work.title == "Accepted title" and work.authors == ["Owner choice"]
    assert work.memberships[0].designation == "Annual" and work.memberships[0].position == 1.5
    assert work.personal.shelf == "library"
    asset = work.editions[0].representations[0].assets[0]
    assert asset.root == ("books" if mode == "register" else "managed")
    with library.sessions() as session:
        representation = session.get(Representation, work.editions[0].representations[0].id)
        facts = json.loads(representation.extracted_json)
        assert facts["title"] == "Embedded title"
        assert facts["accepted_metadata"]["title"] == "Accepted title"
        from stacks.models import Asset

        assert library.resolve_asset(session.get(Asset, asset.id)).read_bytes() == original
    assert publication.read_bytes() == original
    assert publication.stat().st_mtime_ns == before.st_mtime_ns
    duplicate = library.accept_sources(
        "books",
        ["book.epub"],
        {"book.epub": digest(publication)},
        AcceptedMetadata(title="Never overwrite"),
        mode,
    )
    assert duplicate.duplicate and duplicate.work.id == work.id
    assert duplicate.work.title == "Accepted title"


def test_accept_refuses_changed_preview_and_keeps_explicit_archive(source_library):
    library, source = source_library
    publication = source / "book.epub"
    publication.write_bytes(epub_bytes("Before"))
    expected = digest(publication)
    publication.write_bytes(epub_bytes("Changed"))
    with pytest.raises(ValueError, match="changed since preview"):
        library.accept_sources("books", ["book.epub"], {"book.epub": expected}, AcceptedMetadata())
    assert library.list().total == 0
    series = library.save_series(SeriesEdit(name="Followed", run=""))
    with library.sessions.begin() as session:
        session.get(Series, series.id).following = True
    result = library.accept_sources(
        "books",
        ["book.epub"],
        {"book.epub": digest(publication)},
        AcceptedMetadata(shelf="archive", series_id=series.id),
    )
    assert result.work.personal.shelf == "archive"


def test_cancel_before_journal_leaves_no_work_or_stage(source_library):
    from stacks.intake import Interrupted

    library, source = source_library
    publication = source / "book.epub"
    publication.write_bytes(epub_bytes("Cancelled"))

    def cancel():
        raise Interrupted()

    with pytest.raises(Interrupted):
        library.accept_sources(
            "books",
            ["book.epub"],
            {"book.epub": digest(publication)},
            AcceptedMetadata(),
            "copy",
            cancel,
        )
    assert library.list().total == 0
    assert not list(library.staging.iterdir())


def test_recovery_retains_accepted_metadata_after_interrupted_publication(
    source_library, monkeypatch
):
    library, source = source_library
    publication = source / "book.epub"
    publication.write_bytes(epub_bytes("Raw"))
    publish = library._publish

    def fail(operation):
        raise OSError("Interrupted at publication")

    monkeypatch.setattr(library, "_publish", fail)
    with pytest.raises(OSError):
        library.accept_sources(
            "books",
            ["book.epub"],
            {"book.epub": digest(publication)},
            AcceptedMetadata(title="Keep this choice"),
            "copy",
        )
    assert library.list().total == 0
    with library.sessions() as session:
        assert session.scalar(select(ImportOperation)).state == "staged"
    monkeypatch.setattr(library, "_publish", publish)
    library.recover()
    assert library.list(scope="all").items[0].title == "Keep this choice"


def discover(library, source, count=3):
    from stacks.intake import Intake
    from stacks.schemas import ScanRequest

    from .test_inbox import finish

    for index in range(count):
        (source / f"book-{index}.epub").write_bytes(epub_bytes(f"Raw {index}"))
    worker = Intake(library, stable_seconds=0)
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    return worker


@pytest.mark.parametrize("mode", ["register", "copy"])
def test_all_matching_preview_confirm_and_duplicate_retry(source_library, mode, monkeypatch):
    from stacks.schemas import AcceptanceRequest, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source)
    job = worker.preview_acceptance(
        AcceptanceRequest(
            root="books", mode=mode, metadata=AcceptedMetadata(authors=["Batch choice"])
        )
    )
    assert job.state == "preview" and job.discovered == 3
    assert worker.step() is False and library.list(scope="all").total == 0
    page = worker.acceptance(job.id, limit=1, offset=1)
    assert page.total == 3 and len(page.items) == 1
    assert page.items[0].metadata.authors == ["Batch choice"]
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    finish(worker)
    result = worker.acceptance(job.id)
    assert result.job.state == "completed" and result.job.completed == 3
    assert library.list(scope="archive").total == 3
    assert all(item.authors == ["Batch choice"] for item in library.list(scope="all").items)
    worker.change(job.id, JobChange(action="retry", revision=result.job.revision))
    finish(worker)
    assert library.list(scope="all").total == 3
    assert worker.acceptance(job.id).job.completed == 3
    worker.close()


def test_candidate_edit_invalidates_preview_and_active_acceptance_guards_edits(source_library):
    from stacks.schemas import AcceptanceRequest, CandidateEdit, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source, count=1)
    candidate = worker.candidates().items[0]
    job = worker.preview_acceptance(AcceptanceRequest(candidate_ids=[candidate.id]))
    edited = worker.edit_candidate(
        candidate.id,
        CandidateEdit(
            revision=candidate.revision, metadata=AcceptedMetadata(title="Individual choice")
        ),
    )
    assert edited.facts["title"] == "Raw 0" and edited.edits["title"] == "Individual choice"
    with pytest.raises(ValueError, match="changed"):
        worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    replacement = worker.preview_acceptance(AcceptanceRequest(candidate_ids=[candidate.id]))
    worker.change(replacement.id, JobChange(action="confirm", revision=replacement.revision))
    with pytest.raises(ValueError, match="being accepted"):
        worker.edit_candidate(
            candidate.id,
            CandidateEdit(revision=edited.revision, metadata=AcceptedMetadata(title="Too late")),
        )
    finish(worker)
    assert library.list(scope="all").items[0].title == "Individual choice"
    worker.close()


def test_acceptance_cancel_and_restart_keep_completed_items(source_library):
    from stacks.intake import Intake
    from stacks.schemas import AcceptanceRequest, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source)
    job = worker.preview_acceptance(AcceptanceRequest(root="books"))
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    worker.step()
    assert library.list(scope="all").total == 1
    progress = worker.acceptance(job.id).job
    worker.change(job.id, JobChange(action="cancel", revision=progress.revision))
    assert worker.step() is False
    worker.close()
    restarted = Intake(library, stable_seconds=0)
    progress = restarted.acceptance(job.id).job
    restarted.change(job.id, JobChange(action="retry", revision=progress.revision))
    finish(restarted)
    assert library.list(scope="all").total == 3
    assert restarted.acceptance(job.id).job.completed == 3
    restarted.close()


def test_crash_after_publication_before_receipt_is_idempotent(source_library, monkeypatch):
    from stacks.schemas import AcceptanceRequest, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source, count=1)
    job = worker.preview_acceptance(
        AcceptanceRequest(root="books", metadata=AcceptedMetadata(title="Durable choice"))
    )
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    accept = library.accept_sources

    def fail_receipt(*args, **kwargs):
        accept(*args, **kwargs)
        raise OSError("Receipt write interrupted")

    monkeypatch.setattr(library, "accept_sources", fail_receipt)
    finish(worker)
    assert library.list(scope="all").items[0].title == "Durable choice"
    failed = worker.acceptance(job.id)
    assert failed.job.failed == 1
    monkeypatch.setattr(library, "accept_sources", accept)
    worker.change(job.id, JobChange(action="retry", revision=failed.job.revision))
    finish(worker)
    result = worker.acceptance(job.id)
    assert result.job.skipped == 1 and result.job.failed == 0
    assert result.items[0].work_id == library.list(scope="all").items[0].id
    assert library.list(scope="all").total == 1
    worker.close()


def test_audio_acceptance_requires_explicit_group_and_natural_order(source_library):
    from pathlib import Path

    from stacks.intake import Intake
    from stacks.schemas import AcceptanceRequest, JobChange, ScanRequest

    from .test_inbox import finish

    library, source = source_library
    for folder, fixture in (("Disc 10", "tone.mp3"), ("Disc 2", "listening.m4b")):
        directory = source / folder
        directory.mkdir()
        (directory / fixture).write_bytes(
            (Path(__file__).parent / "fixtures" / fixture).read_bytes()
        )
    worker = Intake(library, stable_seconds=0)
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    candidates = worker.candidates().items
    assert all(candidate.state == "review" for candidate in candidates)
    ids = [candidate.id for candidate in candidates]
    with pytest.raises(ValueError, match="audio grouping"):
        worker.preview_acceptance(AcceptanceRequest(candidate_ids=ids))
    job = worker.preview_acceptance(
        AcceptanceRequest(
            candidate_ids=ids,
            group_audio=True,
            metadata=AcceptedMetadata(title="Reviewed recording"),
        )
    )
    preview = worker.acceptance(job.id)
    assert preview.items[0].candidate.relative_path.startswith("Disc 2/")
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    finish(worker)
    work = library.list(scope="all").items[0]
    assert work.title == "Reviewed recording"
    representation = work.editions[0].representations[0]
    assert representation.format == "audio-set" and len(representation.assets) == 2
    assert representation.assets[0].original_name.startswith("Disc 2/")
    assert worker.acceptance(job.id).job.completed == 2
    # Confirming one already-owned track never creates a second work.
    track = source / representation.assets[0].original_name
    duplicate = library.accept_sources(
        "books",
        [representation.assets[0].original_name],
        {representation.assets[0].original_name: digest(track)},
        AcceptedMetadata(),
    )
    assert duplicate.duplicate and duplicate.work.id == work.id
    worker.close()


def test_changed_source_after_preview_is_a_visible_failure(source_library):
    from stacks.schemas import AcceptanceRequest, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source, count=1)
    job = worker.preview_acceptance(AcceptanceRequest(root="books", mode="copy"))
    (source / "book-0.epub").write_bytes(epub_bytes("Changed after preview"))
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    finish(worker)
    result = worker.acceptance(job.id)
    assert result.job.failed == 1 and "changed since preview" in result.items[0].error
    assert library.list(scope="all").total == 0
    worker.close()


def test_acceptance_runs_between_scan_steps_and_preserves_individual_series_order(source_library):
    from stacks.intake import Intake
    from stacks.schemas import AcceptanceRequest, CandidateEdit, JobChange, ScanRequest

    from .test_inbox import finish

    library, source = source_library
    for index in range(40):
        (source / f"{index}.epub").write_bytes(epub_bytes(str(index)))
    worker = Intake(library, stable_seconds=0)
    scan = worker.scan(ScanRequest(root="books"))
    worker.step()
    candidate = worker.candidates(state="ready").items[0]
    run = library.save_series(SeriesEdit(name="Deliberate run", run="2026"))
    worker.edit_candidate(
        candidate.id,
        CandidateEdit(
            revision=candidate.revision,
            metadata=AcceptedMetadata(designation="1/2", shelf="archive"),
        ),
    )
    job = worker.preview_acceptance(
        AcceptanceRequest(candidate_ids=[candidate.id], metadata=AcceptedMetadata(series_id=run.id))
    )
    preview = worker.acceptance(job.id)
    assert preview.items[0].series.name == run.name
    assert preview.items[0].metadata.position == 0.5
    assert preview.items[0].metadata.shelf == "archive"
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    worker.step()
    assert library.list(scope="all").total == 1
    assert next(job for job in worker.jobs().items if job.id == scan.id).completed == 1
    finish(worker)
    work = library.list(scope="all").items[0]
    assert work.memberships[0].position == 0.5 and work.personal.shelf == "archive"
    worker.close()


def test_queued_acceptance_restores_with_relocated_sources(source_library, tmp_path):
    import shutil

    from stacks.backup import backup, restore
    from stacks.intake import Intake
    from stacks.schemas import AcceptanceRequest, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source, count=1)
    job = worker.preview_acceptance(
        AcceptanceRequest(
            root="books", mode="copy", metadata=AcceptedMetadata(title="Restored acceptance")
        )
    )
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    archive = tmp_path / "queued.zip"
    backup(library, archive)
    relocated = tmp_path / "new-source"
    shutil.copytree(source, relocated)
    target = tmp_path / "new-data"
    restore(archive, target)
    restored = Library(target, {"books": relocated})
    resumed = Intake(restored, stable_seconds=0)
    try:
        finish(resumed)
        assert resumed.acceptance(job.id).job.completed == 1
        assert restored.list(scope="all").items[0].title == "Restored acceptance"
        assert restored.export()["schema_version"] == 12
    finally:
        resumed.close()
        restored.close()
        worker.close()


def test_acceptance_api_preview_revision_guards_and_auth(client, tmp_path):
    import time

    source = tmp_path / "source"
    source.mkdir()
    (source / "api.epub").write_bytes(epub_bytes("API acceptance"))
    client.app.state.library.sources["books"] = source
    client.app.state.intake.stable_seconds = 0
    assert client.post("/api/intake/scans", json={"root": "books"}).status_code == 200
    for _ in range(100):
        page = client.get("/api/intake/candidates?state=ready").json()
        if page["items"]:
            break
        time.sleep(0.02)
    candidate = page["items"][0]
    edited = client.patch(
        f"/api/intake/candidates/{candidate['id']}",
        json={"revision": candidate["revision"], "metadata": {"title": "API choice"}},
    )
    assert edited.status_code == 200, edited.text
    preview = client.post("/api/intake/preview", json={"candidate_ids": [candidate["id"]]})
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert client.get("/api/catalog?scope=all").json()["total"] == 0
    assert (
        client.get(f"/api/intake/acceptance/{job['id']}").json()["items"][0]["metadata"]["title"]
        == "API choice"
    )
    assert (
        client.post(
            f"/api/intake/jobs/{job['id']}", json={"action": "confirm", "revision": job["revision"]}
        ).status_code
        == 200
    )
    for _ in range(100):
        result = client.get(f"/api/intake/acceptance/{job['id']}").json()
        if result["job"]["state"] == "completed":
            break
        time.sleep(0.02)
    assert result["job"]["completed"] == 1
    client.cookies.clear()
    assert client.post("/api/intake/preview", json={}).status_code == 401
    assert client.get(f"/api/intake/acceptance/{job['id']}").status_code == 401
    assert (
        client.patch(
            f"/api/intake/candidates/{candidate['id']}", json={"revision": 1, "metadata": {}}
        ).status_code
        == 401
    )


def test_worker_survives_temporary_database_failure_before_claim(source_library, monkeypatch):
    from threading import Event

    from stacks.schemas import AcceptanceRequest, JobChange

    library, source = source_library
    worker = discover(library, source, count=1)
    job = worker.preview_acceptance(AcceptanceRequest(root="books"))
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    step = worker.step
    failed, finished = Event(), Event()

    def unavailable_once():
        if not failed.is_set():
            failed.set()
            raise OSError("Database unavailable before claim")
        result = step()
        if worker.acceptance(job.id).job.state == "completed":
            finished.set()
        return result

    monkeypatch.setattr(worker, "step", unavailable_once)
    worker.start()
    try:
        assert failed.wait(2)
        worker.wake.set()
        assert finished.wait(3)
        assert library.list(scope="all").total == 1
    finally:
        worker.close()


def test_receipt_keeps_preview_snapshot_after_source_replacement(source_library):
    from stacks.schemas import AcceptanceRequest, JobChange, ScanRequest

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source, count=1)
    job = worker.preview_acceptance(AcceptanceRequest(root="books", mode="copy"))
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    finish(worker)
    receipt = worker.acceptance(job.id).items[0]
    assert receipt.metadata.title == "Raw 0"
    original_work = receipt.work_id
    (source / "book-0.epub").write_bytes(epub_bytes("Replacement bytes"))
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    current = worker.candidates().items[0]
    assert current.state == "review" and current.sha256 != receipt.candidate.sha256
    with pytest.raises(ValueError, match="eligible"):
        worker.preview_acceptance(AcceptanceRequest(root="books", state=""))
    receipt = worker.acceptance(job.id).items[0]
    assert receipt.metadata.title == "Raw 0"
    assert receipt.work_id == original_work
    assert receipt.candidate.facts["title"] == "Raw 0"
    assert library.get(original_work).title == "Raw 0"
    worker.close()


def test_pending_journal_cannot_silently_replace_preview_choices(source_library, monkeypatch):
    library, source = source_library
    publication = source / "book.epub"
    publication.write_bytes(epub_bytes("Raw"))
    hashes = {"book.epub": digest(publication)}
    publish = library._publish

    def fail(operation):
        raise OSError("Interrupted publication")

    monkeypatch.setattr(library, "_publish", fail)
    with pytest.raises(OSError):
        library.accept_sources(
            "books", ["book.epub"], hashes, AcceptedMetadata(title="First choice")
        )
    monkeypatch.setattr(library, "_publish", publish)
    with pytest.raises(ValueError, match="different pending choices"):
        library.accept_sources("books", ["book.epub"], hashes, AcceptedMetadata(title="New choice"))
    with pytest.raises(ValueError, match="different pending choices"):
        library.accept_sources(
            "books", ["book.epub"], hashes, AcceptedMetadata(title="First choice"), "copy"
        )
    # Touching identical source bytes does not make a verified retry irrecoverable.
    import os

    stat = publication.stat()
    os.utime(publication, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
    result = library.accept_sources(
        "books", ["book.epub"], hashes, AcceptedMetadata(title="First choice")
    )
    assert result.work.title == "First choice"
    assert library.list(scope="all").total == 1


def test_acceptance_positions_use_catalog_bounds_before_publication(source_library):
    from pydantic import ValidationError
    from stacks.models import InboxCandidate
    from stacks.schemas import AcceptanceRequest, JobChange

    from .test_inbox import finish

    library, source = source_library
    worker = discover(library, source, count=1)
    series = library.save_series(SeriesEdit(name="Bounded run"))
    candidate = worker.candidates().items[0]
    with pytest.raises(ValidationError):
        worker.preview_acceptance(
            AcceptanceRequest(
                candidate_ids=[candidate.id],
                metadata=AcceptedMetadata(series_id=series.id, position=1e12),
            )
        )
    assert library.list(scope="all").total == 0
    with library.sessions.begin() as session:
        row = session.get(InboxCandidate, candidate.id)
        facts = json.loads(row.facts_json)
        facts["series_hint"] = {"designation": "999999999999"}
        row.facts_json = json.dumps(facts)
    job = worker.preview_acceptance(
        AcceptanceRequest(
            candidate_ids=[candidate.id],
            metadata=AcceptedMetadata(series_id=series.id),
        )
    )
    chosen = worker.acceptance(job.id).items[0].metadata
    assert chosen.designation == "999999999999" and chosen.position == 0
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    finish(worker)
    assert library.list(scope="all").items[0].memberships[0].position == 0
    worker.close()


def test_grouped_receipt_uses_accepted_representation_when_tracks_have_other_owners(source_library):
    from pathlib import Path

    from stacks.intake import Intake
    from stacks.models import Asset, Edition
    from stacks.schemas import AcceptanceRequest, JobChange, ScanRequest

    from .test_inbox import finish

    library, source = source_library
    fixtures = Path(__file__).parent / "fixtures"
    tracks = []
    for index, name in enumerate(("tone.mp3", "listening.m4b")):
        path = source / f"{index}-{name}"
        path.write_bytes((fixtures / name).read_bytes())
        tracks.append((path, path.name))
    standalone = library.import_file(*tracks[0])
    recording = library.import_files(tracks)
    # Make the ambiguous checksum fallback deterministically choose the wrong owner.
    with library.sessions.begin() as session:
        asset = session.scalar(
            select(Asset).where(Asset.representation_id == standalone.representation_id)
        )
        asset.id = "00000000-0000-0000-0000-000000000000"
    worker = Intake(library, stable_seconds=0)
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    job = worker.preview_acceptance(
        AcceptanceRequest(
            candidate_ids=[candidate.id for candidate in worker.candidates().items],
            group_audio=True,
        )
    )
    worker.change(job.id, JobChange(action="confirm", revision=job.revision))
    finish(worker)
    assert worker.acceptance(job.id).job.skipped == 2
    assert {item.work_id for item in worker.acceptance(job.id).items} == {recording.work.id}
    # Ownership can change independently of the receipt; stable representation identity follows it.
    with library.sessions.begin() as session:
        rep = session.get(Representation, recording.representation_id)
        edition = session.get(Edition, rep.edition_id)
        edition.work_id = standalone.work.id
    assert {item.work_id for item in worker.acceptance(job.id).items} == {standalone.work.id}
    with library.sessions.begin() as session:
        session.get(Edition, edition.id).work_id = recording.work.id
    assert {item.work_id for item in worker.acceptance(job.id).items} == {recording.work.id}
    worker.close()
