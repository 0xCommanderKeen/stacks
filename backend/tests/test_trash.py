import errno
from pathlib import Path

import pytest
from sqlalchemy import select
from stacks.backup import backup, restore
from stacks.collections import Collections
from stacks.curation import Curation
from stacks.intake import Intake
from stacks.library import Library
from stacks.models import Asset, CollectionEntry, TrashFile
from stacks.reading import Reading
from stacks.samples import epub_bytes
from stacks.schemas import (
    CollectionChange,
    CollectionEdit,
    PersonalEdit,
    ProgressEdit,
    RecordEdit,
    TrashRequest,
    WorkEdit,
)
from stacks.trash import Trash


@pytest.fixture
def library(tmp_path):
    library = Library(tmp_path / "library")
    yield library
    library.close()


def publication(library, tmp_path, title="Recoverable"):
    path = tmp_path / f"{title}.epub"
    path.write_bytes(epub_bytes(title))
    return library.import_file(path, path.name).work


def finish(trash):
    for _ in range(100):
        if not trash.step():
            return
    raise AssertionError("Trash did not finish")


def test_trash_preserves_identity_curation_collections_and_verified_restore(library, tmp_path):
    work = publication(library, tmp_path)
    curation = Curation(library)
    work = curation.edit(
        work.id, PersonalEdit(revision=work.revision, notes="Keep this", rating=4, tags=["Owned"])
    )
    record = curation.save_record(work.id, RecordEdit(kind="read", started="2026-01-01"))
    collections = Collections(library)
    collection = collections.save(CollectionEdit(name="Keep order", home=True))
    collection = collections.change(
        collection.id, CollectionChange(revision=collection.revision, action="add", work_id=work.id)
    )
    with library.sessions() as session:
        before = session.scalar(select(Asset))
        asset_id, original_location = before.id, before.relative_path
        original = library.resolve_asset(before).read_bytes()
        entry_id = session.scalar(select(CollectionEntry.id))
    trash = Trash(library)
    work = library.get(work.id)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    assert operation.total == 1 and library.list().total == 0
    assert library.get(work.id).trashed_at
    assert collections.works(collection.id).total == 0
    assert collections.next().total == 0
    with pytest.raises(ValueError, match="pending trash"):
        backup(library, tmp_path / "unfinished.zip")
    finish(trash)
    assert not (library.managed / original_location).exists()
    with library.sessions() as session:
        asset = session.get(Asset, asset_id)
        assert asset.relative_path.startswith(".trash/")
        assert library.resolve_asset(asset).read_bytes() == original
    hidden = library.get(work.id)
    assert hidden.personal.notes == "Keep this" and hidden.personal.tags == ["Owned"]
    with pytest.raises(ValueError, match="Restore"):
        library.edit(
            work.id, WorkEdit(revision=hidden.revision, title="No", authors=[], description="")
        )
    duplicate = publication(library, tmp_path)
    assert duplicate.id == work.id and duplicate.trashed_at
    operation = trash.request(work.id, TrashRequest(revision=hidden.revision, action="restore"))
    assert library.list().total == 0
    finish(trash)
    restored = library.get(work.id)
    assert not restored.trashed_at and restored.revision > hidden.revision
    assert curation.records(work.id).items[0].id == record.id
    assert collections.works(collection.id).items[0].id == entry_id
    assert library.list().total == 1
    with library.sessions() as session:
        asset = session.get(Asset, asset_id)
        assert asset.relative_path == original_location
        assert library.resolve_asset(asset).read_bytes() == original
    # A second complete cycle uses the latest trash manifest.
    trash.request(work.id, TrashRequest(revision=restored.revision, action="trash"))
    finish(trash)
    trash.request(work.id, TrashRequest(revision=library.get(work.id).revision, action="restore"))
    finish(trash)
    assert library.list().total == 1


