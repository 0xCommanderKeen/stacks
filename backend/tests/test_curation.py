from stacks.backup import backup, restore
from stacks.curation import Curation
from stacks.library import Library
from stacks.models import PersonalState

from .test_operations import commit, pair, preview


def personal(client, work, **values):
    response = client.patch(
        f"/api/works/{work['id']}/personal", json={"revision": work["revision"], **values}
    )
    assert response.status_code == 200, response.text
    return response.json()


def record(client, work, representation_id=None, **values):
    response = client.post(
        f"/api/works/{work['id']}/records",
        json={
            "kind": "read",
            "started": "2026-01-02",
            "finished": "2026-02-03",
            "representation_id": representation_id,
            **values,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def records(client, work):
    return client.get(f"/api/works/{work['id']}/records").json()["items"]


def test_shelf_override_notes_tags_stale_and_sql_pages(client):
    source, target = pair(client)
    assert source["personal"]["shelf"] == "library"
    changed = personal(
        client,
        source,
        shelf_override="archive",
        notes="Keep this edition",
        rating=4,
        tags=[" favorite ", "favorite", "summer"],
    )
    assert changed["personal"]["tags"] == ["favorite", "summer"]
    assert (
        client.patch(
            f"/api/works/{source['id']}/personal",
            json={"revision": source["revision"], "notes": "stale"},
        ).status_code
        == 409
    )
    assert client.get("/api/catalog?scope=library").json()["items"][0]["id"] == target["id"]
    assert client.get("/api/catalog?scope=archive&limit=1&offset=1").json() == {
        "items": [],
        "total": 1,
        "limit": 1,
        "offset": 1,
    }
    assert client.get("/api/catalog?scope=wrong").status_code == 422
    reset = personal(client, changed, shelf_override=None)
    assert reset["personal"]["shelf"] == "library"
    # Registered intake will set this base policy; explicit choices take priority.
    lib = client.app.state.library
    with lib.sessions.begin() as session:
        session.get(PersonalState, source["id"]).default_shelf = "archive"
    source = client.get(f"/api/works/{source['id']}").json()
    assert source["personal"]["shelf"] == "archive"
    assert personal(client, source, shelf_override="library")["personal"]["shelf"] == "library"


def test_repeat_records_validation_edit_and_delete(client):
    source, target = pair(client)
    rep = source["editions"][0]["representations"][0]["id"]
    one = record(client, source, rep)
    two = record(client, source, kind="listen", started="2026-03-01", finished=None)
    assert one["id"] != two["id"]
    assert [r["kind"] for r in records(client, source)] == ["listen", "read"]
    url = f"/api/works/{source['id']}/records"
    assert (
        client.post(
            url, json={"kind": "read", "started": "2026-03-01", "finished": "2026-02-01"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            url, json={"kind": "listen", "started": "2026-01-01", "representation_id": rep}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/works/{target['id']}/records",
            json={"kind": "read", "started": "2026-01-01", "representation_id": rep},
        ).status_code
        == 409
    )
    edit = {**two, "finished": "2026-03-05"}
    assert client.patch(f"{url}/{two['id']}", json=edit).json()["revision"] == 2
    assert client.patch(f"{url}/{two['id']}", json=edit).status_code == 409
    assert client.delete(f"{url}/{two['id']}?revision=1").status_code == 409
    assert client.delete(f"{url}/{two['id']}?revision=2").status_code == 204
    assert client.get(f"{url}?limit=1&offset=1").json()["items"] == []


def test_personal_merge_conflicts_and_undo_preserve_history(client, tmp_path):
    source, target = pair(client)
    source = personal(
        client, source, notes="Source memory", rating=5, tags=["source"], shelf_override="archive"
    )
    target = personal(client, target, notes="Target memory", rating=3, tags=["target"])
    saved = record(client, source)
    record(client, target)
    plan = preview(client, source, target)
    assert {c["field"] for c in plan["conflicts"]} >= {
        "personal:notes",
        "personal:rating",
        "personal:tags",
        "personal:shelf",
    }
    result = client.post(
        f"/api/operations/{plan['id']}/commit",
        json={"resolutions": {c["field"]: "source" for c in plan["conflicts"]}},
    )
    assert result.status_code == 200, result.text
    grouped = client.get(f"/api/works/{target['id']}").json()
    assert grouped["personal"] == source["personal"]
    assert len(records(client, target)) == 2
    archive = tmp_path / "backup.zip"
    backup(client.app.state.library, archive)
    restore(archive, tmp_path / "restored")
    with_library = Library(tmp_path / "restored")
    try:
        assert with_library.get(target["id"]).personal.notes == "Source memory"
        assert Curation(with_library).records(target["id"]).total == 2
        assert with_library.export()["schema_version"] == 10
    finally:
        with_library.close()
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    assert client.get(f"/api/works/{target['id']}").json()["personal"] == target["personal"]
    returned = records(client, source)[0]
    assert returned["id"] == saved["id"] and returned["revision"] > saved["revision"]


def test_split_moves_only_format_records_and_later_edits_block_undo(client):
    source, target = pair(client)
    linked = record(client, source, source["editions"][0]["representations"][0]["id"])
    whole = record(client, source)
    grouped = preview(client, source, target)
    commit(client, grouped)
    target = client.get(f"/api/works/{target['id']}").json()
    target = personal(client, target, notes="Shared note", rating=4)
    plan = preview(client, target, mode="split", representation_id=linked["representation_id"])
    committed = commit(client, plan)
    split = client.get(f"/api/works/{committed['work_ids'][1]}").json()
    assert split["personal"] == target["personal"]
    assert [r["id"] for r in records(client, split)] == [linked["id"]]
    assert [r["id"] for r in records(client, target)] == [whole["id"]]
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    plan = preview(client, target, mode="split", representation_id=linked["representation_id"])
    committed = commit(client, plan)
    split = client.get(f"/api/works/{committed['work_ids'][1]}").json()
    personal(client, split, notes="New choice")
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 409


def test_preview_rejects_new_reading_record(client):
    source, target = pair(client)
    plan = preview(client, source, target)
    record(client, source)
    response = client.post(
        f"/api/operations/{plan['id']}/commit",
        json={"resolutions": {c["field"]: "target" for c in plan["conflicts"]}},
    )
    assert response.status_code == 409


def test_old_catalog_history_can_undo_without_overwriting_new_personal_state(client):
    import json

    from stacks.models import CatalogOperation

    source, target = pair(client)
    plan = preview(client, source, target)
    commit(client, plan)
    with client.app.state.library.sessions.begin() as session:
        operation = session.get(CatalogOperation, plan["id"])
        for field in ("before_json", "after_json"):
            snapshot = json.loads(getattr(operation, field))
            snapshot.pop("personal_state")
            snapshot.pop("reading_record")
            setattr(operation, field, json.dumps(snapshot))
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    plan = preview(client, source, target)
    commit(client, plan)
    record(client, target)
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 409
    assert client.get(f"/api/works/{source['id']}/records").status_code == 409
