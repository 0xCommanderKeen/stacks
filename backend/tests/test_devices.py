import json
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import func, select
from stacks.backup import backup, restore
from stacks.curation import Curation
from stacks.library import Library
from stacks.models import DeviceCredential, LoginSession
from stacks.opds import ACQUISITION, ATOM, NAVIGATION, SEARCH
from stacks.samples import epub_bytes
from stacks.schemas import PersonalEdit, WorkEdit

from .conftest import PASSWORD, upload


def issue(client, scope="library", name="My reader"):
    result = client.post("/api/devices", json={"name": name, "scope": scope})
    assert result.status_code == 200, result.text
    value = result.json()
    return value, (value["username"], value["password"])


def links(xml, relation):
    return [node for node in xml.findall(f"{{{ATOM}}}link") if node.get("rel") == relation]


def test_opds_requires_separate_credentials_and_revocation_is_immediate(client):
    assert client.get("/opds").status_code == 401  # Owner cookies are not reader authority.
    assert client.get("/opds", headers={"Authorization": "Basic not-base64"}).status_code == 401
    issued, auth = issue(client)
    assert issued["catalog_url"] == "http://testserver/opds"
    assert client.get("/opds", auth=auth).status_code == 200
    with client.app.state.library.sessions() as session:
        stored = session.scalar(select(DeviceCredential))
        assert stored.digest != issued["password"] and len(stored.digest) == 64
    listed = client.get("/api/devices").json()
    assert "password" not in json.dumps(listed) and "digest" not in json.dumps(listed)
    assert listed["items"][0]["last_used_at"]
    assert client.delete(f"/api/devices/{issued['device']['id']}").status_code == 204
    assert client.get("/opds", auth=auth).status_code == 401
    _, active_auth = issue(client)
    client.cookies.clear()
    for path in ("/api/devices", "/api/export", "/api/catalog", "/api/status"):
        assert client.get(path, auth=active_auth).status_code == 401
    assert client.post("/api/backup", auth=active_auth).status_code == 401
    assert client.post("/api/login", json={"password": active_auth[1]}).status_code == 401
    assert client.get("/opds", auth=("stacks", PASSWORD)).status_code == 401


def test_absolute_navigation_search_paging_and_exact_original_acquisitions(client):
    works = [
        upload(client, epub_bytes(f"Reader title {index}")).json()["work"] for index in range(3)
    ]
    _, auth = issue(client)
    root_response = client.get("https://reader.example/opds", auth=auth)
    assert root_response.headers["content-type"].startswith(NAVIGATION)
    root = ET.fromstring(root_response.content)
    assert links(root, "start")[0].get("href") == "https://reader.example/opds"
    search_url = links(root, "search")[0].get("href")
    search = ET.fromstring(client.get(search_url, auth=auth).content)
    template = search.find(f"{{{SEARCH}}}Url").get("template")
    assert template == "https://reader.example/opds/catalog?q={searchTerms}"
    feed = ET.fromstring(
        client.get("https://reader.example/opds/catalog?q=Reader&limit=2", auth=auth).content
    )
    assert feed.find(f"{{{SEARCH}}}totalResults").text == "3"
    assert len(feed.findall(f"{{{ATOM}}}entry")) == 2
    next_url = links(feed, "next")[0].get("href")
    assert next_url.startswith("https://reader.example/")
    next_feed = ET.fromstring(client.get(next_url, auth=auth).content)
    assert len(next_feed.findall(f"{{{ATOM}}}entry")) == 1
    entry = next_feed.find(f"{{{ATOM}}}entry")
    response = client.get(links(entry, "subsection")[0].get("href"), auth=auth)
    assert response.headers["content-type"].startswith(ACQUISITION)
    originals = ET.fromstring(response.content)
    acquisition = links(originals.find(f"{{{ATOM}}}entry"), "http://opds-spec.org/acquisition")[0]
    assert acquisition.get("type") == "application/epub+zip"
    downloaded = client.get(acquisition.get("href"), auth=auth)
    original = works[0]["editions"][0]["representations"][0]["assets"][0]
    assert downloaded.content == client.get(f"/api/assets/{original['id']}/download").content
    assert downloaded.headers["cache-control"] == "no-store"
    assert client.head(acquisition.get("href"), auth=auth).status_code == 200


