"""Disposable real backend serving the production web build for browser tests."""

import tempfile
from pathlib import Path

import uvicorn
from stacks.app import create_app
from stacks.config import Settings
from stacks.samples import epub_bytes
from stacks.samples import main as samples

samples()
Path("samples/The Quiet Library — phone.epub").write_bytes(epub_bytes("The Quiet Library — phone"))
with tempfile.TemporaryDirectory(prefix="stacks-browser-") as directory:
    uvicorn.run(
        create_app(
            Settings(data_dir=Path(directory), password="browser-test-password", _env_file=None)
        ),
        host="127.0.0.1",
        port=8123,
    )
