"""Disposable real backend serving the production web build for browser tests."""

import tempfile
from pathlib import Path

import uvicorn
from pypdf import PdfWriter
from stacks.app import create_app
from stacks.config import Settings
from stacks.library import Library
from stacks.samples import epub_bytes
from stacks.samples import main as samples

samples()
writer = PdfWriter()
writer.add_blank_page(width=400, height=600)
writer.add_metadata({"/Title": "An Open Page", "/Author": "Stacks Samples"})
writer.write("samples/An Open Page.pdf")
writer.add_metadata({"/Title": "A Different Format"})
writer.write("samples/A Different Format.pdf")
Path("samples/Ways to Read.epub").write_bytes(epub_bytes("Ways to Read"))
Path("samples/The Quiet Library — phone.epub").write_bytes(epub_bytes("The Quiet Library — phone"))
for index in range(26):
    Path(f"samples/Page Test {index:02d}.epub").write_bytes(
        epub_bytes(f"Page Test {index:02d}", authors=("Pagination Fixture",), cover=False)
    )
with tempfile.TemporaryDirectory(prefix="stacks-browser-") as directory:
    library = Library(Path(directory))
    library.import_files(
        [
            (Path("backend/tests/fixtures/listening.m4b"), "Disc 1/01.m4b"),
            (Path("backend/tests/fixtures/tone.mp3"), "Disc 2/01.mp3"),
        ]
    )
    library.close()
    uvicorn.run(
        create_app(
            Settings(data_dir=Path(directory), password="browser-test-password", _env_file=None)
        ),
        host="127.0.0.1",
        port=8123,
    )
