# Stacks

A personal library for books, comics, and audiobooks.

Stacks is a clean-start project focused on safe imports, useful cataloging,
comic series, and dependable audiobook playback. The current development version supports
**EPUB, PDF, CBZ, CBR, MP3, M4A, and M4B import, catalog search, edition/series editing,
original downloads, reversible grouping/splitting, audiobook playback with saved progress,
personal shelves and reading history, followed comic runs, ordered collections, durable Inbox scans,
previewed batch acceptance, read-only source registration, backup/restore, protected metadata suggestions, chosen covers, scoped OPDS access,
and bounded portable catalog export/import**. NAS scale and recovery qualification are
recorded; actual-device and persistent-adoption gates remain open. See the
[release acceptance matrix](docs/rebuild/ACCEPTANCE.md).

- [Implementation plan](docs/rebuild/PLAN.md)
- [Domain language](CONTEXT.md)
- [First-book scope, guarantees, and limitations](docs/first-book.md)
- [Audiobook playback and progress](docs/audio.md)
- [Personal shelves and reading history](docs/personal-library.md)
- [Followed series and comic runs](docs/followed-series.md)
- [Durable Inbox discovery](docs/durable-inbox.md)
- [Batch acceptance and audio grouping](docs/batch-acceptance.md)

The intended deployment is one self-hosted application with local media storage.
The repository is public; personal library files, databases, and credentials do
not belong in it.

## Run locally

Requires Python 3.13, uv, Node 22, and pnpm 10.6.5. Compressed CBR inspection also
requires a rarfile-supported decompressor, such as `unar` (the backend bundled in the container).

```sh
cp .env.example .env
# Set STACKS_PASSWORD in .env to a unique password of at least 12 characters.
make install
pnpm --dir frontend build
make api
```

Open http://127.0.0.1:8000. For frontend hot reload, also run `make web` and use
http://127.0.0.1:5173. `make samples` creates six original sample EPUBs to upload.
All fonts and application assets are served locally; catalog use needs no external service.

## Docker

```sh
cp .env.example .env
# Set STACKS_PASSWORD before starting.
docker compose up --build -d
```

Open http://127.0.0.1:8133. Compose stores the library in the named `stacks-data`
volume and binds the port to localhost. Configure your private-network proxy/access
separately; set `STACKS_SECURE_COOKIE=true` when serving over HTTPS. The image runs
as UID/GID 10001 and uses a single server process. Bind-mounted data directories
must be writable by that UID. Keep the SQLite database on a local filesystem.

## Back up and restore

Use Settings → Create backup, then download the completed archive. The default
includes catalog data and chosen cover originals; publication originals require
separate protection. Select the full option to include managed originals.
See [backup and recovery](docs/backup-recovery.md) for restore modes, history,
pre-upgrade snapshots, rollback, and thumbnail rebuilding.
The JSON catalog export includes metadata and references, not original book bytes.

For offline maintenance, stop Stacks first:

```sh
uv run stacks backup --mode full --data-dir ./data --output /path/to/stacks.backup.zip
uv run stacks restore /path/to/stacks.backup.zip --data-dir ./restored-data
```

The restore destination must not exist. Restore verifies checksums, relationships,
schema version, and original assets before publishing the directory. Set
`STACKS_DATA_DIR=./restored-data` and start the application to use it. Keep the old
data directory until the restored library is verified. Configure your password
separately; backups contain no reusable login sessions.

For a Compose library, stop the app, then run the packaged CLI against its volume:

```sh
docker compose stop stacks
docker compose run --rm stacks stacks backup --mode full --data-dir /data --output /data/library.backup.zip
```

Copy that backup to separate storage. A backup stored only beside the live library
does not protect against loss of the volume. To restore into a new subdirectory:

```sh
docker compose run --rm stacks stacks restore /data/library.backup.zip --data-dir /data/restored
```

Then set the service's `STACKS_DATA_DIR` environment to `/data/restored` in Compose
and recreate the service. Do not run backup/restore CLI commands while the server
owns that data directory.

## Development checks

```sh
make check
pnpm --dir frontend exec playwright install chromium
make test-browser
docker build -t stacks:test .
uv run python scripts/container_smoke.py stacks:test
```

CI runs the same checks and the container restoration exercise. Backend response
schemas generate the committed TypeScript contract through `make types`.

Implementation targets Linux/NAS and macOS. Windows is not currently supported.

Current format and series behavior is documented in [Formats and series](docs/formats-and-series.md).

[Grouping and undo](docs/grouping.md) explains previews, conflict choices, and stable format identity.

[Collections](docs/collections.md) explains ordered reading lists across books,
comics, and audio, including Home choices and grouping-safe membership.


[Read-only sources](docs/read-only-sources.md) explains fresh registration without
copying, source relocation, and the separate backup policy for external originals.
Full library backups include catalog and Stacks-owned originals/covers. Registered
external originals require their own source-folder backup or snapshot.

Recoverable removal is described in [Trash and restore](docs/recoverable-trash.md).

Portable JSON export and fresh import are documented in [portable catalog](docs/portable-catalog.md).