@pytest.mark.parametrize("failure", ["permission", "full", "after-link", "after-unlink"])
def test_relocation_failures_resume_without_losing_or_overwriting_originals(
    library, tmp_path, monkeypatch, failure
):
    import stacks.trash as module

    work = publication(library, tmp_path)
    trash = Trash(library)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    with library.sessions() as session:
        file = session.scalar(select(TrashFile))
    source, destination = library.managed / file.source, library.managed / file.destination
    original = source.read_bytes()
    link, move = module.os.link, trash._move
    with monkeypatch.context() as patch:
        if failure == "after-unlink":

            def interrupted(*args):
                move(*args)
                raise OSError("Lost receipt")

            patch.setattr(trash, "_move", interrupted)
        else:

            def interrupted(*args):
                if failure == "after-link":
                    link(*args)
                raise OSError(errno.ENOSPC if failure == "full" else errno.EACCES, "Injected")

            patch.setattr(module.os, "link", interrupted)
        assert trash.step()
    failed = trash.operation(operation.id)
    assert failed.state == "error" and failed.completed == 0
    assert any(path.exists() and path.read_bytes() == original for path in (source, destination))
    trash.retry(operation.id, failed.revision)
    finish(trash)
    assert trash.operation(operation.id).state == "complete"
    assert not source.exists() and destination.read_bytes() == original


def test_collision_and_source_changes_refuse_without_deleting_either_file(library, tmp_path):
    work = publication(library, tmp_path)
    trash = Trash(library)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    with library.sessions() as session:
        file = session.scalar(select(TrashFile))
    source, destination = library.managed / file.source, library.managed / file.destination
    original = source.read_bytes()
    destination.parent.mkdir(parents=True)
    destination.write_bytes(original)  # Even byte-identical unrelated destinations are collisions.
    finish(trash)
    failed = trash.operation(operation.id)
    assert failed.state == "error" and "occupied" in failed.error
    assert source.read_bytes() == destination.read_bytes() == original
    destination.unlink()
    source.write_bytes(b"unexpected replacement")
    trash.retry(operation.id, failed.revision)
    finish(trash)
    assert "changed" in trash.operation(operation.id).error
    assert source.read_bytes() == b"unexpected replacement" and not destination.exists()


