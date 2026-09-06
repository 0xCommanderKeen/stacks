from stacks.models import PersonalState
from stacks.samples import epub_bytes

from .conftest import upload
from .test_curation import personal, record


def series(client, run):
    response = client.post("/api/series", json={"name": "A Shared Name", "run": run})
    assert response.status_code == 200, response.text
    return response.json()


def member(client, name, series_id, position, designation=""):
    work = upload(client, epub_bytes(name)).json()["work"]
    return assign(client, work, series_id, position, designation)


def assign(client, work, series_id, position, designation=""):
    response = client.patch(
        f"/api/works/{work['id']}",
        json={
            **work,
            "memberships": [
                {"series_id": series_id, "position": position, "designation": designation}
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def follow(client, series, value=True):
    response = client.patch(
        f"/api/series/{series['id']}/following",
        json={"revision": series["revision"], "following": value},
    )
    assert response.status_code == 200, response.text
    return response.json()


def archive_default(client, work):
    with client.app.state.library.sessions.begin() as session:
        state = session.get(PersonalState, work["id"])
        if state is None:
            state = PersonalState(work_id=work["id"])
            session.add(state)
        state.default_shelf = "archive"


def test_follow_promotes_defaults_preserves_choices_and_unfollow(client):
    run = series(client, "1999")
    one = member(client, "First", run["id"], 1)
    two = member(client, "Second", run["id"], 2)
    archive_default(client, one)
    archive_default(client, two)
    two = personal(client, two, shelf_override="archive")
    old_revision = run["revision"]
    run = follow(client, run)
    assert client.get(f"/api/works/{one['id']}").json()["personal"]["shelf"] == "library"
    assert client.get(f"/api/works/{two['id']}").json()["personal"]["shelf"] == "archive"
    assert (
        client.patch(
            f"/api/series/{run['id']}/following",
            json={"revision": old_revision, "following": False},
        ).status_code
        == 409
    )
    future = upload(client, epub_bytes("Future member")).json()["work"]
    archive_default(client, future)
    future = assign(client, future, run["id"], 3)
    assert future["personal"]["default_shelf"] == "library"
    run = follow(client, run, False)
    assert not run["following"]
    assert client.get(f"/api/works/{one['id']}").json()["personal"]["shelf"] == "library"
    after = upload(client, epub_bytes("After unfollow")).json()["work"]
    archive_default(client, after)
    assert assign(client, after, run["id"], 4)["personal"]["shelf"] == "archive"
    assert client.app.state.library.export()["tables"]["series"][0]["following"] is False


def test_distinct_runs_ordering_sql_paging_and_next_unfinished(client):
    old, new = series(client, "1999"), series(client, "2026")
    annual = member(client, "Annual", old["id"], 1.5, "Annual 1")
    last = member(client, "Last", old["id"], 2, "Special")
    first = member(client, "First", old["id"], 1, "#1")
    another = member(client, "Another run", new["id"], 1, "#1")
    follow(client, old)
    follow(client, new)
    browse = client.get("/api/browse/series?q=Shared&medium=ebook&limit=1").json()
    assert browse["total"] == 2 and len(browse["items"]) == 1
    assert client.get("/api/browse/series?medium=comic").json()["total"] == 0
    assert (
        client.get(f"/api/series/{old['id']}/works?limit=1&offset=1").json()["items"][0]["id"]
        == annual["id"]
    )
    next_url = "/api/home/next"
    response = client.get(next_url)
    assert response.status_code == 200, response.text
    assert {item["work"]["id"] for item in response.json()["items"]} == {first["id"], another["id"]}
    record(client, first)
    assert client.get(next_url + "?limit=1").json()["items"][0]["work"]["id"] == annual["id"]
    personal(client, annual, shelf_override="archive")
    assert client.get(next_url + "?limit=1").json()["items"][0]["work"]["id"] == last["id"]
    record(client, last, finished=None)
    assert client.get(next_url + "?limit=1").json()["items"][0]["work"]["id"] == last["id"]
    record(client, last, kind="listen")
    page = client.get(next_url + "?limit=1&offset=1").json()
    assert page["total"] == 1 and page["items"] == []
    browse = client.get("/api/browse/series?scope=library").json()
    assert browse["items"][0]["owned"] == 2 and browse["items"][0]["finished"] == 2


def test_media_unassigned_and_following_backup(client, tmp_path):
    from stacks.backup import backup, restore
    from stacks.library import Library
    from stacks.series import SeriesCatalog

    from .test_formats import comic_bytes

    run = series(client, "2026")
    assigned = upload(client, comic_bytes("cbz"), "comic.cbz").json()["work"]
    assigned = assign(client, assigned, run["id"], 1, "Annual 2024")
    ebook = upload(client, epub_bytes("No series")).json()["work"]
    assert client.get("/api/catalog?medium=comic").json()["items"][0]["id"] == assigned["id"]
    assert client.get("/api/catalog?medium=comic&unassigned=true").json()["total"] == 0
    assert (
        client.get("/api/catalog?medium=ebook&unassigned=true").json()["items"][0]["id"]
        == ebook["id"]
    )
    record(client, assigned)
    page = client.get(f"/api/series/{run['id']}/works?limit=1").json()
    assert page["finished_work_ids"] == [assigned["id"]]
    assert (
        client.get(f"/api/series/{run['id']}/works?limit=1&offset=1").json()["finished_work_ids"]
        == []
    )
    follow(client, run)
    archive = tmp_path / "backup.zip"
    backup(client.app.state.library, archive)
    restore(archive, tmp_path / "restored")
    library = Library(tmp_path / "restored")
    try:
        assert SeriesCatalog(library).get(run["id"]).following is True
        assert library.export()["schema_version"] == 9
    finally:
        library.close()


def test_grouping_respects_deliberate_shelf_resolution_and_follow_defaults(client):
    from .test_operations import commit, preview

    run = series(client, "1999")
    source = member(client, "Series issue", run["id"], 1)
    target = upload(client, epub_bytes("Alternate format")).json()["work"]
    follow(client, run)
    # An explicit Archive choice must survive a grouped followed membership.
    target = personal(client, target, shelf_override="archive")
    plan = preview(client, source, target)
    commit(client, plan)
    grouped = client.get(f"/api/works/{target['id']}").json()
    assert grouped["personal"]["shelf"] == "archive"
    assert grouped["memberships"][0]["series"]["following"] is True
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
