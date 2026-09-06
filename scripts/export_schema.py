"""Generate the frontend's contract without opening a database or using owner credentials."""

import json
from pathlib import Path

from stacks.app import create_app
from stacks.config import Settings

app = create_app(Settings(password="schema-generation-only", _env_file=None))
Path("openapi.json").write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
