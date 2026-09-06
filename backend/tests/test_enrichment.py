import io
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from stacks.models import MetadataSuggestion
from stacks.openlibrary import LIMIT, NoRedirect, ProviderUnavailable, fetch, lookup
from stacks.samples import epub_bytes

from .conftest import upload
from .test_covers import choose
from .test_operations import pair, preview


class Provider:
    def request(self, **request):
        if request["kind"] == "details":
            return {"description": "A proposed description."}
        start = request.get("offset", 0)
        return {
            "matches": [
                {
                    "key": f"/works/OL{index + 1}W",
                    "title": f"Proposed title {index}",
                    "authors": ["Proposed Author"],
                }
                for index in range(start, start + 5)
            ],
            "total": 40,
        }


def search(client, work):
    client.app.state.enrichment.provider = Provider()
    result = client.post(f"/api/works/{work['id']}/metadata/search", json={"q": "a book"})
    assert result.status_code == 200, result.text
    return result.json()["items"][0]


def accept(client, work, suggestion, fields, **extra):
    return client.post(
        f"/api/works/{work['id']}/metadata/{suggestion['id']}/accept",
        json={
            "revision": work["revision"],
            "suggestion_fetched_at": suggestion["fetched_at"],
            "fields": fields,
            **extra,
        },
    )


def test_preview_accept_manual_protection_refresh_and_cover_preservation(client):
    work = choose(client, upload(client, epub_bytes("Embedded title")).json()["work"])
    suggestion = search(client, work)
    assert client.get(f"/api/works/{work['id']}").json()["title"] == "Embedded title"
    result = accept(client, work, suggestion, ["title"])
    assert result.status_code == 200, result.text
    work = result.json()
    assert work["title"] == "Proposed title 0" and work["selected_cover_id"]
    state = client.get(f"/api/works/{work['id']}/metadata").json()
    assert state["origins"]["title"]["source"] == "openlibrary"
    assert state["origins"]["title"]["source_url"] == "https://openlibrary.org/works/OL1W"
    work = client.patch(
        f"/api/works/{work['id']}",
        json={
            "revision": work["revision"],
            "title": "My corrected title",
            "authors": work["authors"],
            "description": work["description"],
        },
    ).json()
    suggestion = search(client, work)
    assert accept(client, work, suggestion, ["title"]).status_code == 409
    assert client.get(f"/api/works/{work['id']}").json()["title"] == "My corrected title"
    detail = client.post(f"/api/works/{work['id']}/metadata/{suggestion['id']}/details").json()
    assert (
        accept(client, work, suggestion, ["authors"]).status_code == 409
    )  # Refreshed proposal token.
    result = accept(client, work, detail, ["description"])
    assert result.status_code == 200, result.text
    work = result.json()
    assert (
        work["title"] == "My corrected title" and work["description"] == "A proposed description."
    )
    replaced = accept(client, work, detail, ["title"], replace_protected=["title"])
    assert replaced.status_code == 200
    assert replaced.json()["selected_cover_id"] == work["selected_cover_id"]
    assert accept(client, work, detail, ["authors"]).status_code == 409  # Work revision changed.


def test_provider_failure_does_not_block_import_and_candidate_cache_is_bounded(client):
    work = upload(client, epub_bytes("Offline work")).json()["work"]

    class Offline:
        def request(self, **request):
            raise ProviderUnavailable("Provider offline")

    client.app.state.enrichment.provider = Offline()
    assert (
        client.post(f"/api/works/{work['id']}/metadata/search", json={"q": "offline"}).status_code
        == 502
    )
    assert upload(client, epub_bytes("Still local")).status_code == 200
    client.app.state.enrichment.provider = Provider()
    for offset in range(0, 30, 5):
        result = client.post(
            f"/api/works/{work['id']}/metadata/search", json={"q": "paged", "offset": offset}
        )
        assert result.status_code == 200 and len(result.json()["items"]) == 5
    with client.app.state.library.sessions() as session:
        assert session.scalar(select(func.count()).select_from(MetadataSuggestion)) == 20


def test_provenance_survives_grouping_undo_export_and_backup(client, tmp_path):
    from stacks.backup import backup, restore
    from stacks.library import Library
    from stacks.models import Work
    from stacks.provenance import origins

    source, target = pair(client)
    suggestion = search(client, source)
    source = accept(client, source, suggestion, ["title", "authors"]).json()
    plan = preview(client, source, target)
    response = client.post(
        f"/api/operations/{plan['id']}/commit",
        json={
            "resolutions": {c["field"]: "source" for c in plan["conflicts"]},
        },
    )
    assert response.status_code == 200
    assert (
        client.get(f"/api/works/{target['id']}/metadata").json()["origins"]["title"]["source"]
        == "openlibrary"
    )
    assert client.get(f"/api/works/{source['id']}/metadata").status_code == 404
    assert client.post(f"/api/operations/{plan['id']}/undo").status_code == 200
    library = client.app.state.library
    exported = library.export()
    row = next(row for row in exported["tables"]["work"] if row["id"] == source["id"])
    assert json.loads(row["metadata_origins_json"])["title"]["source"] == "openlibrary"
    archive = tmp_path / "backup.zip"
    backup(library, archive)
    restore(archive, tmp_path / "restored")
    restored = Library(tmp_path / "restored")
    try:
        with restored.sessions() as session:
            assert origins(session.get(Work, source["id"]))["title"]["source"] == "openlibrary"
    finally:
        restored.close()


