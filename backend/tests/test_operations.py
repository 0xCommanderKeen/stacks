from sqlalchemy import select
from stacks.models import Asset
from stacks.samples import epub_bytes

from .conftest import upload
from .test_formats import FIXTURES, pdf_bytes


def pair(client):
    return (
        upload(client, epub_bytes("Shared Work")).json()["work"],
        upload(client, pdf_bytes(), "book.pdf").json()["work"],
    )


def preview(client, source, target=None, **kwargs):
    response = client.post(
        "/api/operations/preview",
        json={
            "mode": "editions",
            "source_work_id": source["id"],
            "target_work_id": target["id"] if target else None,
            **kwargs,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def commit(client, plan):
    response = client.post(
        f"/api/operations/{plan['id']}/commit",
        json={"resolutions": {c["field"]: "target" for c in plan["conflicts"]}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def paths(client):
    lib = client.app.state.library
    with lib.sessions() as session:
        return {
            a.id: (a.relative_path, lib.resolve(a.relative_path).read_bytes())
            for a in session.scalars(select(Asset))
        }


def test_group_preserves_editions_redirects_originals_and_undo(client):
    source, target = pair(client)
    originals = paths(client)
    plan = preview(client, source, target)
    assert {c["field"] for c in plan["conflicts"]} >= {"title", "authors"}
    assert client.post(f"/api/operations/{plan['id']}/commit", json={}).status_code == 409
    commit(client, plan)
    assert client.get("/api/catalog").json()["total"] == 1
    merged = client.get(f"/api/works/{source['id']}").json()
    assert merged["id"] == target["id"] and len(merged["editions"]) == 2
    assert paths(client) == originals
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    assert client.get("/api/catalog").json()["total"] == 2
    assert client.get(f"/api/works/{source['id']}").json()["title"] == source["title"]
    assert paths(client) == originals
    # Both directions are idempotent, but an undone preview cannot be committed again.
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    assert client.post(f"/api/operations/{plan['id']}/commit", json={}).status_code == 409


def test_same_edition_formats_and_split_keep_representation_ids(client):
    source, target = pair(client)
    # Unknown edition values can be supplemented; conflicting identifiers stay separate.
    edit = {
        "revision": 1,
        "title": target["title"],
        "authors": target["authors"],
        "description": target["description"],
        "editions": [
            {"id": target["editions"][0]["id"], "language": "", "publisher": "", "identifier": ""}
        ],
    }
    target = client.patch(f"/api/works/{target['id']}", json=edit).json()
    rep = source["editions"][0]["representations"][0]
    plan = preview(
        client,
        source,
        target,
        mode="representation",
        representation_id=rep["id"],
        target_edition_id=target["editions"][0]["id"],
    )
    commit(client, plan)
    grouped = client.get(f"/api/works/{target['id']}").json()
    assert len(grouped["editions"]) == 1
    assert grouped["editions"][0]["language"] == source["editions"][0]["language"]
    assert len(grouped["editions"][0]["representations"]) == 2
    split = preview(client, grouped, mode="split", representation_id=rep["id"])
    result = commit(client, split)
    separate = client.get(f"/api/works/{result['work_ids'][1]}").json()
    assert separate["editions"][0]["representations"][0]["id"] == rep["id"]
    assert client.get("/api/catalog").json()["total"] == 2
    assert client.post(f"/api/operations/{split['id']}/undo").status_code == 200
    assert (
        len(client.get(f"/api/works/{target['id']}").json()["editions"][0]["representations"]) == 2
    )


def test_preview_and_undo_refuse_newer_metadata(client):
    source, target = pair(client)
    plan = preview(client, source, target)
    edit = {"revision": 1, "title": "Changed elsewhere", "authors": [], "description": "New note"}
    assert client.patch(f"/api/works/{target['id']}", json=edit).status_code == 200
    assert client.post(f"/api/operations/{plan['id']}/commit", json={}).status_code == 409
    plan = preview(client, source, client.get(f"/api/works/{target['id']}").json())
    commit(client, plan)
    current = client.get(f"/api/works/{target['id']}").json()
    edit.update(revision=current["revision"], title="Edited after grouping")
    client.patch(f"/api/works/{target['id']}", json=edit)
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 409
    assert client.get(f"/api/works/{target['id']}").json()["title"] == "Edited after grouping"


def test_distinct_narrations_cannot_be_collapsed(client):
    source = upload(client, (FIXTURES / "tone.mp3").read_bytes(), "one.mp3").json()["work"]
    target = upload(client, (FIXTURES / "tone.m4a").read_bytes(), "two.m4a").json()["work"]
    for work, narrator in [(source, "Reader One"), (target, "Reader Two")]:
        edition = work["editions"][0]
        response = client.patch(
            f"/api/works/{work['id']}",
            json={
                "revision": 1,
                "title": work["title"],
                "authors": work["authors"],
                "description": work["description"],
                "editions": [
                    {
                        "id": edition["id"],
                        "language": "en",
                        "publisher": "",
                        "identifier": "",
                        "narrator": narrator,
                    }
                ],
            },
        )
        assert response.status_code == 200
    response = client.post(
        "/api/operations/preview",
        json={
            "mode": "representation",
            "source_work_id": source["id"],
            "target_work_id": target["id"],
            "representation_id": source["editions"][0]["representations"][0]["id"],
            "target_edition_id": target["editions"][0]["id"],
        },
    )
    assert response.status_code == 409 and "narrator" in response.text
    plan = preview(client, source, target)
    commit(client, plan)
    editions = client.get(f"/api/works/{target['id']}").json()["editions"]
    assert {e["narrator"] for e in editions} == {"Reader One", "Reader Two"}


def test_backup_preserves_grouping_undo_and_duplicate_redirect(client, tmp_path):
    from stacks.backup import backup, restore
    from stacks.library import Library
    from stacks.operations import CatalogOperations

    source, target = pair(client)
    plan = preview(client, source, target)
    commit(client, plan)
    asset_id = source["editions"][0]["representations"][0]["assets"][0]["id"]
    original = client.get(f"/api/assets/{asset_id}/download").content
    duplicate = upload(client, original).json()
    assert duplicate["duplicate"] and duplicate["work"]["id"] == target["id"]
    archive = tmp_path / "snapshot.zip"
    backup(client.app.state.library, archive)
    restore(archive, tmp_path / "restored")
    lib = Library(tmp_path / "restored")
    try:
        before_revision = lib.get(target["id"]).revision
        CatalogOperations(lib).undo(plan["id"])
        assert lib.list().total == 2
        assert lib.get(target["id"]).revision > before_revision
        assert lib.export()["tables"]["catalog_operation"][0]["state"] == "undone"
    finally:
        lib.close()


def test_interrupted_group_transaction_is_retryable(client, monkeypatch):
    import pytest
    from stacks.operations import CatalogOperations

    source, target = pair(client)
    originals = paths(client)
    plan = preview(client, source, target)
    apply = CatalogOperations._group

    def interrupted(self, session, data, resolutions):
        apply(self, session, data, resolutions)
        raise RuntimeError("interrupted before commit")

    monkeypatch.setattr(CatalogOperations, "_group", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        commit(client, plan)
    assert client.get("/api/catalog").json()["total"] == 2
    assert paths(client) == originals
    monkeypatch.setattr(CatalogOperations, "_group", apply)
    commit(client, plan)
    assert client.get("/api/catalog").json()["total"] == 1


def test_shared_series_conflict_requires_explicit_resolution(client):
    source, target = pair(client)
    series = client.post("/api/series", json={"name": "Rooms", "run": "2024"}).json()
    for work, label in [(source, "Annual"), (target, "Special")]:
        response = client.patch(
            f"/api/works/{work['id']}",
            json={
                "revision": 1,
                "title": work["title"],
                "authors": work["authors"],
                "description": work["description"],
                "memberships": [{"series_id": series["id"], "designation": label, "position": 2}],
            },
        )
        assert response.status_code == 200
    plan = preview(client, source, target)
    key = f"series:{series['id']}"
    assert key in {c["field"] for c in plan["conflicts"]}
    choices = {c["field"]: "target" for c in plan["conflicts"]}
    choices[key] = "source"
    result = client.post(f"/api/operations/{plan['id']}/commit", json={"resolutions": choices})
    assert result.status_code == 200
    assert (
        client.get(f"/api/works/{target['id']}").json()["memberships"][0]["designation"] == "Annual"
    )
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    assert (
        client.get(f"/api/works/{target['id']}").json()["memberships"][0]["designation"]
        == "Special"
    )