def test_scope_applies_to_guessed_work_asset_and_cover_urls_and_trash(client):
    work = upload(client, epub_bytes("Private archive")).json()["work"]
    library = client.app.state.library
    Curation(library).edit(
        work["id"], PersonalEdit(revision=work["revision"], shelf_override="archive")
    )
    _, shelf = issue(client)
    _, all_owned = issue(client, "all")
    representation = work["editions"][0]["representations"][0]
    paths = [
        f"/opds/works/{work['id']}",
        f"/opds/assets/{representation['assets'][0]['id']}",
        f"/opds/covers/{representation['id']}",
    ]
    assert (
        ET.fromstring(client.get("/opds/catalog?q=Private", auth=shelf).content)
        .find(f"{{{SEARCH}}}totalResults")
        .text
        == "0"
    )
    for path in paths:
        assert client.get(path, auth=shelf).status_code == 404
        assert client.get(path, auth=all_owned).status_code == 200
    current = library.get(work["id"])
    assert (
        client.post(
            f"/api/works/{work['id']}/trash", json={"action": "trash", "revision": current.revision}
        ).status_code
        == 200
    )
    for path in paths:
        assert client.get(path, auth=all_owned).status_code == 404


def test_regrouped_original_checks_current_owner_scope(client):
    from .test_operations import commit, pair, preview

    source, target = pair(client)
    representation = source["editions"][0]["representations"][0]
    Curation(client.app.state.library).edit(
        target["id"], PersonalEdit(revision=target["revision"], shelf_override="archive")
    )
    target = client.get(f"/api/works/{target['id']}").json()
    _, auth = issue(client)
    path = f"/opds/assets/{representation['assets'][0]['id']}"
    assert client.get(path, auth=auth).status_code == 200
    commit(client, preview(client, source, target))
    assert client.get(path, auth=auth).status_code == 404


def test_audio_tracks_are_individually_labelled_paged_and_ordered(client):
    library = client.app.state.library
    fixtures = Path(__file__).parent / "fixtures"
    result = library.import_files(
        [(fixtures / "listening.m4b", "Disc 2/01.m4b"), (fixtures / "tone.mp3", "Disc 10/01.mp3")]
    )
    _, auth = issue(client)
    feed = ET.fromstring(client.get(f"/opds/works/{result.work.id}?limit=1", auth=auth).content)
    first = feed.find(f"{{{ATOM}}}entry")
    assert "Track 1: Disc 2/01.m4b" in first.find(f"{{{ATOM}}}title").text
    second = ET.fromstring(client.get(links(feed, "next")[0].get("href"), auth=auth).content).find(
        f"{{{ATOM}}}entry"
    )
    assert "Track 2: Disc 10/01.mp3" in second.find(f"{{{ATOM}}}title").text


def test_accepted_edits_update_atom_timestamp_and_cannot_inject_xml(client):
    work = upload(client, epub_bytes("Before")).json()["work"]
    library = client.app.state.library
    changed = library.edit(
        work["id"],
        WorkEdit(
            revision=work["revision"],
            title="After <script>\x00",
            authors=["A & B"],
            description="<img src=x onerror=alert(1)>",
        ),
    )
    assert changed.updated_at > work["updated_at"]
    _, auth = issue(client)
    xml = ET.fromstring(client.get(f"/opds/works/{work['id']}", auth=auth).content)
    entry = xml.find(f"{{{ATOM}}}entry")
    assert entry.find(f"{{{ATOM}}}updated").text == changed.updated_at
    assert "<script>" in entry.find(f"{{{ATOM}}}title").text
    assert entry.find(f"{{{ATOM}}}summary").text == changed.description
    assert not entry.findall(".//script")


def test_backups_and_export_do_not_reissue_device_authority(client, tmp_path):
    issued, _ = issue(client)
    library = client.app.state.library
    exported = library.export()
    assert exported["schema_version"] == 15
    assert "device_credential" not in exported["tables"]
    assert issued["password"] not in json.dumps(exported)
    archive = tmp_path / "backup.zip"
    backup(library, archive)
    target = tmp_path / "fresh"
    restore(archive, target)
    restored = Library(target)
    try:
        with restored.sessions() as session:
            assert session.scalar(select(func.count()).select_from(DeviceCredential)) == 0
            assert session.scalar(select(func.count()).select_from(LoginSession)) == 0
    finally:
        restored.close()
