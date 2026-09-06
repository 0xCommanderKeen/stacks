import hashlib
import io

import pytest
from PIL import Image
from stacks.backup import backup, restore
from stacks.covers import Covers
from stacks.library import Library
from stacks.models import CoverBlob
from stacks.samples import epub_bytes
from stacks.schemas import TrashRequest
from stacks.trash import Trash

from .conftest import upload
from .test_devices import issue
from .test_operations import pair, preview


def picture(color="red"):
    out = io.BytesIO()
    Image.new("RGB", (80, 120), color).save(out, "PNG")
    return out.getvalue()


def choose(client, work, color="red"):
    response = client.post(
        f"/api/works/{work['id']}/cover?revision={work['revision']}", content=picture(color)
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_chosen_cover_original_backup_export_and_reset(client, tmp_path):
    work = upload(client, epub_bytes("Chosen cover")).json()["work"]
    embedded = client.get(f"/api/works/{work['id']}/cover").content
    selected = choose(client, work)
    assert selected["selected_cover_id"] and selected["revision"] == work["revision"] + 1
    assert client.get(f"/api/works/{work['id']}/cover").content != embedded
    original = client.get(f"/api/works/{work['id']}/cover/original")
    assert original.content == picture() and original.headers["content-type"] == "image/png"
    library = client.app.state.library
    with library.sessions() as session:
        blob = session.get(CoverBlob, selected["selected_cover_id"])
        assert blob.origin == "manual" and blob.sha256 == hashlib.sha256(picture()).hexdigest()
    exported = library.export()
    assert exported["tables"]["cover_blob"][0]["id"] == selected["selected_cover_id"]
    archive = tmp_path / "backup.zip"
    backup(library, archive)
    restore(archive, tmp_path / "restored")
    restored = Library(tmp_path / "restored")
    try:
        assert Covers(restored).original(work["id"])[0].read_bytes() == picture()
        assert restored.get(work["id"]).selected_cover_id == selected["selected_cover_id"]
    finally:
        restored.close()
    reset = client.delete(f"/api/works/{work['id']}/cover?revision={selected['revision']}")
    assert reset.status_code == 200 and reset.json()["selected_cover_id"] is None
    assert client.get(f"/api/works/{work['id']}/cover").content == embedded
    assert (
        library.resolve(f".covers/{selected['selected_cover_id']}/original").read_bytes()
        == picture()
    )


@pytest.mark.parametrize("failure_at", [1, 2, 3])
def test_bad_image_stale_choice_and_publication_failure_do_not_replace_cover(
    client, monkeypatch, failure_at
):
    work = choose(client, upload(client, epub_bytes("Guarded cover")).json()["work"])
    url = f"/api/works/{work['id']}/cover"
    assert client.post(f"{url}?revision={work['revision']}", content=b"invalid").status_code == 422
    assert (
        client.post(f"{url}?revision={work['revision'] - 1}", content=picture()).status_code == 409
    )

    from stacks.covers import sync_dir

    calls = 0

    def fail(*args):
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise OSError("disk full")
        return sync_dir(*args)

    monkeypatch.setattr("stacks.covers.sync_dir", fail)
    assert (
        client.post(f"{url}?revision={work['revision']}", content=picture("blue")).status_code
        == 503
    )
    assert (
        client.get(f"/api/works/{work['id']}").json()["selected_cover_id"]
        == work["selected_cover_id"]
    )
    assert client.get(f"{url}/original").content == picture()


def test_group_cover_conflict_split_and_undo_preserve_choices(client):
    source, target = pair(client)
    source, target = choose(client, source), choose(client, target, "blue")
    plan = preview(client, source, target)
    assert "selected_cover_id" in {c["field"] for c in plan["conflicts"]}
    merged = client.post(
        f"/api/operations/{plan['id']}/commit",
        json={"resolutions": {c["field"]: "source" for c in plan["conflicts"]}},
    )
    assert merged.status_code == 200, merged.text
    work = client.get(f"/api/works/{target['id']}").json()
    assert work["selected_cover_id"] == source["selected_cover_id"]
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    assert (
        client.get(f"/api/works/{target['id']}").json()["selected_cover_id"]
        == target["selected_cover_id"]
    )
    # Re-group, split a representation, and retain the selected source cover on both works.
    source = client.get(f"/api/works/{source['id']}").json()
    target = client.get(f"/api/works/{target['id']}").json()
    plan = preview(client, source, target)
    assert (
        client.post(
            f"/api/operations/{plan['id']}/commit",
            json={"resolutions": {c["field"]: "source" for c in plan["conflicts"]}},
        ).status_code
        == 200
    )
    target = client.get(f"/api/works/{target['id']}").json()
    split = preview(
        client,
        target,
        mode="split",
        representation_id=target["editions"][0]["representations"][0]["id"],
    )
    response = client.post(f"/api/operations/{split['id']}/commit", json={"resolutions": {}})
    assert response.status_code == 200, response.text
    assert all(
        item["selected_cover_id"] == source["selected_cover_id"]
        for item in client.get("/api/catalog").json()["items"]
    )


def test_cover_survives_trash_and_scoped_opds_hides_it(client):
    work = choose(client, upload(client, epub_bytes("Trash cover")).json()["work"])
    _, auth = issue(client, "all")
    url = f"/opds/works/{work['id']}/cover"
    assert (
        client.get(url, auth=auth).content == client.get(f"/api/works/{work['id']}/cover").content
    )
    library = client.app.state.library
    trash = Trash(library)
    trash.request(work["id"], TrashRequest(revision=work["revision"], action="trash"))
    while trash.step():
        pass
    assert client.get(url, auth=auth).status_code == 404
    hidden = library.get(work["id"])
    with pytest.raises(ValueError, match="Restore"):
        Covers(library).reset(work["id"], hidden.revision)
    trash.request(work["id"], TrashRequest(revision=hidden.revision, action="restore"))
    while trash.step():
        pass
    assert client.get(url, auth=auth).status_code == 200
    assert Covers(library).original(work["id"])[0].read_bytes() == picture()


def test_cover_upload_limit_and_later_choice_block_stale_undo(client):
    source, target = pair(client)
    plan = preview(client, source, target)
    assert (
        client.post(
            f"/api/operations/{plan['id']}/commit",
            json={"resolutions": {c["field"]: "target" for c in plan["conflicts"]}},
        ).status_code
        == 200
    )
    target = client.get(f"/api/works/{target['id']}").json()
    target = choose(client, target)
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 409
    assert (
        client.post(
            f"/api/works/{target['id']}/cover?revision={target['revision']}",
            content=b"x" * (10 * 1024**2 + 1),
        ).status_code
        == 413
    )
