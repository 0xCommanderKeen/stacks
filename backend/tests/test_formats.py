import io
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select
from stacks.backup import backup, restore
from stacks.epub import InvalidBook
from stacks.inspection import inspect_file
from stacks.library import Library
from stacks.models import Asset

from .conftest import upload

FIXTURES = Path(__file__).parent / "fixtures"


def pdf_bytes():
    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=600)
    writer.add_metadata({"/Title": "An Open Page", "/Author": "Stacks Samples"})
    writer.write(out)
    return out.getvalue()


def comic_bytes(fmt="cbz", unsafe=False):
    image = io.BytesIO()
    Image.new("RGB", (40, 60), "green").save(image, "PNG")
    files = {
        "ComicInfo.xml": b"<ComicInfo><Title>Green Rooms</Title><Series>Rooms</Series>"
        b"<Number>Annual 2024</Number><Year>2024</Year><Writer>Alex Reed</Writer></ComicInfo>",
        "pages/10.png": image.getvalue(),
        "pages/2.png": image.getvalue(),
    }
    if unsafe:
        files["../outside.png"] = image.getvalue()
    if fmt == "cbz":
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return out.getvalue()

    # Original stored RAR4 fixture: no external licensed publication or rar writer needed.
    def header(content):
        return struct.pack("<H", zlib.crc32(content) & 0xFFFF) + content

    out = b"Rar!\x1a\x07\x00" + header(struct.pack("<BHH6s", 0x73, 0, 13, b"\x00" * 6))
    for name, content in files.items():
        encoded = name.encode()
        out += (
            header(
                struct.pack(
                    "<BHHIIBIIBBHI",
                    0x74,
                    0x8000,
                    32 + len(encoded),
                    len(content),
                    len(content),
                    3,
                    zlib.crc32(content),
                    0,
                    20,
                    0x30,
                    len(encoded),
                    0x20,
                )
                + encoded
            )
            + content
        )
    return out + header(struct.pack("<BHH", 0x7B, 0, 7))


@pytest.mark.parametrize("fmt", ["pdf", "cbz", "cbr", "mp3", "m4a", "m4b"])
def test_format_import_download_restart_backup(client, tmp_path, fmt):
    content = (
        pdf_bytes()
        if fmt == "pdf"
        else comic_bytes(fmt)
        if fmt in {"cbz", "cbr"}
        else (FIXTURES / ("tone.mp3" if fmt == "mp3" else "tone.m4a")).read_bytes()
    )
    response = upload(client, content, f"sample.{fmt}")
    assert response.status_code == 200, response.text
    work = response.json()["work"]
    rep = work["editions"][0]["representations"][0]
    assert rep["format"] == fmt
    assert "download" in rep["capabilities"]
    asset = rep["assets"][0]
    assert client.get(f"/api/assets/{asset['id']}/download").content == content
    if fmt in {"cbz", "cbr"}:
        assert rep["facts"]["page_count"] == 2
        assert rep["has_cover"]
        assert rep["facts"]["series_hint"]["designation"] == "Annual 2024"
        assert work["memberships"] == []  # Embedded series names are suggestions, never identity.
    if fmt in {"mp3", "m4a", "m4b"}:
        assert rep["facts"]["duration_seconds"] > 1
        assert work["title"] == "A Listening Room"
    lib = client.app.state.library
    archive = tmp_path / "snapshot.zip"
    backup(lib, archive)
    root = tmp_path / "restored"
    restore(archive, root)
    restored = Library(root)
    try:
        assert restored.get(work["id"]).editions[0].representations[0].format == fmt
        with restored.sessions() as session:
            original = session.get(Asset, asset["id"])
            assert restored.resolve(original.relative_path).read_bytes() == content
    finally:
        restored.close()


@pytest.mark.parametrize("fmt", ["cbz", "cbr"])
def test_comic_unsafe_paths_are_rejected(client, fmt):
    response = upload(client, comic_bytes(fmt, unsafe=True), f"unsafe.{fmt}")
    assert response.status_code == 422
    assert client.get("/api/catalog").json()["total"] == 0


def test_encrypted_pdf_and_mislabeled_files_are_rejected(client):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("private")
    out = io.BytesIO()
    writer.write(out)
    assert upload(client, out.getvalue(), "locked.pdf").status_code == 422
    assert upload(client, b"not audio", "fake.mp3").status_code == 422
    assert upload(client, pdf_bytes(), "fake.cbz").status_code == 422


def test_audio_set_nested_natural_order_and_interrupted_recovery(tmp_path, monkeypatch):
    lib = Library(tmp_path / "data")
    sources = [
        (FIXTURES / "tone.mp3", name)
        for name in ["Disc 10/01.mp3", "Disc 2/10.mp3", "Disc 2/2.mp3"]
    ]
    monkeypatch.setattr(lib, "_publish", lambda _: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError, match="crash"):
        lib.import_files(sources)
    lib.close()
    lib = Library(tmp_path / "data")
    try:
        work = lib.list().items[0]
        rep = work.editions[0].representations[0]
        assert rep.format == "audio-set"
        assert [a.original_name for a in rep.assets] == [
            "Disc 2/2.mp3",
            "Disc 2/10.mp3",
            "Disc 10/01.mp3",
        ]
        with lib.sessions() as session:
            for asset in session.scalars(select(Asset).order_by(Asset.position)):
                assert (
                    lib.resolve(asset.relative_path).read_bytes()
                    == (FIXTURES / "tone.mp3").read_bytes()
                )
        assert lib.import_files(sources).duplicate
        # A standalone track is not the same representation as a three-track book.
        assert not lib.import_file(FIXTURES / "tone.mp3", "one.mp3").duplicate
    finally:
        lib.close()


