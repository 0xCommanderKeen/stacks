# Backup and recovery

Settings shows free space, intake failures, unfinished Trash operations, and backup
history. Create a backup, wait for completion, and download it to separate storage.
Downloads use the browser's file download facility. Closing Settings does not cancel
a backup. Only one backup runs at a time; at most three server archive copies are
kept. Remove downloaded server copies explicitly to free space; their history stays.
An interrupted backup is recorded as failed on restart and can be created again.

## Choose what to protect

- **Catalog and chosen covers** (default): a consistent SQLite snapshot and every
  immutable chosen cover original, including retained choices needed for undo.
  Publication originals and disposable thumbnails are excluded. This is practical
  for a large registered archive, with source storage protected independently.
- **Including managed originals**: adds the complete managed directory, including
  originals in Trash and thumbnails. Registered source originals are still excluded.
  Budget disk space for the entire archive; archives are stored without compression.

Original checksums are verified as bytes are archived. An incomplete archive is never
advertised for download. The catalog write lock is released after the SQLite snapshot;
search, metadata edits, and audio remain available while the archive is packaged.
Imports, cover changes and managed file moves wait for packaging to finish. Edits made
after the snapshot belong to the next backup. Pending file operations must recover
before a backup can start. Failure leaves the previous completed backups intact.

Neither backup mode includes reusable owner sessions or reader passwords. Configure
the owner password separately and issue fresh reader credentials after recovery.
Absolute source locations remain deployment configuration, not portable catalog data.
The legacy `POST /api/backup` endpoint still produces a full synchronous backup for
existing tooling; Settings uses the queued `/api/backups` workflow and durable history.

## Offline commands

Stop the server first; the data directory permits only one owner process.

```sh
uv run stacks backup --data-dir ./data --mode catalog --output /separate/stacks.catalog.zip
uv run stacks backup --data-dir ./data --mode full --output /separate/stacks.full.zip
uv run stacks restore /separate/stacks.full.zip --data-dir ./restored-data
uv run stacks restore /separate/stacks.catalog.zip --data-dir ./restored-data --allow-missing-originals
```

The destination must not exist. Restore verifies the manifest, file hashes, SQLite
integrity, foreign keys, original declarations and chosen covers before publishing the
new directory. Catalog-only restore requires the explicit missing-original flag and
writes `MEDIA-RESTORE-REQUIRED.txt`. Restore the separately protected managed originals
under `restored-data/managed` with their original relative paths while offline. Preserve
the restored `.covers` directory. Remount registered sources using their existing
aliases; paths may differ. Missing files remain missing without catalog deletion.
Retain the recovery marker until original storage and downloads have been checked.

Rebuild disposable thumbnails after original storage is available:

```sh
uv run stacks rebuild-thumbnails --data-dir ./restored-data --sources /private/sources.json
```

The optional JSON file maps aliases to absolute source paths, for example
`{"archive":"/mnt/readonly-books"}`. Do not commit private paths. The command walks
catalog identities in batches of 100, processes one original at a time in the bounded
inspector, and writes thumbnails atomically. It verifies original hashes and reports
rebuilt, without-cover and unavailable counts; unavailable originals return exit code 1.
It does not alter publication files or manual metadata. Rerunning is safe.

## Before an upgrade and rollback

Every schema upgrade automatically creates a consistent, mode-0600 SQLite snapshot
in `data/schema-backups` before changing the database. If the snapshot cannot be
created or flushed, startup stops before migration. These snapshots contain catalog
data only, with sessions and reader passwords removed. They are local rollback aids,
not substitutes for off-volume backups, and are retained until explicitly removed.
Make and copy a complete recovery backup before an update, and retain the old image.

For rollback, stop the service and preserve the entire newer data directory first.
Restore a pre-update backup into a fresh directory and start the retained compatible
image against that directory. Alternatively, build a fresh directory from the
pre-upgrade SQLite snapshot plus the corresponding preserved managed originals and
source configuration. Never overwrite the live database or mix a database with an
unknown original-file snapshot. Changes made after the snapshot are absent in the
older view; retain the newer directory for recovery. Verify catalog counts, chosen
covers, personal records, progress, downloads and source availability before resuming.

Automated tests exercise snapshot failure before migration, populated schema changes,
consistent backup during metadata edits, archive verification, omitted-media consent,
worker restart history, download access and thumbnail rebuilds. Fresh NAS container
restore and physical-device acceptance are separate release qualification gates.
