from concurrent.futures import ThreadPoolExecutor

import pytest
from stacks.backup import backup, restore
from stacks.library import Library
from stacks.models import Asset
from stacks.operations import CatalogOperations
from stacks.reading import Reading
from stacks.schemas import GroupRequest, ProgressEdit

from .conftest import upload
from .test_formats import FIXTURES


def audiobook(client):
    response = upload(client, (FIXTURES / "listening.m4b").read_bytes(), "listening.m4b")
    assert response.status_code == 200, response.text
    work = response.json()["work"]
    rep = work["editions"][0]["representations"][0]
    return work, rep, rep["assets"][0]


def test_authenticated_range_stream_and_chapters(client):
    _, rep, asset = audiobook(client)
    playback = client.get(f"/api/representations/{rep['id']}/playback").json()
    assert [c["title"] for c in playback["tracks"][0]["chapters"]] == ["First Room", "Second Room"]
    assert playback["tracks"][0]["chapters"][1]["start"] == 10
    original = (FIXTURES / "listening.m4b").read_bytes()
    response = client.get(f"/api/assets/{asset['id']}/stream", headers={"Range": "bytes=10-99"})
    assert response.status_code == 206 and response.content == original[10:100]
    assert response.headers["content-range"] == f"bytes 10-99/{len(original)}"
    assert response.headers["content-type"] == "audio/mp4"
    assert client.head(f"/api/assets/{asset['id']}/stream").headers["content-length"] == str(
        len(original)
    )
    assert (
        client.get(
            f"/api/assets/{asset['id']}/stream", headers={"Range": "bytes=9999999-"}
        ).status_code
        == 416
    )
    client.cookies.clear()
    assert client.get(f"/api/assets/{asset['id']}/stream").status_code == 401


def test_resume_revision_backward_seek_and_restore(client, tmp_path):
    _, rep, asset = audiobook(client)
    url = f"/api/representations/{rep['id']}/progress"
    edit = {"revision": 0, "asset_id": asset["id"], "position": 12, "speed": 1.5}
    one = client.patch(url, json=edit)
    assert one.status_code == 200, one.text
    assert one.json()["revision"] == 1
    assert client.patch(url, json={**edit, "position": 19}).status_code == 409
    back = client.patch(url, json={**edit, "revision": 1, "position": 3})
    assert back.status_code == 200 and back.json()["position"] == 3
    assert client.patch(url, json={**edit, "revision": 2, "asset_id": "other"}).status_code == 409
    archive = tmp_path / "backup.zip"
    backup(client.app.state.library, archive)
    restore(archive, tmp_path / "restored")
    lib = Library(tmp_path / "restored")
    try:
        progress = Reading(lib).playback(rep["id"]).progress
        assert (progress.position, progress.speed, progress.revision) == (3, 1.5, 2)
        assert Reading(lib).continue_list().total == 1
        assert lib.export()["tables"]["progress"][0]["asset_id"] == asset["id"]
    finally:
        lib.close()


def test_concurrent_devices_have_one_winner(client):
    _, rep, asset = audiobook(client)
    reading = Reading(client.app.state.library)

    def update(position):
        try:
            return reading.update(
                rep["id"], ProgressEdit(revision=0, asset_id=asset["id"], position=position)
            ).revision
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(update, [2, 10]))
    assert sorted(results, key=str) == [1, "conflict"]


def test_multitrack_order_completion_and_missing_asset(client):
    lib = client.app.state.library
    result = lib.import_files(
        [(FIXTURES / "tone.mp3", "Disc 2/1.mp3"), (FIXTURES / "listening.m4b", "Disc 1/1.m4b")]
    )
    rep = result.work.editions[0].representations[0]
    reading = Reading(lib)
    playback = reading.playback(rep.id)
    assert [t.original_name for t in playback.tracks] == ["Disc 1/1.m4b", "Disc 2/1.mp3"]
    first, last = playback.tracks
    with pytest.raises(ValueError, match="last track"):
        reading.update(
            rep.id,
            ProgressEdit(
                revision=0, asset_id=first.asset_id, position=first.duration, completed=True
            ),
        )
    progress = reading.update(
        rep.id,
        ProgressEdit(revision=0, asset_id=last.asset_id, position=last.duration, completed=True),
    )
    assert reading.continue_list().total == 0
    reading.update(
        rep.id,
        ProgressEdit(
            revision=progress.revision, asset_id=first.asset_id, position=0, completed=False
        ),
    )
    assert reading.continue_list().total == 1
    with lib.sessions() as session:
        asset = session.get(Asset, last.asset_id)
        lib.resolve(asset.relative_path).unlink()
    assert client.get(f"/api/assets/{last.asset_id}/stream").status_code == 409
    assert reading.playback(rep.id).progress.asset_id == first.asset_id


def test_grouping_and_undo_do_not_rewind_progress(client):
    source, rep, asset = audiobook(client)
    target = upload(client, (FIXTURES / "tone.mp3").read_bytes(), "other.mp3").json()["work"]
    lib = client.app.state.library
    reading = Reading(lib)
    ops = CatalogOperations(lib)
    plan = ops.preview(
        GroupRequest(mode="editions", source_work_id=source["id"], target_work_id=target["id"])
    )
    ops.commit(plan.id, {c.field: "target" for c in plan.conflicts})
    reading.update(rep["id"], ProgressEdit(revision=0, asset_id=asset["id"], position=12))
    assert reading.continue_list().items[0].work.id == target["id"]
    split = ops.preview(
        GroupRequest(mode="split", source_work_id=target["id"], representation_id=rep["id"])
    )
    result = ops.commit(split.id, {})
    assert reading.playback(rep["id"]).work_id == result.work_ids[1]
    reading.update(rep["id"], ProgressEdit(revision=1, asset_id=asset["id"], position=15))
    ops.undo(split.id)
    ops.undo(plan.id)
    saved = reading.playback(rep["id"])
    assert (
        saved.work_id == source["id"]
        and saved.progress.position == 15
        and saved.progress.revision == 2
    )