def test_series_runs_labels_order_and_stale_edits(client):
    runs = [
        client.post("/api/series", json={"name": "Rooms", "run": run}).json()
        for run in ["2020 · Paper Press", "2024 · Paper Press"]
    ]
    assert runs[0]["id"] != runs[1]["id"]
    works = []
    for label, order in [("Annual 2024", 2), ("1/2", 1), ("Special", 3)]:
        # Different filenames with identical bytes are exact duplicates; use distinct PDF metadata.
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({"/Title": label})
        out = io.BytesIO()
        writer.write(out)
        work = upload(client, out.getvalue(), f"{order}.pdf").json()["work"]
        edition = work["editions"][0]
        response = client.patch(
            f"/api/works/{work['id']}",
            json={
                "revision": 1,
                "title": label,
                "authors": [],
                "description": "",
                "editions": [
                    {
                        **{k: edition[k] for k in ("id", "language", "publisher", "identifier")},
                        "language": "sl",
                        "narrator": "A Reader",
                        "abridgement": "unabridged",
                    }
                ],
                "memberships": [
                    {"series_id": runs[0]["id"], "designation": label, "position": order}
                ],
            },
        )
        assert response.status_code == 200, response.text
        works.append(response.json())
    ordered = client.get(f"/api/series/{runs[0]['id']}/works").json()["items"]
    assert [w["title"] for w in ordered] == ["1/2", "Annual 2024", "Special"]
    assert client.get(f"/api/series/{runs[1]['id']}/works").json()["items"] == []
    assert ordered[0]["editions"][0]["language"] == "sl"
    request = {"name": "Renamed Rooms", "run": "2020", "revision": 1}
    assert client.patch(f"/api/series/{runs[0]['id']}", json=request).status_code == 200
    assert client.patch(f"/api/series/{runs[0]['id']}", json=request).status_code == 409
    # Updating series metadata is visible through memberships without changing identity.
    assert (
        client.get(f"/api/works/{works[0]['id']}").json()["memberships"][0]["series"]["name"]
        == "Renamed Rooms"
    )
    assert len(client.get("/api/export").json()["tables"]["series_membership"]) == 3


def test_comic_page_order(tmp_path):
    path = tmp_path / "pages.cbz"
    path.write_bytes(comic_bytes())
    assert inspect_file(path, path.name).facts["pages"] == ["pages/2.png", "pages/10.png"]
    lib = Library(tmp_path / "data")
    try:
        with pytest.raises(InvalidBook):
            lib.import_files([(path, "../outside.cbz")])
    finally:
        lib.close()


def test_series_and_members_are_paginated_without_truncation(client):
    from stacks.models import Series, SeriesMembership, Work

    lib = client.app.state.library
    with lib.sessions.begin() as session:
        for index in range(1001):
            session.add(Series(name=f"Run {index:04d}", run=""))
        run = Series(name="Long Series", run="2024")
        session.add(run)
        session.flush()
        run_id = run.id
        for index in range(1001):
            session.add(
                Work(
                    title=f"Issue {index}",
                    memberships=[
                        SeriesMembership(series_id=run_id, designation=str(index), position=index)
                    ],
                )
            )
    page = client.get("/api/series?q=Run&offset=1000&limit=100").json()
    assert page["total"] == 1001 and page["items"][0]["name"] == "Run 1000"
    page = client.get(f"/api/series/{run_id}/works?offset=1000&limit=100").json()
    assert page["total"] == 1001 and page["items"][0]["title"] == "Issue 1000"
    assert client.get("/api/series?limit=1001").status_code == 422


def test_equal_natural_names_have_stable_audio_identity(tmp_path):
    from mutagen.id3 import ID3, TIT2

    paths = []
    for i, name in enumerate(["1.mp3", "01.mp3"]):
        path = tmp_path / name
        path.write_bytes((FIXTURES / "tone.mp3").read_bytes())
        tags = ID3(path)
        tags.add(TIT2(encoding=3, text=[f"Track {i}"]))
        tags.save(path)
        paths.append((path, name))
    lib = Library(tmp_path / "data")
    try:
        first = lib.import_files(paths)
        second = lib.import_files(list(reversed(paths)))
        assert second.duplicate and second.work.id == first.work.id
        assert [a.original_name for a in first.work.editions[0].representations[0].assets] == [
            "01.mp3",
            "1.mp3",
        ]
    finally:
        lib.close()


def test_compressed_cbr_uses_real_decompression(client):
    import rarfile

    path = FIXTURES / "compressed.cbr"
    with rarfile.RarFile(path) as archive:
        assert archive.getinfo("ComicInfo.xml").compress_type != rarfile.RAR_M0
    response = upload(client, path.read_bytes(), "compressed.cbr")
    assert response.status_code == 200, response.text
    assert response.json()["work"]["title"] == "Compressed Rooms"
    assert response.json()["work"]["editions"][0]["representations"][0]["has_cover"]


def test_previous_stacks_schema_opens_without_changing_originals(tmp_path):
    import stacks.db as db
    from alembic import command
    from alembic.config import Config

    lib = Library(tmp_path / "data")
    path = tmp_path / "old.pdf"
    path.write_bytes(pdf_bytes())
    work = lib.import_file(path, path.name).work
    config = Config()
    config.set_main_option("script_location", str(Path(db.__file__).parent / "migrations"))
    with lib.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001")
    lib.close()
    reopened = Library(tmp_path / "data")
    try:
        assert reopened.get(work.id).editions[0].narrator == ""
        with reopened.sessions() as session:
            asset = session.scalar(select(Asset))
            assert reopened.resolve(asset.relative_path).read_bytes() == pdf_bytes()
    finally:
        reopened.close()
