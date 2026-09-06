import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from stacks.app import create_app
from stacks.backup import backup, restore
from stacks.config import Settings
from stacks.library import Library
from stacks.models import Asset, ImportOperation
from stacks.samples import epub_bytes

from .conftest import HEADERS, PASSWORD
from .test_formats import FIXTURES
from .test_operations import commit, preview


@pytest.fixture
def source_client(tmp_path):
    sources = tmp_path / "originals"
    sources.mkdir()
    (sources / "Book.epub").write_bytes(epub_bytes("Registered book"))
    (sources / "Disc 1").mkdir()
    (sources / "Disc 2").mkdir()
    shutil.copy2(FIXTURES / "listening.m4b", sources / "Disc 1/01.m4b")
    shutil.copy2(FIXTURES / "tone.mp3", sources / "Disc 2/01.mp3")
    settings = Settings(
        data_dir=tmp_path / "data",
        password=PASSWORD,
        sources={"archive": sources},
        frontend_dir=tmp_path / "none",
    )
    with TestClient(create_app(settings)) as client:
        assert (
            client.post("/api/login", json={"password": PASSWORD}, headers=HEADERS).status_code
            == 204
        )
        client.headers.update(HEADERS)
        yield client, sources


def register(client, paths=None):
    response = client.post(
        "/api/sources/register", json={"root": "archive", "paths": paths or ["Book.epub"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_register_readonly_default_download_relocation_and_backup(source_client, tmp_path):
    client, source = source_client
    original = (source / "Book.epub").read_bytes()
    stamp = (source / "Book.epub").stat().st_mtime_ns
    result = register(client)
    work = result["work"]
    assert not result["duplicate"] and work["personal"]["default_shelf"] == "archive"
    asset = work["editions"][0]["representations"][0]["assets"][0]
    assert asset["root"] == "archive"
    assert client.get(f"/api/assets/{asset['id']}/download").content == original
    assert client.get("/api/catalog?scope=library").json()["total"] == 0
    assert client.get("/api/catalog?scope=archive").json()["total"] == 1
    assert register(client)["duplicate"] is True
    assert (source / "Book.epub").stat().st_mtime_ns == stamp
    lib = client.app.state.library
    assert not list(lib.managed.rglob("*.epub"))
    snapshot = lib.export()
    assert str(source) not in json.dumps(snapshot)
    assert snapshot["roots"]["archive"] == {"kind": "external"}
    archive = tmp_path / "backup.zip"
    backup(lib, archive)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["external_roots"] == {"archive": 1}
        assert not any(name.endswith(".epub") for name in z.namelist())
    moved = tmp_path / "relocated"
    source.rename(moved)
    assert not client.get("/api/sources").json()[0]["available"]
    assert client.get(f"/api/assets/{asset['id']}/download").status_code == 409
    assert client.get(f"/api/works/{work['id']}").json()["id"] == work["id"]
    restore(archive, tmp_path / "restored")
    reopened = Library(tmp_path / "restored", {"archive": moved})
    try:
        with reopened.sessions() as session:
            assert reopened.resolve_asset(session.get(Asset, asset["id"])).read_bytes() == original
        assert reopened.export()["tables"] == snapshot["tables"]
    finally:
        reopened.close()


def test_changed_path_escape_overlap_and_unknown_sources(source_client, tmp_path):
    client, source = source_client
    work = register(client)["work"]
    asset = work["editions"][0]["representations"][0]["assets"][0]
    (source / "Book.epub").write_bytes(epub_bytes("Changed publication"))
    availability = client.get(f"/api/works/{work['id']}/availability").json()
    assert availability[0]["available"] is False and "changed" in availability[0]["detail"]
    assert client.get(f"/api/assets/{asset['id']}/download").status_code == 409
    assert (
        client.post(
            "/api/sources/register", json={"root": "archive", "paths": ["Book.epub"]}
        ).status_code
        == 422
    )
    outside = tmp_path / "outside.epub"
    outside.write_bytes(epub_bytes("Outside"))
    (source / "escape.epub").symlink_to(outside)
    for relative in ("../outside.epub", str(outside), "escape.epub"):
        assert (
            client.post(
                "/api/sources/register", json={"root": "archive", "paths": [relative]}
            ).status_code
            == 409
        )
    assert (
        client.post(
            "/api/sources/register", json={"root": "unknown", "paths": ["Book.epub"]}
        ).status_code
        == 422
    )
    with pytest.raises(ValueError, match="overlap"):
        Library(tmp_path / "otherdata", {"archive": tmp_path})


def test_multi_track_originals_and_partial_overlap(source_client):
    client, source = source_client
    result = register(client, ["Disc 2/01.mp3", "Disc 1/01.m4b"])
    representation = result["work"]["editions"][0]["representations"][0]
    assert [asset["original_name"] for asset in representation["assets"]] == [
        "Disc 1/01.m4b",
        "Disc 2/01.mp3",
    ]
    playback = client.get(f"/api/representations/{representation['id']}/playback").json()
    asset = playback["tracks"][0]["asset_id"]
    stream = client.get(f"/api/assets/{asset}/stream", headers={"Range": "bytes=0-9"})
    assert stream.status_code == 206
    assert stream.content == (source / "Disc 1/01.m4b").read_bytes()[:10]
    assert (
        client.post(
            "/api/sources/register", json={"root": "archive", "paths": ["Disc 1/01.m4b"]}
        ).status_code
        == 422
    )
    assert register(client, ["Disc 1/01.m4b", "Disc 2/01.mp3"])["duplicate"] is True


def test_registration_interruption_and_source_changes_during_inspection(source_client, monkeypatch):
    client, source = source_client
    lib = client.app.state.library
    publish = lib._publish
    monkeypatch.setattr(lib, "_publish", lambda _: (_ for _ in ()).throw(OSError("interrupted")))
    response = client.post(
        "/api/sources/register", json={"root": "archive", "paths": ["Book.epub"]}
    )
    assert response.status_code == 409
    with lib.sessions() as session:
        assert session.scalar(select(ImportOperation.state)) == "staged"
    monkeypatch.setattr(lib, "_publish", publish)
    lib.recover()
    assert register(client)["duplicate"] is True
    (source / "Second.epub").write_bytes(epub_bytes("Second"))
    import stacks.library as module

    inspect = module.inspect_file

    def changing(path, name):
        result = inspect(path, name)
        os.utime(path, ns=(1, 1))
        return result

    monkeypatch.setattr(module, "inspect_file", changing)
    assert (
        client.post(
            "/api/sources/register", json={"root": "archive", "paths": ["Second.epub"]}
        ).status_code
        == 422
    )
    assert client.get("/api/catalog").json()["total"] == 1


def test_same_relative_name_in_two_roots_and_duplicate_current_owner(source_client, tmp_path):
    client, source = source_client
    first = register(client)["work"]
    other = tmp_path / "other"
    other.mkdir()
    (other / "Book.epub").write_bytes(epub_bytes("Different work"))
    lib = client.app.state.library
    lib.sources["other"] = other
    second = lib.register_files("other", ["Book.epub"]).work.model_dump()
    assert second["id"] != first["id"]
    commit(client, preview(client, first, second))
    assert register(client)["work"]["id"] == second["id"]


def test_populated_previous_schema_keeps_audio_progress_during_asset_rebuild(tmp_path):
    import stacks.db as db
    from alembic import command
    from alembic.config import Config
    from stacks.models import Progress
    from stacks.reading import Reading

    directory = tmp_path / "data"
    library = Library(directory)
    work = library.import_file(FIXTURES / "listening.m4b", "listening.m4b").work
    rep = work.editions[0].representations[0]
    config = Config()
    config.set_main_option("script_location", str(Path(db.__file__).parent / "migrations"))
    with library.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007")
    with library.sessions.begin() as session:
        session.add(
            Progress(
                representation_id=rep.id,
                asset_id=rep.assets[0].id,
                position=8,
                speed=1.5,
                completed=False,
                revision=3,
            )
        )
    library.close()
    reopened = Library(directory)
    try:
        progress = Reading(reopened).playback(rep.id).progress
        assert (progress.position, progress.revision, progress.asset_id) == (8, 3, rep.assets[0].id)
    finally:
        reopened.close()


def test_failed_schema_upgrade_rolls_back_ddl_and_restores_foreign_keys(tmp_path, monkeypatch):
    import sqlite3

    import stacks.db as db
    from sqlalchemy.exc import IntegrityError
    from stacks.models import Progress

    directory = tmp_path / "data"
    library = Library(directory)
    work = library.import_file(FIXTURES / "listening.m4b", "listening.m4b").work
    rep = work.editions[0].representations[0]
    with library.sessions.begin() as session:
        session.add(
            Progress(
                representation_id=rep.id,
                asset_id=rep.assets[0].id,
                position=2,
                speed=1,
                completed=False,
                revision=1,
            )
        )
    library.close()
    original = db.command.upgrade

    def broken(config, target):
        original(config, target)
        connection = config.attributes["connection"]
        connection.exec_driver_sql("CREATE TABLE failed_migration (id INTEGER)")
        connection.exec_driver_sql("DELETE FROM asset")

    monkeypatch.setattr(db.command, "upgrade", broken)
    with pytest.raises(ValueError, match="relationship"):
        Library(directory)
    with sqlite3.connect(directory / "catalog.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM asset").fetchone() == (1,)
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='failed_migration'"
        ).fetchall()
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    monkeypatch.setattr(db.command, "upgrade", original)
    reopened = Library(directory)
    try:
        with pytest.raises(IntegrityError), reopened.engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM asset")
    finally:
        reopened.close()


def test_equivalent_path_spellings_and_internal_symlinks_share_identity(source_client):
    client, source = source_client
    first = register(client, ["Disc 1/01.m4b"])
    (source / "alias.m4b").symlink_to(source / "Disc 1/01.m4b")
    assert register(client, ["alias.m4b"])["work"]["id"] == first["work"]["id"]
    for names in (
        ["./Disc 1/01.m4b", "Disc 1/01.m4b"],
        ["alias.m4b", "Disc 1/01.m4b"],
        ["./Disc 1/01.m4b", "Disc 2/01.mp3"],
        ["alias.m4b", "Disc 2/01.mp3"],
    ):
        response = client.post("/api/sources/register", json={"root": "archive", "paths": names})
        assert response.status_code == 422, response.text
    assert client.get("/api/catalog").json()["total"] == 1


def test_pending_set_reserves_paths_and_restarts_without_conflict(source_client, monkeypatch):
    client, source = source_client
    lib = client.app.state.library
    publish = lib._publish
    monkeypatch.setattr(lib, "_publish", lambda _: (_ for _ in ()).throw(OSError("interrupted")))
    assert (
        client.post(
            "/api/sources/register",
            json={"root": "archive", "paths": ["Disc 1/01.m4b", "Disc 2/01.mp3"]},
        ).status_code
        == 409
    )
    monkeypatch.setattr(lib, "_publish", publish)
    response = client.post(
        "/api/sources/register", json={"root": "archive", "paths": ["./Disc 1/01.m4b"]}
    )
    assert response.status_code == 422 and "pending registration" in response.json()["detail"]
    lib.close()
    lib = Library(lib.data_dir, lib.sources)
    client.app.state.library = lib
    assert client.get("/api/catalog").json()["total"] == 1
    with lib.sessions() as session:
        assert session.scalar(select(ImportOperation.state)) == "complete"


def test_historical_conflicting_journal_is_retained_without_blocking_startup(source_client):
    client, _ = source_client
    lib = client.app.state.library
    work = register(client)["work"]
    rep_id = work["editions"][0]["representations"][0]["id"]
    with lib.sessions.begin() as session:
        operation = session.get(ImportOperation, rep_id)
        details = json.loads(operation.extracted_json)
        session.add(
            ImportOperation(
                id="conflicting",
                state="staged",
                sha256=operation.sha256,
                size=operation.size,
                original_name=operation.original_name,
                extracted_json=json.dumps(details),
            )
        )
    stage = lib.staging / "conflicting"
    stage.mkdir()
    lib.close()
    lib = Library(lib.data_dir, lib.sources)
    client.app.state.library = lib
    with lib.sessions() as session:
        operation = session.get(ImportOperation, "conflicting")
        assert operation.state == "error" and "ownership conflict" in operation.error
    assert (lib.managed / "conflicting").is_dir()
    assert lib.get(work["id"]).title == work["title"]


def test_backup_external_declarations_and_legacy_manifest(source_client, tmp_path):
    client, _ = source_client
    register(client)
    external = tmp_path / "external.zip"
    backup(client.app.state.library, external)
    broken = tmp_path / "undeclared.zip"
    with zipfile.ZipFile(external) as source, zipfile.ZipFile(broken, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(content)
                manifest["external_roots"] = {}
                content = json.dumps(manifest).encode()
            target.writestr(name, content)
    with pytest.raises(ValueError, match="declarations"):
        restore(broken, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()
    library = Library(tmp_path / "managed-only")
    try:
        work = library.import_file(FIXTURES / "tone.mp3", "tone.mp3").work
        current = tmp_path / "current.zip"
        backup(library, current)
    finally:
        library.close()
    legacy = tmp_path / "legacy.zip"
    with zipfile.ZipFile(current) as source, zipfile.ZipFile(legacy, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(content)
                manifest["version"] = 1
                del manifest["external_roots"]
                content = json.dumps(manifest).encode()
            target.writestr(name, content)
    restore(legacy, tmp_path / "legacy-restored")
    reopened = Library(tmp_path / "legacy-restored")
    try:
        assert reopened.get(work.id).id == work.id
    finally:
        reopened.close()
