import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import func, select
from stacks.backup import backup, restore
from stacks.intake import Intake
from stacks.library import Library
from stacks.models import IntakeItem
from stacks.samples import epub_bytes
from stacks.schemas import JobChange, ScanRequest


@pytest.fixture
def inbox(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    library = Library(tmp_path / "data", {"books": source})
    worker = Intake(library, stable_seconds=0)
    yield worker, library, source
    worker.close()
    library.close()


def finish(worker):
    for _ in range(300):
        if not worker.step():
            return
    pytest.fail("Scan did not complete within bounded test steps")


def test_scan_restart_rescan_duplicate_evidence_and_paging(inbox):
    worker, library, source = inbox
    for index in range(40):
        (source / f"book-{index:02}.epub").write_bytes(epub_bytes(f"Inbox {index}"))
    original = source / "book-00.epub"
    existing = library.import_file(original, original.name).work
    job = worker.scan(ScanRequest(root="books"))
    worker.step()
    assert 0 < worker.candidates().total < 40
    worker.close()
    resumed = Intake(library, stable_seconds=0)
    finish(resumed)
    page = resumed.candidates(limit=7, offset=7)
    assert page.total == 40 and len(page.items) == 7
    assert resumed.jobs().items[0].completed == 40
    duplicate = resumed.candidates(state="duplicate").items[0]
    assert duplicate.work_id == existing.id
    assert duplicate.sha256 == existing.editions[0].representations[0].assets[0].sha256
    resumed.scan(ScanRequest(root="books"))
    finish(resumed)
    assert resumed.candidates().total == 40
    assert resumed.candidates(job_id=job.id).total == 40
    with library.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IntakeItem)) == 80
    assert library.list().total == 1
    resumed.close()


def test_recent_damaged_escape_alias_and_missing_files_are_explicit(inbox, tmp_path):
    worker, library, source = inbox
    valid = source / "valid.epub"
    valid.write_bytes(epub_bytes("Valid"))
    (source / "alias.epub").symlink_to(valid)
    (source / "loop").symlink_to(source, target_is_directory=True)
    outside = tmp_path / "outside.epub"
    outside.write_bytes(epub_bytes("Outside"))
    (source / "escape.epub").symlink_to(outside)
    (source / "broken.epub").write_bytes(b"damaged")
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    assert worker.candidates().total == 3
    assert worker.candidates(state="ready").total == 1
    assert worker.candidates(state="error").total == 2
    assert str(tmp_path) not in worker.candidates().model_dump_json()
    worker.stable_seconds = 30
    job = worker.scan(ScanRequest(root="books"))
    finish(worker)
    assert worker.candidates(state="waiting").total == 2
    current = next(j for j in worker.jobs().items if j.id == job.id)
    worker.stable_seconds = 0
    worker.change(job.id, JobChange(action="retry", revision=current.revision))
    finish(worker)
    assert worker.candidates(state="ready").total == 1
    valid.unlink()
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    assert worker.candidates(q="valid").items[0].state == "error"


def test_source_changes_during_inspection_require_retry(inbox, monkeypatch):
    import stacks.intake as module

    worker, library, source = inbox
    original = source / "changing.epub"
    original.write_bytes(epub_bytes("Before"))
    inspect = module.inspect_file

    def changing(path, name):
        result = inspect(path, name)
        path.write_bytes(epub_bytes("After"))
        return result

    monkeypatch.setattr(module, "inspect_file", changing)
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    candidate = worker.candidates().items[0]
    assert candidate.state == "waiting"
    assert candidate.sha256 is None
    assert library.list().total == 0


def test_cancel_retry_and_missing_root_preserve_checkpoints(inbox):
    worker, library, source = inbox
    for index in range(35):
        (source / f"{index}.epub").write_bytes(epub_bytes(str(index)))
    job = worker.scan(ScanRequest(root="books"))
    worker.step()
    current = worker.jobs().items[0]
    worker.change(job.id, JobChange(action="cancel", revision=current.revision))
    assert worker.step() is False
    current = worker.jobs().items[0]
    with pytest.raises(ValueError, match="changed"):
        worker.change(job.id, JobChange(action="retry", revision=1))
    worker.change(job.id, JobChange(action="retry", revision=current.revision))
    library.sources.clear()
    worker.step()
    assert worker.jobs().items[0].state == "error"
    assert worker.candidates().total == 32
    library.sources["books"] = source
    current = worker.jobs().items[0]
    worker.change(job.id, JobChange(action="retry", revision=current.revision))
    finish(worker)
    assert worker.candidates().total == 35
    assert worker.jobs().items[0].completed == 35


