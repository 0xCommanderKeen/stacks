import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from stacks.app import create_app
from stacks.config import Settings
from stacks.epub import InvalidBook, inspect_epub

from .conftest import HEADERS, PASSWORD, upload


def rewrite(publication, entries):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(publication)) as source, zipfile.ZipFile(result, "w") as target:
        for member in source.infolist():
            if member.filename not in entries:
                target.writestr(member, source.read(member))
        for name, content in entries.items():
            target.writestr(name, content)
    return result.getvalue()


@pytest.mark.parametrize("content", [b"", b"not an epub", b"PK\x03\x04damaged"])
def test_invalid_upload_leaves_no_catalog_or_staging(client, content):
    assert upload(client, content).status_code == 422
    assert client.get("/api/catalog").json()["total"] == 0
    assert list(client.app.state.library.staging.iterdir()) == []


def test_epub_traversal_and_xml_entities_rejected(client, publication):
    assert upload(client, rewrite(publication, {"../../escape": b"bad"})).status_code == 422
    xml = b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
    assert upload(client, rewrite(publication, {"META-INF/container.xml": xml})).status_code == 422


def test_bounded_metadata(client, publication):
    oversized = b"x" * (2 * 1024**2 + 1)
    assert upload(client, rewrite(publication, {"OEBPS/content.opf": oversized})).status_code == 422


def test_duplicate_archive_members_rejected(publication, tmp_path):
    content = io.BytesIO(publication)
    with zipfile.ZipFile(content, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("mimetype", b"application/epub+zip")
    path = tmp_path / "duplicate.epub"
    path.write_bytes(content.getvalue())
    with pytest.raises(InvalidBook, match="ambiguous"):
        inspect_epub(path, "duplicate.epub")


def test_upload_size_limit(settings):
    limited = settings.model_copy(update={"max_upload_bytes": 1024})
    with TestClient(create_app(limited)) as client:
        client.headers.update(HEADERS)
        client.post("/api/login", json={"password": PASSWORD})
        assert upload(client, b"x" * 1025).status_code == 413
        # No content-length: the streamed byte counter must also enforce the limit.
        assert (
            client.post(
                "/api/import",
                content=iter([b"x" * 800, b"y" * 800]),
                headers={"X-Filename": "book.epub"},
            ).status_code
            == 413
        )
        assert list(client.app.state.library.staging.iterdir()) == []


def test_auth_csrf_logout_and_private_content(settings):
    with TestClient(create_app(settings)) as client:
        for path in (
            "/api/catalog",
            "/api/export",
            "/api/status",
            "/api/openapi.json",
            "/api/assets/x/download",
        ):
            assert client.get(path).status_code == 401
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 403
        assert (
            client.post(
                "/api/login",
                json={"password": PASSWORD},
                headers={**HEADERS, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        assert (
            client.post("/api/login", json={"password": "wrong"}, headers=HEADERS).status_code
            == 401
        )
        login = client.post("/api/login", json={"password": PASSWORD}, headers=HEADERS)
        assert "HttpOnly" in login.headers["set-cookie"]
        token = client.cookies.get("stacks_session")
        assert client.get("/api/session").status_code == 204
        assert client.post("/api/logout", headers=HEADERS).status_code == 204
        client.cookies.set("stacks_session", token)
        assert client.get("/api/session").status_code == 401
        assert client.get("/health/ready").status_code == 200


def test_no_default_password(tmp_path, monkeypatch):
    monkeypatch.delenv("STACKS_PASSWORD", raising=False)
    with pytest.raises(ValueError):
        Settings(_env_file=None, data_dir=tmp_path)


def test_login_throttling(settings):
    with TestClient(create_app(settings)) as client:
        for _ in range(10):
            assert (
                client.post("/api/login", json={"password": "wrong"}, headers=HEADERS).status_code
                == 401
            )
        assert (
            client.post("/api/login", json={"password": PASSWORD}, headers=HEADERS).status_code
            == 429
        )


def test_password_change_invalidates_existing_sessions(settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/login", json={"password": PASSWORD}, headers=HEADERS)
        token = client.cookies.get("stacks_session")
    from pydantic import SecretStr

    changed = settings.model_copy(update={"password": SecretStr("replacement-library-password")})
    with TestClient(create_app(changed)) as client:
        client.cookies.set("stacks_session", token)
        assert client.get("/api/session").status_code == 401
