import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from stacks.app import create_app
from stacks.backup import backup, restore
from stacks.library import Library
from stacks.models import Asset, ImportOperation
from stacks.samples import epub_bytes

from .conftest import HEADERS, PASSWORD, upload


def test_complete_book_restart_and_restore(client, settings, publication, tmp_path):
    imported = upload(client, publication)
    assert imported.status_code == 200, imported.text
    book = imported.json()["work"]
    assert book["title"] == "The Quiet Library"
    assert book["authors"] == ["Alex Reed"]
    representation = book["editions"][0]["representations"][0]
    asset = representation["assets"][0]
    library = client.app.state.library
    with library.sessions() as session:
        old_path = session.get(Asset, asset["id"]).relative_path
    changed = client.patch(
        f"/api/works/{book['id']}",
        json={
            "revision": book["revision"],
            "title": "My corrected title",
            "authors": ["New Author"],
            "description": "My own description",
        },
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/catalog?q=New%20Author").json()["total"] == 1
    assert client.get("/api/catalog?q=Alex").json()["total"] == 0
    with library.sessions() as session:
        assert session.get(Asset, asset["id"]).relative_path == old_path
    download = client.get(f"/api/assets/{asset['id']}/download")
    assert download.content == publication
    assert download.headers["content-type"] == "application/epub+zip"
    assert (
        client.get(f"/api/representations/{representation['id']}/cover").headers["content-type"]
        == "image/jpeg"
    )
    export = client.get("/api/export").json()
    assert export["schema_version"] == 7
    assert export["tables"]["work"][0]["title"] == "My corrected title"
    assert "login_session" not in export["tables"]
    assert (
        json.loads(export["tables"]["representation"][0]["extracted_json"])["title"]
        == "The Quiet Library"
    )
    archive = tmp_path / "backup.zip"
    archive.write_bytes(client.post("/api/backup").content)
    restored = tmp_path / "restored"
    restore(archive, restored)
    with TestClient(create_app(settings.model_copy(update={"data_dir": restored}))) as fresh:
        assert fresh.get("/api/catalog").status_code == 401
        fresh.post("/api/login", json={"password": PASSWORD}, headers=HEADERS)
        assert fresh.get("/api/catalog").json()["items"][0]["title"] == "My corrected title"
        assert fresh.get(f"/api/assets/{asset['id']}/download").content == publication
    # Close the first instance and reopen the same data root, including WAL and session persistence.
    library.close()
    reopened = Library(settings.data_dir)
    try:
        assert reopened.get(book["id"]).title == "My corrected title"
        assert reopened.resolve(old_path).read_bytes() == publication
    finally:
        reopened.close()


def test_exact_duplicate_keeps_one_work(client, publication):
    one = upload(client, publication).json()
    two = upload(client, publication, "different-name.epub").json()
    assert not one["duplicate"] and two["duplicate"]
    assert one["work"]["id"] == two["work"]["id"]
    assert client.get("/api/catalog").json()["total"] == 1


def test_same_title_is_not_same_work(client):
    first = upload(client, epub_bytes("Shared Title", ("One Author",))).json()
    second = upload(client, epub_bytes("Shared Title", ("Another Author",))).json()
    assert first["work"]["id"] != second["work"]["id"]
    assert client.get("/api/catalog?q=Shared").json()["total"] == 2


def test_stale_edit_is_rejected(client, publication):
    book = upload(client, publication).json()["work"]
    edit = {"revision": 1, "title": "First edit", "authors": [], "description": ""}
    assert client.patch(f"/api/works/{book['id']}", json=edit).status_code == 200
    edit["title"] = "Stale edit"
    assert client.patch(f"/api/works/{book['id']}", json=edit).status_code == 409
    assert client.get(f"/api/works/{book['id']}").json()["title"] == "First edit"


def test_search_escapes_wildcards_and_pages_in_sql(client):
    for title in ("100% Books", "1000 Books", "Third Book"):
        assert upload(client, epub_bytes(title)).status_code == 200
    assert client.get("/api/catalog?q=%25").json()["total"] == 1
    result = client.get("/api/catalog?limit=1&offset=1").json()
    assert result["total"] == 3 and len(result["items"]) == 1
    assert client.get("/api/catalog?limit=1000").status_code == 422


@pytest.mark.parametrize("checkpoint", ["before_publish", "after_rename"])
def test_crash_recovery(tmp_path, publication, monkeypatch, checkpoint):
    data = tmp_path / "library"
    source = tmp_path / "source.epub"
    source.write_bytes(publication)
    library = Library(data)
    if checkpoint == "before_publish":
        monkeypatch.setattr(
            library, "_publish", lambda _id: (_ for _ in ()).throw(RuntimeError("crash"))
        )
    else:
        import stacks.library as module

        actual = module.sync_dir

        def crash_after_rename(path):
            if path == library.managed:
                raise RuntimeError("crash")
            actual(path)

        monkeypatch.setattr(module, "sync_dir", crash_after_rename)
    with pytest.raises(RuntimeError):
        library.import_file(source, "source.epub")
    library.close()
    monkeypatch.undo()
    recovered = Library(data)
    try:
        page = recovered.list()
        assert page.total == 1
        asset = page.items[0].editions[0].representations[0].assets[0]
        with recovered.sessions() as session:
            assert session.scalar(select(ImportOperation)).state == "complete"
            assert (
                recovered.resolve(session.get(Asset, asset.id).relative_path).read_bytes()
                == publication
            )
        recovered.recover()
        assert recovered.list().total == 1
        assert source.read_bytes() == publication
    finally:
        recovered.close()


def test_corrupt_pending_import_is_reported_and_retained(tmp_path, publication, monkeypatch):
    source = tmp_path / "source.epub"
    source.write_bytes(publication)
    library = Library(tmp_path / "library")
    monkeypatch.setattr(
        library, "_publish", lambda _id: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    with pytest.raises(RuntimeError):
        library.import_file(source, "source.epub")
    staged = next(library.staging.glob("*/original.epub"))
    staged.write_bytes(b"damaged")
    library.close()
    recovered = Library(tmp_path / "library")
    try:
        assert recovered.list().total == 0
        assert staged.exists()
        with recovered.sessions() as session:
            assert session.scalar(select(ImportOperation)).state == "error"
    finally:
        recovered.close()


def test_concurrent_duplicate_imports_are_serialized(tmp_path, publication):
    source = tmp_path / "source.epub"
    source.write_bytes(publication)
    library = Library(tmp_path / "library")
    try:
        with ThreadPoolExecutor(2) as executor:
            results = list(
                executor.map(lambda _: library.import_file(source, "book.epub"), range(2))
            )
        assert sorted(result.duplicate for result in results) == [False, True]
        assert library.list().total == 1
    finally:
        library.close()


def test_second_process_owner_is_rejected(client, settings):
    with pytest.raises(RuntimeError, match="already open"):
        Library(settings.data_dir)


def test_restore_does_not_overwrite_and_checks_bytes(client, publication, tmp_path):
    upload(client, publication)
    archive = tmp_path / "backup.zip"
    backup(client.app.state.library, archive)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        restore(archive, existing)
    corrupted = tmp_path / "corrupted.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(corrupted, "w") as target:
        for member in source.infolist():
            content = source.read(member)
            if member.filename.endswith("original.epub"):
                content = b"x" * len(content)
            target.writestr(member, content)
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="checksum"):
        restore(corrupted, destination)
    assert not destination.exists()


def test_restore_rejects_traversal(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("../outside", "bad")
    with pytest.raises(ValueError, match="paths"):
        restore(archive, tmp_path / "restored")
    assert not (tmp_path / "outside").exists()


def test_missing_original_does_not_erase_catalog(client, publication):
    book = upload(client, publication).json()["work"]
    lib = client.app.state.library
    with lib.sessions() as session:
        asset = session.scalar(select(Asset))
        lib.resolve(asset.relative_path).unlink()
        asset_id = asset.id
    assert client.get(f"/api/assets/{asset_id}/download").status_code == 409
    assert client.get(f"/api/works/{book['id']}").status_code == 200


def test_backup_rejects_changed_original(client, publication):
    upload(client, publication)
    lib = client.app.state.library
    with lib.sessions() as session:
        asset = session.scalar(select(Asset))
        lib.resolve(asset.relative_path).write_bytes(b"modified after import")
    response = client.post("/api/backup")
    assert response.status_code == 409
    assert "verification failed" in response.json()["detail"]


def test_initial_migration_matches_models_and_preserves_populated_data(client, publication):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from stacks.db import initialize
    from stacks.models import Base, Work

    book = upload(client, publication).json()["work"]
    lib = client.app.state.library
    with lib.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    engine, sessions = initialize(lib.data_dir / "catalog.sqlite3")
    try:
        with sessions() as session:
            assert session.get(Work, book["id"]).title == book["title"]
    finally:
        engine.dispose()


def test_reupload_resumes_pending_publication(tmp_path, publication, monkeypatch):
    source = tmp_path / "source.epub"
    source.write_bytes(publication)
    library = Library(tmp_path / "library")
    publish = library._publish
    monkeypatch.setattr(
        library, "_publish", lambda _: (_ for _ in ()).throw(OSError("interrupted"))
    )
    try:
        with pytest.raises(OSError):
            library.import_file(source, "book.epub")
        with pytest.raises(ValueError, match="unfinished"):
            backup(library, tmp_path / "incomplete.zip")
        monkeypatch.setattr(library, "_publish", publish)
        result = library.import_file(source, "retry.epub")
        assert result.work.title == "The Quiet Library"
        assert library.list().total == 1
        with library.sessions() as session:
            assert len(list(session.scalars(select(ImportOperation)))) == 1
    finally:
        library.close()


def test_recovered_destination_syncs_before_catalog_commit(tmp_path, publication, monkeypatch):
    import stacks.library as module

    source = tmp_path / "source.epub"
    source.write_bytes(publication)
    library = Library(tmp_path / "library")
    actual_sync = module.sync_dir
    calls = []
    failures = 0

    def fail_twice(path):
        nonlocal failures
        calls.append(path)
        if path == library.managed and failures < 2:
            failures += 1
            raise OSError("directory fsync failed")
        actual_sync(path)

    monkeypatch.setattr(module, "sync_dir", fail_twice)
    try:
        for _ in range(2):
            with pytest.raises(OSError, match="fsync"):
                library.import_file(source, "book.epub")
            assert library.list().total == 0
        calls.clear()
        library.import_file(source, "book.epub")
        assert calls == [library.managed, library.staging]
        assert library.list().total == 1
    finally:
        library.close()
