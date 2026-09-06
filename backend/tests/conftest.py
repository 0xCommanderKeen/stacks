import pytest
from fastapi.testclient import TestClient
from stacks.app import create_app
from stacks.config import Settings
from stacks.samples import epub_bytes

PASSWORD = "test-library-password"
HEADERS = {"X-Stacks-Request": "1"}


@pytest.fixture
def publication():
    return epub_bytes()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "library", password=PASSWORD, frontend_dir=tmp_path / "none"
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        assert (
            client.post("/api/login", json={"password": PASSWORD}, headers=HEADERS).status_code
            == 204
        )
        client.headers.update(HEADERS)
        yield client


def upload(client, content, name="book.epub"):
    return client.post(
        "/api/import",
        content=content,
        headers={
            "Content-Type": "application/epub+zip",
            "X-Filename": name,
        },
    )
