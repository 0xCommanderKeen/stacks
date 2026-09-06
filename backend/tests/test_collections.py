import pytest
from stacks.backup import backup, restore
from stacks.collections import Collections
from stacks.library import Library
from stacks.samples import epub_bytes

from .conftest import upload
from .test_curation import personal, record
from .test_operations import commit, pair, paths, preview
from .test_series_reading import member, series


def create(client, name="Weekend", home=False):
    response = client.post("/api/collections", json={"name": name, "home": home})
    assert response.status_code == 200, response.text
    return response.json()


def change(client, collection, work=None, action="add", **values):
    response = client.post(
        f"/api/collections/{collection['id']}/entries",
        json={
            "revision": collection["revision"],
            "action": action,
            "work_id": work["id"] if work else None,
            **values,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def contents(client, collection, **params):
    response = client.get(f"/api/collections/{collection['id']}/works", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids(client, collection):
    return [e["work"]["id"] for e in contents(client, collection)["items"]]


def test_order_pages_dedupe_revision_and_series(client):
    collection = create(client)
    run = series(client, "2026")
    second = member(client, "Second", run["id"], 2)
    first = member(client, "First", run["id"], 1)
    collection = change(client, collection, action="add_series", series_id=run["id"])
    assert ids(client, collection) == [first["id"], second["id"]]
    collection = change(client, collection, first)
    assert collection["count"] == 2
    old = collection
    collection = change(client, collection, second, "up")
    assert contents(client, collection, limit=1, offset=1)["items"][0]["work"]["id"] == first["id"]
    assert (
        client.post(
            f"/api/collections/{collection['id']}/entries",
            json={"revision": old["revision"], "action": "down", "work_id": second["id"]},
        ).status_code
        == 409
    )
    collection = change(client, collection, second, "remove")
    collection = change(client, collection, second)
    assert ids(client, collection) == [first["id"], second["id"]]
    response = client.patch(
        f"/api/collections/{collection['id']}",
        json={**collection, "name": "Evenings", "home": True},
    )
    assert response.status_code == 200
    assert client.get("/api/collections?q=Even&limit=1").json()["total"] == 1
    assert client.get("/api/collections?offset=1").json()["items"] == []
    assert client.post("/api/collections", json={"name": "  "}).status_code == 422


def test_home_finished_archive_and_restore(client, tmp_path):
    first, second = pair(client)
    collection = change(client, change(client, create(client, home=True), first), second)
    ignored = change(client, create(client, "Not on Home"), second)
    assert ignored["count"] == 1
    next_url = "/api/home/collections"
    assert client.get(next_url).json()["items"][0]["work"]["id"] == first["id"]
    record(client, first)
    assert client.get(next_url).json()["items"][0]["work"]["id"] == second["id"]
    personal(client, second, shelf_override="archive")
    assert client.get(next_url).json()["total"] == 0
    snapshot = client.app.state.library.export()
    assert snapshot["schema_version"] == 12
    archive = tmp_path / "backup.zip"
    backup(client.app.state.library, archive)
    restore(archive, tmp_path / "restored")
    library = Library(tmp_path / "restored")
    try:
        assert library.export()["tables"] == snapshot["tables"]
        assert Collections(library).works(collection["id"]).total == 2
    finally:
        library.close()


@pytest.mark.parametrize("side", ["source", "target"])
def test_group_duplicate_position_and_undo(client, side):
    source, target = pair(client)
    third = upload(client, epub_bytes("Unrelated")).json()["work"]
    collection = create(client)
    for work in (source, third, target):
        collection = change(client, collection, work)
    before = contents(client, collection)["items"]
    originals = paths(client)
    plan = preview(client, source, target)
    key = f"collection:{collection['id']}"
    assert key in {c["field"] for c in plan["conflicts"]}
    resolution = {c["field"]: "target" for c in plan["conflicts"]}
    resolution[key] = side
    response = client.post(f"/api/operations/{plan['id']}/commit", json={"resolutions": resolution})
    assert response.status_code == 200, response.text
    after = contents(client, collection)["items"]
    kept = after[0] if side == "source" else after[1]
    assert kept["id"] == before[0 if side == "source" else 2]["id"]
    assert kept["work"]["id"] == target["id"]
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    restored = contents(client, collection)
    assert [(e["id"], e["position"], e["work"]["id"]) for e in restored["items"]] == [
        (e["id"], e["position"], e["work"]["id"]) for e in before
    ]
    assert restored["collection"]["revision"] > collection["revision"] + 1
    assert paths(client) == originals


def test_collection_later_edit_guards_preview_and_undo(client):
    source, target = pair(client)
    other = upload(client, epub_bytes("Another")).json()["work"]
    collection = change(client, change(client, create(client), source), other)
    plan = preview(client, source, target)
    collection = change(client, collection, other, "up")
    assert client.post(f"/api/operations/{plan['id']}/commit", json={}).status_code == 409
    plan = preview(client, source, target)
    commit(client, plan)
    collection = contents(client, collection)["collection"]
    change(client, collection, other, "down")
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 409


def test_split_and_undo_chain_preserve_unrelated_entries(client):
    source, target = pair(client)
    other = upload(client, epub_bytes("Unrelated")).json()["work"]
    collection = change(client, change(client, create(client), source), other)
    original = ids(client, collection)
    grouped = preview(client, source, target)
    commit(client, grouped)
    work = client.get(f"/api/works/{target['id']}").json()
    split = preview(
        client,
        work,
        mode="split",
        representation_id=source["editions"][0]["representations"][0]["id"],
    )
    result = commit(client, split)
    assert ids(client, collection) == [target["id"], other["id"], result["work_ids"][1]]
    assert client.post(f"/api/operations/{split['id']}/undo").status_code == 200
    assert client.post(f"/api/operations/{grouped['id']}/undo").status_code == 200
    assert ids(client, collection) == original


def test_partial_format_attachment_copies_membership_at_end(client):
    source, target = pair(client)
    extra = upload(client, epub_bytes("Extra edition")).json()["work"]
    commit(client, preview(client, extra, source))
    other = upload(client, epub_bytes("Between them")).json()["work"]
    collection = change(client, change(client, create(client), source), other)
    target = client.patch(
        f"/api/works/{target['id']}",
        json={
            **target,
            "editions": [
                {**target["editions"][0], "language": "", "identifier": "", "publisher": ""}
            ],
        },
    ).json()
    source = client.get(f"/api/works/{source['id']}").json()
    plan = preview(
        client,
        source,
        target,
        mode="representation",
        representation_id=source["editions"][0]["representations"][0]["id"],
        target_edition_id=target["editions"][0]["id"],
    )
    assert not any(c["field"].startswith("collection:") for c in plan["conflicts"])
    commit(client, plan)
    assert ids(client, collection) == [source["id"], other["id"], target["id"]]
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    assert ids(client, collection) == [source["id"], other["id"]]
