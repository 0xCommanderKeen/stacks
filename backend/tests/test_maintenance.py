import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from stacks.backup import backup, restore
from stacks.library import Library
from stacks.maintenance import Backups
from stacks.models import Asset
from stacks.samples import epub_bytes
from stacks.schemas import BackupCreate, WorkEdit

from .conftest import upload
from .test_covers import choose, picture


def test_catalog_backup_preserves_chosen_original_but_declares_omitted_media(client, tmp_path):
    work = choose(client, upload(client, epub_bytes("Metadata only backup")).json()["work"])
    library = client.app.state.library
    output = tmp_path / "catalog.zip"
    manifest = backup(library, output, "catalog")
    assert manifest["version"] == 3 and manifest["managed_originals_omitted"] == 1
    with zipfile.ZipFile(output) as archive:
        assert all(
            name == "catalog.sqlite3" or name == "manifest.json" or name.endswith("/original")
            for name in archive.namelist()
        )
    with pytest.raises(ValueError, match="omits media"):
        restore(output, tmp_path / "rejected")
    restore(output, tmp_path / "restored", allow_missing_originals=True)
    restored = Library(tmp_path / "restored")
    try:
        restored_work = restored.get(work["id"])
        assert restored_work.selected_cover_id == work["selected_cover_id"]
        assert (
            restored.resolve(f".covers/{work['selected_cover_id']}/original").read_bytes()
            == picture()
        )
        asset = restored_work.editions[0].representations[0].assets[0]
        with restored.sessions() as session:
            stored_asset = session.get(Asset, asset.id)
            with pytest.raises(FileNotFoundError):
                restored.resolve_asset(stored_asset)
        assert (restored.data_dir / "MEDIA-RESTORE-REQUIRED.txt").exists()
    finally:
        restored.close()


def test_archive_packaging_releases_catalog_lock_and_keeps_a_consistent_snapshot(client, tmp_path):
    work = upload(client, epub_bytes("Before backup")).json()["work"]
    library = client.app.state.library
    reached, proceed = threading.Event(), threading.Event()

    def checkpoint(size):
        if size and not reached.is_set():
            reached.set()
            assert proceed.wait(5)

    output = tmp_path / "snapshot.zip"
    with ThreadPoolExecutor(max_workers=2) as executor:
        task = executor.submit(backup, library, output, "full", checkpoint)
        assert reached.wait(5)
        try:
            edited = executor.submit(
                library.edit,
                work["id"],
                WorkEdit(
                    revision=work["revision"],
                    title="After backup",
                    authors=work["authors"],
                    description=work["description"],
                ),
            ).result(timeout=2)
            assert edited.title == "After backup"
            assert library.list(q="After").total == 1
        finally:
            proceed.set()
        task.result(timeout=5)
    restore(output, tmp_path / "restored")
    restored = Library(tmp_path / "restored")
    try:
        assert restored.get(work["id"]).title == "Before backup"
    finally:
        restored.close()


def test_queued_backup_history_download_and_restart_error(client, tmp_path):
    client.app.state.backups.close()
    manager = Backups(client.app.state.library)
    manager.create(BackupCreate())
    with pytest.raises(ValueError, match="already"):
        manager.create(BackupCreate())
    assert manager.step()
    completed = manager.list().items[0]
    assert completed.state == "complete" and completed.available and completed.bytes > 0
    assert manager.health().last_backup.id == completed.id
    path, name = manager.download(completed.id)
    assert path.is_file() and name == "stacks.catalog.backup.zip"
    manager.remove_copy(completed.id)
    assert not manager.list().items[0].available
    pending = manager.create(BackupCreate(mode="full"))
    manager = Backups(client.app.state.library)
    assert next(item for item in manager.list().items if item.id == pending.id).state == "error"
    assert not manager.list().items[0].available


def test_failed_backup_keeps_previous_history_and_no_download(client, monkeypatch):
    client.app.state.backups.close()
    manager = Backups(client.app.state.library)

    def fail(*args):
        raise OSError("private path")

    monkeypatch.setattr("stacks.maintenance.backup", fail)
    manager.create(BackupCreate())
    manager.step()
    record = manager.list().items[0]
    assert record.state == "error" and not record.available
    assert "private path" not in record.error
    with pytest.raises(KeyError):
        manager.download(record.id)


def test_preupgrade_snapshot_is_private_and_failure_prevents_schema_change(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from stacks import snapshots
    from stacks.db import connect

    data = tmp_path / "catalog"
    library = Library(data)
    library.close()
    engine = connect(data / "catalog.sqlite3")
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "stacks" / "migrations")
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0014")
    engine.dispose()
    original = snapshots.snapshot_database

    def fail(*args):
        raise OSError("No space for recovery snapshot")

    monkeypatch.setattr(snapshots, "snapshot_database", fail)
    with pytest.raises(OSError):
        Library(data)
    with sqlite3.connect(data / "catalog.sqlite3") as database:
        assert database.execute("SELECT version_num FROM alembic_version").fetchone() == ("0014",)
    monkeypatch.setattr(snapshots, "snapshot_database", original)
    library = Library(data)
    library.close()
    saved = list((data / "schema-backups").glob("*.sqlite3"))
    assert len(saved) == 1 and saved[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(saved[0]) as database:
        assert database.execute("SELECT version_num FROM alembic_version").fetchone() == ("0014",)
        assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_rebuild_thumbnails_from_immutable_originals_and_missing_media(client):
    from stacks.thumbnails import rebuild

    work = choose(client, upload(client, epub_bytes("Rebuild my cover")).json()["work"])
    library = client.app.state.library
    selected = library.resolve(f".covers/{work['selected_cover_id']}/thumbnail.jpg")
    selected.unlink()
    representation = work["editions"][0]["representations"][0]
    embedded = library.resolve(f"{representation['id']}/cover.jpg")
    embedded.unlink()
    result = rebuild(library)
    assert result == {"rebuilt": 2, "without_cover": 0, "unavailable": 0}
    assert selected.is_file() and embedded.is_file()
    with library.sessions() as session:
        asset = session.get(Asset, representation["assets"][0]["id"])
        library.resolve_asset(asset).unlink()
    result = rebuild(library)
    assert result["rebuilt"] == 1 and result["unavailable"] == 1
    assert selected.is_file()


def test_backup_api_queues_downloads_and_removes_only_server_copy(client):
    client.app.state.backups.close()
    client.app.state.backups = Backups(client.app.state.library)
    created = client.post("/api/backups", json={"mode": "catalog"})
    assert created.status_code == 200
    identifier = created.json()["id"]
    assert client.get(f"/api/backups/{identifier}/download").status_code == 404
    assert client.app.state.backups.step()
    response = client.get(f"/api/backups/{identifier}/download")
    assert response.status_code == 200 and response.content.startswith(b"PK")
    assert client.get("/api/maintenance").json()["last_backup"]["id"] == identifier
    assert client.delete(f"/api/backups/{identifier}/copy").status_code == 204
    assert client.get(f"/api/backups/{identifier}/download").status_code == 404
    assert client.get("/api/backups").json()["items"][0]["state"] == "complete"