def test_read_only_removal_does_not_require_mount_and_never_touches_source(library, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    original = source / "external.epub"
    original.write_bytes(epub_bytes("External"))
    before = original.stat()
    library.sources["source"] = source
    work = library.register_files("source", [original.name]).work
    library.sources.clear()
    trash = Trash(library)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    assert operation.total == 0
    finish(trash)
    trash.request(work.id, TrashRequest(revision=library.get(work.id).revision, action="restore"))
    finish(trash)
    assert library.list().total == 1
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    assert original.read_bytes() == epub_bytes("External")


def test_trash_backup_restores_and_worker_restarts_queued_operations(library, tmp_path):
    work = publication(library, tmp_path)
    trash = Trash(library)
    trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    worker = Intake(library)
    while worker.step():
        pass
    worker.close()
    archive = tmp_path / "trash.zip"
    backup(library, archive)
    target = tmp_path / "restored"
    restore(archive, target)
    with_library = Library(target)
    try:
        restored = Trash(with_library)
        assert restored.list().items[0].work.id == work.id
        restored.request(
            work.id, TrashRequest(revision=with_library.get(work.id).revision, action="restore")
        )
    finally:
        with_library.close()
    reopened = Library(target)
    try:
        resumed = Intake(reopened)
        while resumed.step():
            pass
        resumed.close()
        assert reopened.list().total == 1
        assert reopened.get(work.id).personal == work.personal
    finally:
        reopened.close()


def test_audio_progress_remains_but_trash_is_not_a_listening_choice(library):
    fixture = Path(__file__).parent / "fixtures" / "tone.mp3"
    result = library.import_file(fixture, fixture.name)
    work, representation = result.work, result.work.editions[0].representations[0]
    reading = Reading(library)
    asset_id = representation.assets[0].id
    progress = reading.update(
        representation.id, ProgressEdit(revision=0, asset_id=asset_id, position=1, speed=1)
    )
    trash = Trash(library)
    trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    assert reading.continue_list().total == 0
    with pytest.raises(ValueError, match="Restore"):
        reading.stream(asset_id)
    # A final in-flight pause save still preserves what was heard.
    progress = reading.update(
        representation.id,
        ProgressEdit(revision=progress.revision, asset_id=asset_id, position=2, speed=1),
    )
    finish(trash)
    trash.request(work.id, TrashRequest(revision=library.get(work.id).revision, action="restore"))
    finish(trash)
    assert reading.playback(representation.id).progress == progress
    assert reading.continue_list().total == 1


def test_grouping_undo_cannot_erase_trash_history_and_api_blocks_downloads(client):
    from .test_operations import commit, pair, preview

    client.app.state.intake.close()
    source, target = pair(client)
    representation = source["editions"][0]["representations"][0]
    commit(client, preview(client, source, target))
    grouped = client.get(f"/api/works/{target['id']}").json()
    split = preview(client, grouped, mode="split", representation_id=representation["id"])
    separate_id = commit(client, split)["work_ids"][1]
    separate = client.get(f"/api/works/{separate_id}").json()
    response = client.post(
        f"/api/works/{separate_id}/trash",
        json={"action": "trash", "revision": separate["revision"]},
    )
    assert response.status_code == 200, response.text
    assert (
        client.get(f"/api/assets/{representation['assets'][0]['id']}/download").status_code == 409
    )
    assert client.post(f"/api/operations/{split['id']}/undo").status_code == 409
    trash = client.app.state.intake.trash
    finish(trash)
    hidden = client.get(f"/api/works/{separate_id}").json()
    assert (
        client.post(
            f"/api/works/{separate_id}/trash",
            json={"action": "restore", "revision": hidden["revision"]},
        ).status_code
        == 200
    )
    finish(trash)
    # This undo would delete the work owning durable trash receipts, so it must refuse cleanly.
    assert client.post(f"/api/operations/{split['id']}/undo").status_code == 409
    assert (
        client.get(f"/api/assets/{representation['assets'][0]['id']}/download").status_code == 200
    )
    client.cookies.clear()
    assert client.get("/api/trash").status_code == 401
    assert (
        client.post(
            f"/api/works/{separate_id}/trash", json={"action": "trash", "revision": 1}
        ).status_code
        == 401
    )


def test_mixed_managed_and_external_work_preserves_source_and_run_membership(client, tmp_path):
    from stacks.schemas import MembershipEdit, SeriesEdit
    from stacks.series import SeriesCatalog

    from .conftest import upload
    from .test_operations import commit, preview

    client.app.state.intake.close()
    library = client.app.state.library
    source = tmp_path / "source"
    source.mkdir()
    original = source / "source.epub"
    original.write_bytes(epub_bytes("External edition"))
    before = original.stat()
    library.sources["source"] = source
    external = library.register_files("source", [original.name]).work.model_dump()
    managed = upload(client, epub_bytes("Managed edition")).json()["work"]
    commit(client, preview(client, external, managed))
    work = library.get(managed["id"])
    series = library.save_series(SeriesEdit(name="Restored run"))
    work = library.edit(
        work.id,
        WorkEdit(
            revision=work.revision,
            title=work.title,
            authors=work.authors,
            description=work.description,
            memberships=[MembershipEdit(series_id=series.id, designation="Annual", position=2)],
        ),
    )
    trash = Trash(library)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    assert operation.total == 1
    assert SeriesCatalog(library).works(series.id).total == 0
    finish(trash)
    trash.request(work.id, TrashRequest(revision=library.get(work.id).revision, action="restore"))
    finish(trash)
    assert len(library.get(work.id).editions) == 2
    assert library.get(work.id).memberships == work.memberships
    assert SeriesCatalog(library).works(series.id).total == 1
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    assert original.read_bytes() == epub_bytes("External edition")


def test_trash_verification_keeps_catalog_available(library, tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    hidden = publication(library, tmp_path)
    visible = publication(library, tmp_path, "Still visible")
    trash = Trash(library)
    trash.request(hidden.id, TrashRequest(revision=hidden.revision, action="trash"))
    entered, release = threading.Event(), threading.Event()
    verify = trash._verify

    def slow_verify(*args):
        entered.set()
        assert release.wait(5)
        return verify(*args)

    monkeypatch.setattr(trash, "_verify", slow_verify)
    with ThreadPoolExecutor(max_workers=2) as pool:
        moving = pool.submit(trash.step)
        assert entered.wait(5)
        try:
            result = pool.submit(library.list).result(timeout=1)
            assert [work.id for work in result.items] == [visible.id]
            with pytest.raises(ValueError, match="pending trash"):
                pool.submit(backup, library, tmp_path / "concurrent.zip").result(timeout=1)
        finally:
            release.set()
        assert moving.result(timeout=5)
    finish(trash)


def test_actual_restart_recovers_link_before_catalog_acknowledgement(tmp_path, monkeypatch):
    import stacks.trash as module

    class PowerLoss(BaseException):
        pass

    data = tmp_path / "restart"
    library = Library(data)
    work = publication(library, tmp_path)
    trash = Trash(library)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    link = module.os.link
    with monkeypatch.context() as patch:

        def crash(*args):
            link(*args)
            raise PowerLoss()

        patch.setattr(module.os, "link", crash)
        with pytest.raises(PowerLoss):
            trash.step()
    library.close()
    reopened = Library(data)
    try:
        resumed = Trash(reopened)
        finish(resumed)
        assert resumed.operation(operation.id).state == "complete"
        assert resumed.list().items[0].work.id == work.id
        resumed.request(
            work.id, TrashRequest(revision=reopened.get(work.id).revision, action="restore")
        )
        finish(resumed)
        assert reopened.list().items[0].id == work.id
    finally:
        reopened.close()


def test_recovery_fsyncs_destination_ancestors_before_unlink_and_ack(
    library, tmp_path, monkeypatch
):
    import stacks.trash as module

    work = publication(library, tmp_path)
    trash = Trash(library)
    operation = trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
    with library.sessions() as session:
        file = session.scalar(select(TrashFile))
    source, destination = library.managed / file.source, library.managed / file.destination
    destination.parent.mkdir(parents=True)
    sync = module.sync_dir
    with monkeypatch.context() as patch:

        def fail_destination(path):
            if path == destination.parent:
                raise OSError("Destination directory fsync failed")
            sync(path)

        patch.setattr(module, "sync_dir", fail_destination)
        trash.step()
        first = trash.operation(operation.id)
        trash.retry(operation.id, first.revision)
        trash.step()
        assert source.samefile(destination)
    assert source.samefile(destination)
    failed = trash.operation(operation.id)
    assert failed.state == "error"
    events = []
    unlink = Path.unlink
    with monkeypatch.context() as patch:

        def tracked_sync(path):
            events.append(("sync", path))
            sync(path)

        def tracked_unlink(path, *args, **kwargs):
            events.append(("unlink", path))
            return unlink(path, *args, **kwargs)

        patch.setattr(module, "sync_dir", tracked_sync)
        patch.setattr(Path, "unlink", tracked_unlink)
        trash.retry(operation.id, failed.revision)
        finish(trash)
    deletion = events.index(("unlink", source))
    for ancestor in (destination.parent, destination.parent.parent, library.managed):
        assert events.index(("sync", ancestor)) < deletion
    assert events.index(("sync", source.parent)) > deletion
    assert trash.operation(operation.id).state == "complete"