def test_slow_inspection_allows_catalog_writes_and_shutdown_waits(inbox, monkeypatch):
    import stacks.intake as module
    from stacks.schemas import WorkEdit

    worker, library, source = inbox
    publication = source / "slow.epub"
    publication.write_bytes(epub_bytes("Slow"))
    work = library.import_file(publication, publication.name).work
    entered, release = Event(), Event()
    inspect = module.inspect_file

    def delayed(path, name):
        entered.set()
        assert release.wait(5)
        return inspect(path, name)

    monkeypatch.setattr(module, "inspect_file", delayed)
    worker.scan(ScanRequest(root="books"))
    worker.start()
    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            assert entered.wait(3)
            editing = executor.submit(
                library.edit,
                work.id,
                WorkEdit(title="Edited", authors=[], description="", revision=work.revision),
            )
            assert editing.result(timeout=1).title == "Edited"
            closing = executor.submit(worker.close)
            assert not closing.done()
        finally:
            release.set()
        closing.result(timeout=3)
    assert library.get(work.id).title == "Edited"
    assert worker.jobs().items[0].remaining == 1


def test_backup_restores_scan_and_candidate_facts_with_relocated_root(inbox, tmp_path):
    worker, library, source = inbox
    (source / "fresh.epub").write_bytes(epub_bytes("Fresh"))
    worker.scan(ScanRequest(root="books"))
    worker.step()
    archive = tmp_path / "backup.zip"
    backup(library, archive)
    target = tmp_path / "restored"
    restore(archive, target)
    restored = Library(target, {"books": source})
    resumed = Intake(restored, stable_seconds=0)
    try:
        finish(resumed)
        assert resumed.candidates().items[0].facts["title"] == "Fresh"
        export = restored.export()
        assert export["schema_version"] == 14
        assert export["roots"]["books"] == {"kind": "external"}
        assert len(export["tables"]["inbox_candidate"]) == 1
    finally:
        resumed.close()
        restored.close()


def test_scan_api_auth_and_background_completion(client, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    publication = source / "api.epub"
    publication.write_bytes(epub_bytes("API Inbox"))
    os.utime(publication, (1, 1))
    client.app.state.library.sources["books"] = source
    response = client.post("/api/intake/scans", json={"root": "books"})
    assert response.status_code == 200, response.text
    # The owned worker executes this job; no endpoint performs file inspection inline.
    import time

    for _ in range(100):
        page = client.get("/api/intake/candidates").json()
        if page["items"] and page["items"][0]["state"] == "ready":
            break
        time.sleep(0.02)
    assert page["items"][0]["facts"]["title"] == "API Inbox"
    assert client.get("/api/intake/candidates?limit=101").status_code == 422
    assert client.post("/api/intake/scans", json={"root": "absent"}).status_code == 422
    assert (
        client.post("/api/intake/scans", json={"root": "books", "prefix": "../"}).status_code == 422
    )
    assert (
        client.post(
            f"/api/intake/jobs/{response.json()['id']}", json={"action": "cancel", "revision": 1}
        ).status_code
        == 409
    )
    client.cookies.clear()
    assert client.get("/api/intake/jobs").status_code == 401
    assert client.get("/api/intake/candidates").status_code == 401
    assert client.post("/api/intake/scans", json={"root": "books"}).status_code == 401


def test_nested_discovery_keeps_active_iterator_and_restores_missing_alias(inbox, monkeypatch):
    import stacks.intake as module
    from stacks.sources import Sources

    worker, library, source = inbox
    for index in range(40):
        folder = source / str(index)
        folder.mkdir()
        (folder / "book.epub").write_bytes(epub_bytes(str(index)))
    scans = []
    scandir = module.os.scandir

    def tracked(path):
        scans.append(path)
        return scandir(path)

    monkeypatch.setattr(module.os, "scandir", tracked)
    worker.scan(ScanRequest(root="books"))
    finish(worker)
    assert worker.candidates().total == 40
    assert scans.count(source) == 1
    assert len(scans) == 41
    library.sources.clear()
    roots = Sources(library).list()
    assert len(roots) == 1 and roots[0].alias == "books"
    assert roots[0].configured is False and roots[0].registered_assets == 0


def test_duplicate_evidence_follows_split_and_undo_without_rescan(client, tmp_path):
    from .test_operations import commit, pair, preview

    source, target = pair(client)
    representation = source["editions"][0]["representations"][0]
    commit(client, preview(client, source, target))
    library = client.app.state.library
    folder = tmp_path / "duplicate"
    folder.mkdir()
    original = client.get(f"/api/assets/{representation['assets'][0]['id']}/download").content
    (folder / "same.epub").write_bytes(original)
    library.sources["duplicates"] = folder
    worker = client.app.state.intake
    worker.stable_seconds = 0
    worker.scan(ScanRequest(root="duplicates"))
    import time

    for _ in range(100):
        candidates = worker.candidates(state="duplicate")
        if candidates.total:
            break
        time.sleep(0.02)
    candidate = candidates.items[0]
    assert candidate.work_id == target["id"]
    grouped = client.get(f"/api/works/{target['id']}").json()
    split = preview(client, grouped, mode="split", representation_id=representation["id"])
    result = commit(client, split)
    separate_id = result["work_ids"][1]
    current = worker.candidates(state="duplicate").items[0]
    assert current.id == candidate.id and current.work_id == separate_id
    assert client.get(f"/api/works/{current.work_id}").status_code == 200
    assert client.post(f"/api/operations/{split['id']}/undo").status_code == 200
    current = worker.candidates(state="duplicate").items[0]
    assert current.work_id == target["id"]
    assert client.get(f"/api/works/{separate_id}").status_code == 404
