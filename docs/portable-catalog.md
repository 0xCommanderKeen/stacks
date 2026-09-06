# Portable catalog

Settings → Export catalog downloads ordinary UTF-8 JSON. The writer takes a
consistent SQLite snapshot, releases the catalog lock, and serializes one row at
a time to a private temporary file. The browser downloads the file directly. The
offline CLI uses the same writer:

```sh
uv run stacks export --data-dir ./data --output /separate/stacks-catalog.json
uv run stacks import-catalog /separate/stacks-catalog.json --data-dir ./fresh-data --allow-missing-originals
```

Stop the server before CLI maintenance. The import destination must not exist.
Import validates a private database before publishing the new directory. It keeps
IDs, root-relative paths, bibliographic relationships, series, ordered collections,
curation, repeated reading records, selected field origins, cover references, audio
progress, guarded grouping history and completed Trash receipts. No owner session,
reader password or absolute source-root configuration is exported or imported.

This is a catalog transfer, not a media backup. Publication files, chosen cover
originals and thumbnails are absent. Import requires explicit acknowledgement and
writes `MEDIA-RESTORE-REQUIRED.txt`. Restore the corresponding managed directory from
separate protection, preserving its relative paths and `.covers` originals; remount
external roots using their existing aliases. Never point managed recovery storage
at the old Polica catalog. Rebuild thumbnails and verify downloads before use.
See [backup recovery](backup-recovery.md) for file protection and recovery commands.

Intake history is retained, but imported queued/running intake jobs become cancelled.
They never resume automatically. Review the new root configuration before deliberately
retrying a job. Completed import/Trash receipts are retained; unfinished file operations
must be resolved before export and are rejected on import. Backup history has no archive
copies in the new installation. Issue fresh reader credentials after import.

## Format contract

The envelope contains `format_version: 1`, `schema_version: 15`, a `roots` declaration,
and `tables`, mapping documented catalog table names to arrays of column-value objects.
Root declarations contain only `kind: managed` or `kind: external`. Object order is
irrelevant. IDs, nullable values, JSON booleans and finite numbers retain their types.
Fields ending in `_json` preserve embedded facts, selected provenance and history as
JSON strings. Table and column names correspond to the public SQLAlchemy models;
`stacks.portable.TABLE_NAMES` is the explicit allowlist, excluding authority tables.

The importer currently accepts this exact format/schema pair; older early development
exports did not include a portable-format version and are not accepted. Future format
changes need an explicit version handler. This is unrelated to Polica migration.
Unknown/duplicate keys or tables, missing tables, unsafe paths, malformed UUIDs,
checksums, types, selected origins, incomplete foreign keys, invalid progress ownership,
redirect cycles and truncated JSON are rejected. Import never contacts a provider.

The incremental parser uses [ijson's event interface](https://github.com/ICRAR/ijson).
Memory follows the largest individual field/row, not the whole catalog. Format 1
limits decoded strings to 16 MiB and objects to 1,000 keys with eight levels of
structural nesting. Embedded JSON strings are validated separately. Large catalogs
remain row streams; the original SQLite snapshot and output require temporary disk.
The import/export format is transparent JSON, not executable code or a database dump.