@pytest.mark.parametrize("raw", [b"bad JSON", b"[]", b"x" * (LIMIT + 1)])
def test_provider_rejects_malformed_or_oversized_response(monkeypatch, raw):
    response = io.BytesIO(raw)
    response.headers = {}
    monkeypatch.setattr(
        "stacks.openlibrary.build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: response),
    )
    with pytest.raises(ProviderUnavailable):
        fetch("/search.json?q=book")


def test_provider_rejects_redirect_and_untrusted_keys_and_handles_partial_fields(monkeypatch):
    with pytest.raises(ProviderUnavailable):
        NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/")
    with pytest.raises(ProviderUnavailable):
        lookup({"kind": "details", "key": "//127.0.0.1/secret"})
    monkeypatch.setattr(
        "stacks.openlibrary.fetch",
        lambda *args: {
            "docs": [
                {"key": "/works/OL1W", "title": "Only a title"},
                {"key": "//bad", "title": "Ignored"},
            ],
            "numFound": 1,
        },
    )
    result = lookup({"kind": "search", "q": "query"})
    assert result["matches"] == [{"key": "/works/OL1W", "title": "Only a title", "authors": []}]


def test_provider_timeout_kills_lookup_and_releases_concurrency(monkeypatch):
    import subprocess

    from stacks.openlibrary import OpenLibrary

    killed = []

    class Child:
        pid = 12345
        returncode = 0
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def communicate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("lookup", 12)
            return b"", b""

    monkeypatch.setattr("stacks.openlibrary.subprocess.Popen", lambda *args, **kwargs: Child())
    monkeypatch.setattr("stacks.openlibrary.os.killpg", lambda pid, signal: killed.append(pid))
    provider = OpenLibrary()
    with pytest.raises(ProviderUnavailable, match="timed out"):
        provider.request(kind="search", q="a book")
    assert killed == [12345] and not provider.lock.locked()


def test_manual_field_protection_survives_equal_value_grouping_and_split(client):
    from stacks.schemas import WorkEdit

    source, target = pair(client)
    library = client.app.state.library
    source = library.edit(
        source["id"],
        WorkEdit(
            revision=source["revision"],
            title="Equal title",
            authors=source["authors"],
            description=source["description"],
        ),
    ).model_dump()
    suggestion = search(client, target)
    # Simulate a provider proposing the same selected title, with a different origin.
    with library.sessions.begin() as session:
        saved = session.get(MetadataSuggestion, suggestion["id"])
        saved.values_json = json.dumps({"title": "Equal title"})
    target = accept(client, target, suggestion, ["title"]).json()
    plan = preview(client, source, target)
    assert (
        client.post(
            f"/api/operations/{plan['id']}/commit",
            json={"resolutions": {c["field"]: "target" for c in plan["conflicts"]}},
        ).status_code
        == 200
    )
    metadata = client.get(f"/api/works/{target['id']}/metadata").json()
    assert metadata["origins"]["title"]["protected"]
    target = metadata["work"]
    plan = preview(
        client,
        target,
        mode="split",
        representation_id=target["editions"][0]["representations"][0]["id"],
    )
    assert (
        client.post(f"/api/operations/{plan['id']}/commit", json={"resolutions": {}}).status_code
        == 200
    )
    for work in client.get("/api/catalog").json()["items"]:
        assert client.get(f"/api/works/{work['id']}/metadata").json()["origins"]["title"][
            "protected"
        ]


@pytest.mark.parametrize(
    "overrides, protected",
    [
        ({}, set()),
        ({"title": "Batch title"}, {"title"}),
        ({"authors": ["Chosen writer"]}, {"authors"}),
    ],
)
def test_inbox_resolved_facts_only_protect_explicit_overrides(tmp_path, overrides, protected):
    from stacks.intake import Intake
    from stacks.library import Library
    from stacks.models import Work
    from stacks.provenance import origins
    from stacks.schemas import AcceptanceRequest, AcceptedMetadata, JobChange, ScanRequest

    source = tmp_path / "source"
    source.mkdir()
    (source / "book.epub").write_bytes(epub_bytes("Embedded title"))
    library = Library(tmp_path / "catalog", {"sample": source})
    worker = Intake(library, stable_seconds=0)
    try:
        worker.scan(ScanRequest(root="sample"))
        while worker.step():
            pass
        preview = worker.preview_acceptance(
            AcceptanceRequest(root="sample", metadata=AcceptedMetadata(**overrides))
        )
        worker.change(preview.id, JobChange(action="confirm", revision=preview.revision))
        while worker.step():
            pass
        work = library.list(scope="all").items[0]
        with library.sessions() as session:
            actual = origins(session.get(Work, work.id))
        assert {field for field, origin in actual.items() if origin["protected"]} == protected
        assert actual["description"]["source"] == "embedded"
    finally:
        worker.close()
        library.close()
