from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from stacks.reading import Reading
from stacks.samples import epub_bytes
from stacks.schemas import ProgressEdit

from .test_reading import audiobook


@pytest.mark.parametrize("registered", [False, True])
def test_original_verification_does_not_block_listening_progress(
    client, tmp_path, monkeypatch, registered
):
    import stacks.library as module

    work, representation, asset = audiobook(client)
    library = client.app.state.library
    source = tmp_path / "source"
    source.mkdir()
    publication = source / "large.epub"
    publication.write_bytes(epub_bytes("Concurrent intake"))
    library.sources["inbox"] = source
    digest = module.digest
    entered, release = Event(), Event()
    observations = 0

    def delayed(path):
        nonlocal observations
        if path == publication:
            observations += 1
        if (registered and path == publication and observations == 2) or (
            not registered and path.is_relative_to(library.staging)
        ):
            entered.set()
            assert release.wait(5)
        return digest(path)

    monkeypatch.setattr(module, "digest", delayed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        importing = (
            executor.submit(library.register_files, "inbox", ["large.epub"])
            if registered
            else executor.submit(library.import_file, publication, "large.epub")
        )
        try:
            assert entered.wait(3)
            saving = executor.submit(
                Reading(library).update,
                representation["id"],
                ProgressEdit(revision=0, asset_id=asset["id"], position=4),
            )
            assert saving.result(timeout=1).position == 4
            assert library.get(work["id"]).id == work["id"]
        finally:
            release.set()
        assert importing.result(timeout=3).work.title == "Concurrent intake"


def test_recovery_waits_for_unjournaled_copy_and_keeps_the_stage(client, tmp_path, monkeypatch):
    from concurrent.futures import TimeoutError

    import stacks.library as module

    library = client.app.state.library
    publication = tmp_path / "copy.epub"
    original = epub_bytes("Uninterrupted copy")
    publication.write_bytes(original)
    copying, release, recovery_started = Event(), Event(), Event()
    copy = module.shutil.copyfileobj

    def delayed(reader, writer, length):
        copying.set()
        assert release.wait(5)
        copy(reader, writer, length)

    def recover():
        recovery_started.set()
        library.recover()

    monkeypatch.setattr(module.shutil, "copyfileobj", delayed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        importing = executor.submit(library.import_file, publication, "copy.epub")
        try:
            assert copying.wait(3)
            stage = next(library.staging.iterdir())
            recovering = executor.submit(recover)
            assert recovery_started.wait(1)
            with pytest.raises(TimeoutError):
                recovering.result(timeout=0.1)
            assert stage.is_dir()
        finally:
            release.set()
        work = importing.result(timeout=3).work
        recovering.result(timeout=3)
    asset = work.editions[0].representations[0].assets[0]
    assert client.get(f"/api/assets/{asset.id}/download").content == original


def test_backup_refuses_pending_publication_without_waiting_for_file_io(
    client, tmp_path, monkeypatch
):
    from stacks.backup import backup

    library = client.app.state.library
    publication = tmp_path / "pending.epub"
    publication.write_bytes(epub_bytes("Pending publication"))
    publishing, release = Event(), Event()
    publish = library._publish

    def delayed(operation_id):
        publishing.set()
        assert release.wait(5)
        return publish(operation_id)

    monkeypatch.setattr(library, "_publish", delayed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        importing = executor.submit(library.import_file, publication, "pending.epub")
        try:
            assert publishing.wait(3)
            saving = executor.submit(backup, library, tmp_path / "backup.zip")
            with pytest.raises(ValueError, match="unfinished"):
                saving.result(timeout=1)
            assert not (tmp_path / "backup.zip").exists()
        finally:
            release.set()
        assert importing.result(timeout=3).work.title == "Pending publication"


def test_recovery_preserves_upload_while_request_is_streaming(client, monkeypatch):
    from anyio import to_thread
    from starlette.requests import Request

    library = client.app.state.library
    original = epub_bytes("Streaming intake")
    receiving, release = Event(), Event()
    stream = Request.stream

    async def delayed(request):
        async for chunk in stream(request):
            yield chunk
            if chunk:
                receiving.set()
                assert await to_thread.run_sync(release.wait, 5)

    monkeypatch.setattr(Request, "stream", delayed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        uploading = executor.submit(
            client.post,
            "/api/import",
            content=original,
            headers={"X-Filename": "stream.epub"},
        )
        try:
            assert receiving.wait(3)
            temporary = next(library.uploads.iterdir())
            executor.submit(library.recover).result(timeout=1)
            assert temporary.is_file()
        finally:
            release.set()
        response = uploading.result(timeout=3)
    assert response.status_code == 200, response.text
    asset = response.json()["work"]["editions"][0]["representations"][0]["assets"][0]
    assert client.get(f"/api/assets/{asset['id']}/download").content == original
    assert list(library.uploads.iterdir()) == []


def test_orphan_uploads_are_cleaned_only_when_exclusive_owner_starts(tmp_path):
    from stacks.library import Library

    library = Library(tmp_path / "library")
    orphan = library.uploads / "upload-interrupted.epub"
    orphan.write_bytes(b"unfinished upload")
    library.recover()
    assert orphan.is_file()
    library.close()
    reopened = Library(tmp_path / "library")
    try:
        assert not orphan.exists()
    finally:
        reopened.close()
