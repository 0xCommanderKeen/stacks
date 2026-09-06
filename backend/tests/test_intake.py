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
