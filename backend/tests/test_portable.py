import json
import shutil

import pytest
from stacks.library import Library
from stacks.portable import import_catalog, write_catalog
from stacks.samples import epub_bytes
from stacks.schemas import WorkEdit

from .conftest import upload
from .test_covers import choose


def test_portable_api_roundtrip_retains_corrections_and_cover_identity(client, tmp_path):
    original = upload(client, epub_bytes("Portable story")).json()["work"]
    work = choose(client, original)
    lib = client.app.state.library
    lib.edit(
        work["id"],
        WorkEdit(
            revision=work["revision"],
            title="My own title",
            authors=["My author"],
            description="My description",
        ),
    )
    response = client.get("/api/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["format_version"] == 1
    assert not {"login_session", "device_credential"} & payload["tables"].keys()
    path = tmp_path / "catalog.json"
    path.write_bytes(response.content)
    destination = tmp_path / "fresh"
    with pytest.raises(ValueError, match="omits"):
        import_catalog(path, destination)
    import_catalog(path, destination, allow_missing_originals=True)
    # Original storage is restored separately, retaining all relative paths.
    shutil.copytree(lib.managed, destination / "managed", dirs_exist_ok=True)
    restored = Library(destination)
    try:
        returned = restored.get(work["id"])
        assert returned.title == "My own title"
        assert returned.selected_cover_id == work["selected_cover_id"]
        second = tmp_path / "second.json"
        write_catalog(restored, second)
        assert json.loads(second.read_text())["tables"] == payload["tables"]
    finally:
        restored.close()


@pytest.mark.parametrize(
    "damage", ["version", "path", "relationship", "duplicate", "truncated", "authority"]
)
def test_bad_portable_catalog_never_publishes_a_directory(client, tmp_path, damage):
    upload(client, epub_bytes("Protected import"))
    document = client.get("/api/export").json()
    if damage == "version":
        document["format_version"] = 999
    elif damage == "path":
        document["tables"]["asset"][0]["relative_path"] = "../outside.epub"
    elif damage == "relationship":
        document["tables"]["credit"][0]["contributor_id"] = "00000000-0000-0000-0000-000000000000"
    elif damage == "duplicate":
        document["tables"]["work"].append(document["tables"]["work"][0])
    elif damage == "authority":
        document["tables"]["device_credential"] = []
    data = json.dumps(document)
    if damage == "truncated":
        data = data[:-5]
    source = tmp_path / "bad.json"
    source.write_text(data)
    destination = tmp_path / "fresh"
    with pytest.raises(ValueError):
        import_catalog(source, destination, allow_missing_originals=True)
    assert not destination.exists()
    assert not list(tmp_path.glob(".stacks-catalog-*"))


def test_import_rejects_existing_destination_even_when_empty(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        import_catalog(tmp_path / "unused.json", destination, allow_missing_originals=True)
    assert destination.is_dir()


def test_roundtrip_preserves_group_undo_collections_multitrack_and_trash(client, tmp_path):
    from stacks.collections import Collections
    from stacks.operations import CatalogOperations
    from stacks.reading import Reading
    from stacks.schemas import ProgressEdit, TrashRequest
    from stacks.trash import Trash

    from .test_collections import change, create
    from .test_curation import personal, record
    from .test_formats import FIXTURES
    from .test_operations import commit, pair, preview

    source, target = pair(client)
    source = personal(client, source, notes="Keep my notes", rating=5, tags=["portable"])
    saved_record = record(client, source)
    collection = change(client, change(client, create(client), source), target)
    plan = preview(client, source, target)
    commit(client, plan)
    library = client.app.state.library
    audio = library.import_files(
        [(FIXTURES / "tone.mp3", "Disc 1/01.mp3"), (FIXTURES / "listening.m4b", "Disc 2/02.m4b")]
    )
    rep = audio.work.editions[0].representations[0]
    track = rep.assets[1]
    Reading(library).update(
        rep.id, ProgressEdit(revision=0, asset_id=track.id, position=12, speed=1.5)
    )
    removed = upload(client, epub_bytes("Still in Trash")).json()["work"]
    trash = Trash(library)
    trash.request(removed["id"], TrashRequest(revision=removed["revision"], action="trash"))
    while trash.step():
        pass
    output = tmp_path / "catalog.json"
    write_catalog(library, output)
    destination = tmp_path / "fresh"
    import_catalog(output, destination, allow_missing_originals=True)
    shutil.copytree(library.managed, destination / "managed", dirs_exist_ok=True)
    restored = Library(destination)
    try:
        playback = Reading(restored).playback(rep.id)
        assert [item.asset_id for item in playback.tracks] == [item.id for item in rep.assets]
        assert (
            playback.progress.asset_id,
            playback.progress.position,
            playback.progress.speed,
        ) == (track.id, 12, 1.5)
        assert restored.get(removed["id"]).trashed_at
        CatalogOperations(restored).undo(plan["id"])
        assert restored.get(source["id"]).personal.notes == "Keep my notes"
        assert [item.work.id for item in Collections(restored).works(collection["id"]).items] == [
            source["id"],
            target["id"],
        ]
        assert restored.export()["tables"]["reading_record"][0]["id"] == saved_record["id"]
        hidden = restored.get(removed["id"])
        restored_trash = Trash(restored)
        restored_trash.request(hidden.id, TrashRequest(revision=hidden.revision, action="restore"))
        while restored_trash.step():
            pass
        assert not restored.get(hidden.id).trashed_at
    finally:
        restored.close()


def test_imported_intake_is_stopped_and_external_root_can_be_relocated(tmp_path):
    from stacks.intake import Intake
    from stacks.models import IntakeJob
    from stacks.schemas import ScanRequest

    original = tmp_path / "source"
    original.mkdir()
    (original / "one.epub").write_bytes(epub_bytes("Registered original"))
    library = Library(tmp_path / "data", {"books": original})
    worker = Intake(library, stable_seconds=0)
    try:
        registered = library.register_files("books", ["one.epub"])
        pending = worker.scan(ScanRequest(root="books"))
        output = tmp_path / "catalog.json"
        write_catalog(library, output)
        document = json.loads(output.read_text())
        # JSON object ordering is not part of the portable contract.
        output.write_text(json.dumps(dict(reversed(list(document.items())))))
        destination = tmp_path / "fresh"
        import_catalog(output, destination, allow_missing_originals=True)
        relocated = tmp_path / "relocated"
        original.rename(relocated)
        restored = Library(destination, {"books": relocated})
        restored_worker = Intake(restored, stable_seconds=0)
        try:
            with restored.sessions() as session:
                assert session.get(IntakeJob, pending.id).state == "cancelled"
            assert not restored_worker.step()
            assert restored.get(registered.work.id).id == registered.work.id
            repeated = restored.register_files("books", ["one.epub"])
            assert repeated.duplicate and repeated.work.id == registered.work.id
        finally:
            restored_worker.close()
            restored.close()
    finally:
        worker.close()
        library.close()


def test_export_packaging_leaves_catalog_edits_and_audio_ranges_available(
    client, tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from stacks import portable

    from .test_reading import audiobook

    work, _, asset = audiobook(client)
    entered, release = threading.Event(), threading.Event()
    dump = portable.json.dump

    def slow_dump(value, output, **kwargs):
        entered.set()
        assert release.wait(5)
        return dump(value, output, **kwargs)

    monkeypatch.setattr(portable.json, "dump", slow_dump)
    destination = tmp_path / "catalog.json"
    with ThreadPoolExecutor(max_workers=2) as pool:
        exporting = pool.submit(write_catalog, client.app.state.library, destination)
        try:
            assert entered.wait(5)
            edited = pool.submit(
                client.patch,
                f"/api/works/{work['id']}",
                json={
                    "revision": work["revision"],
                    "title": "Still responsive",
                    "authors": ["A reader"],
                    "description": "",
                },
            ).result(timeout=2)
            assert edited.status_code == 200
            response = pool.submit(
                client.get, f"/api/assets/{asset['id']}/stream", headers={"Range": "bytes=10-99"}
            ).result(timeout=2)
            assert response.status_code == 206 and len(response.content) == 90
        finally:
            release.set()
        exporting.result(timeout=5)
    assert json.loads(destination.read_text())["tables"]["work"][0]["title"] == work["title"]


@pytest.mark.parametrize(
    "damage",
    [
        "membership_position",
        "membership_designation",
        "progress_position",
        "facts_shape",
        "redirect_cycle",
    ],
)
def test_read_invalid_values_are_rejected_before_publication(client, tmp_path, damage):
    from uuid import uuid4

    from .test_reading import audiobook

    work, rep, asset = audiobook(client)
    document = client.get("/api/export").json()
    if damage.startswith("membership"):
        series_id = str(uuid4())
        document["tables"]["series"] = [
            {"id": series_id, "name": "Run", "run": "2026", "following": False, "revision": 1}
        ]
        document["tables"]["series_membership"] = [
            {
                "id": str(uuid4()),
                "series_id": series_id,
                "work_id": work["id"],
                "designation": "x" * 129 if damage.endswith("designation") else "1",
                "position": 1e10 if damage.endswith("position") else 1,
            }
        ]
    elif damage == "progress_position":
        document["tables"]["progress"] = [
            {
                "representation_id": rep["id"],
                "asset_id": asset["id"],
                "position": 1e10,
                "speed": 1.0,
                "completed": False,
                "revision": 1,
                "updated_at": "2026-09-06T00:00:00Z",
            }
        ]
    elif damage == "facts_shape":
        document["tables"]["representation"][0]["extracted_json"] = "[]"
    else:
        document["tables"]["work_redirect"] = [{"source_id": work["id"], "target_id": work["id"]}]
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(document))
    destination = tmp_path / "fresh"
    with pytest.raises(ValueError):
        import_catalog(source, destination, allow_missing_originals=True)
    assert not destination.exists()


@pytest.mark.parametrize("prefix", [b'{"', b'{"value":"'])
@pytest.mark.parametrize("ending", [b'"}', b""])
def test_oversized_keys_and_strings_stop_input_before_complete_allocation(
    monkeypatch, prefix, ending
):
    import io

    import ijson
    from stacks import portable

    monkeypatch.setattr(portable, "MAX_TOKEN", 64)
    source = io.BytesIO(prefix + b"x" * 10000 + ending)
    with pytest.raises(ValueError, match="token exceeds"):
        list(ijson.basic_parse(portable.TokenBoundedInput(source)))
    assert source.tell() <= 130


def test_string_guard_preserves_escaped_quotes_backslashes_and_utf8_at_chunk_boundaries():
    import io

    from stacks.portable import Reader

    class ByteAtATime(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 1) if size >= 0 else 1)

    value = {"quoted": 'A "book" \\ shelf \\"end 📚', "line": "a\nb"}
    assert Reader(ByteAtATime(json.dumps(value, ensure_ascii=False).encode())).value() == value


@pytest.mark.parametrize("ending", [b"}", b""])
def test_numeric_tokens_are_bounded_before_parser_allocation(monkeypatch, ending):
    import io

    import ijson
    from stacks import portable

    monkeypatch.setattr(portable, "MAX_TOKEN", 64)
    source = io.BytesIO(b'{"format_version":' + b"1" * 100000 + ending)
    with pytest.raises(ValueError, match="token exceeds"):
        list(ijson.basic_parse(portable.TokenBoundedInput(source)))
    assert source.tell() <= 130
