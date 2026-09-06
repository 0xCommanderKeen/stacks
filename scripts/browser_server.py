"""Disposable real backend serving the production web build for browser tests."""

import io
import os
import tempfile
import zipfile
from pathlib import Path

import uvicorn
from mutagen.id3 import TIT2
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from stacks.app import create_app
from stacks.config import Settings
from stacks.library import Library
from stacks.samples import epub_bytes
from stacks.samples import main as samples
from stacks.schemas import MembershipEdit, SeriesEdit, TrashRequest, WorkEdit
from stacks.trash import Trash

samples()
writer = PdfWriter()
writer.add_blank_page(width=400, height=600)
writer.add_metadata({"/Title": "An Open Page", "/Author": "Stacks Samples"})
writer.write("samples/An Open Page.pdf")
writer.add_metadata({"/Title": "A Different Format"})
writer.write("samples/A Different Format.pdf")
for viewport in ("desktop", "phone"):
    Path(f"samples/Cover selection {viewport}.epub").write_bytes(
        epub_bytes(f"Cover selection {viewport}")
    )
Path("samples/Ways to Read.epub").write_bytes(epub_bytes("Ways to Read"))
Path("samples/The Quiet Library — phone.epub").write_bytes(epub_bytes("The Quiet Library — phone"))
for index in range(26):
    Path(f"samples/Page Test {index:02d}.epub").write_bytes(
        epub_bytes(f"Page Test {index:02d}", authors=("Pagination Fixture",), cover=False)
    )
for viewport in ("desktop", "phone"):
    for index in range(25):
        name = f"Shelf Test {viewport} {index:02d}"
        Path(f"samples/{name}.epub").write_bytes(
            epub_bytes(name, authors=("Shelf Pagination Fixture",), cover=False)
        )
with (
    tempfile.TemporaryDirectory(prefix="stacks-browser-") as directory,
    tempfile.TemporaryDirectory(prefix="stacks-browser-source-") as source_directory,
):
    for viewport in ("desktop", "phone"):
        Path(source_directory, f"Registered {viewport}.epub").write_bytes(
            epub_bytes(f"A registered book {viewport}")
        )
    for viewport in ("desktop", "phone"):
        folder = Path(source_directory, f"Inbox {viewport}")
        folder.mkdir()
        for index in range(26):
            publication = folder / f"{index:02}.epub"
            publication.write_bytes(epub_bytes(f"Inbox {viewport} {index:02}", cover=False))
            os.utime(publication, (1, 1))
    for viewport in ("desktop", "phone"):
        folder = Path(source_directory, f"Acceptance {viewport}")
        folder.mkdir()
        for index in range(3):
            publication = folder / f"{index}.epub"
            publication.write_bytes(epub_bytes(f"Acceptance {viewport} {index}", cover=False))
            os.utime(publication, (1, 1))
        for index in (2, 10):
            folder = Path(source_directory, f"Audio inbox {viewport}", f"Disc {index}")
            folder.mkdir(parents=True)
            track = folder / "track.mp3"
            track.write_bytes(Path("backend/tests/fixtures/tone.mp3").read_bytes())
            audio = MP3(track)
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TIT2(encoding=3, text=f"Acceptance {viewport} track {index}"))
            audio.save()
            os.utime(track, (1, 1))
    library = Library(Path(directory))
    library.import_files(
        [
            (Path("backend/tests/fixtures/listening.m4b"), "Disc 1/01.m4b"),
            (Path("backend/tests/fixtures/tone.mp3"), "Disc 2/01.mp3"),
        ]
    )
    old_run = library.save_series(SeriesEdit(name="Orbit", run="1999"))
    new_run = library.save_series(SeriesEdit(name="Orbit", run="2026"))
    comic_titles = [
        (f"Orbit {index:02d}", old_run.id, float(index), f"#{index}") for index in range(1, 26)
    ]
    comic_titles += [
        ("Orbit Annual", old_run.id, 1.5, "Annual 1"),
        ("Orbit Returns", new_run.id, 1.0, "#1"),
        ("A Standalone Comic", None, 0, ""),
    ]
    for title, run_id, position, designation in comic_titles:
        cover = Image.new("RGB", (240, 360), "#304e46")
        draw = ImageDraw.Draw(cover)
        draw.ellipse((35, 70, 205, 240), outline="#d9e293", width=4)
        draw.line((20, 280, 220, 280), fill="#d9e293", width=3)
        draw.text((25, 310), title, fill="#f4f1e9")
        image = io.BytesIO()
        cover.save(image, format="PNG")
        path = Path(f"samples/{title}.cbz")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.png", image.getvalue())
            archive.writestr(
                "ComicInfo.xml",
                f"<ComicInfo><Title>{title}</Title><Writer>Stacks Samples</Writer></ComicInfo>",
            )
        work = library.import_file(path, path.name).work
        if run_id:
            library.edit(
                work.id,
                WorkEdit(
                    revision=work.revision,
                    title=work.title,
                    authors=work.authors,
                    description=work.description,
                    memberships=[
                        MembershipEdit(series_id=run_id, position=position, designation=designation)
                    ],
                ),
            )
    trash = Trash(library)
    for viewport in ("desktop", "phone"):
        Path(f"samples/Trash audio target {viewport}.epub").write_bytes(
            epub_bytes(f"Trash audio target {viewport}")
        )
        track = Path(f"samples/Trash audio {viewport}.m4b")
        track.write_bytes(Path("backend/tests/fixtures/listening.m4b").read_bytes())
        audio = MP4(track)
        audio["\xa9nam"] = [track.stem]
        audio["\xa9alb"] = [track.stem]
        audio.save()
    for viewport in ("desktop", "phone"):
        Path(f"samples/Trash journey {viewport}.epub").write_bytes(
            epub_bytes(f"Trash journey {viewport}")
        )
        for index in range(13):
            path = Path(f"samples/Recovery shelf {viewport} {index:02d}.epub")
            path.write_bytes(epub_bytes(path.stem, cover=False))
            work = library.import_file(path, path.name).work
            trash.request(work.id, TrashRequest(revision=work.revision, action="trash"))
            while trash.step():
                pass
    library.close()
    uvicorn.run(
        create_app(
            Settings(
                data_dir=Path(directory),
                password="browser-test-password",
                sources={"sample": Path(source_directory)},
                _env_file=None,
            )
        ),
        host="127.0.0.1",
        port=8123,
    )
