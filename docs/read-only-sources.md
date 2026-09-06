# Register originals without copying them

Stacks can register an existing publication in a configured read-only source
folder. It stores metadata, derived covers, notes, collections, and progress in
its own data directory. The registered original stays in its source, unchanged.
Registrations start in Archive; individual shelf choices and following rules
continue to apply. This is fresh intake, not a Polica database migration.

Configure `STACKS_SOURCES` as JSON mapping lowercase aliases to absolute source
directories. `managed` is reserved. Sources and the Stacks data directory must
not overlap. For example, add this to your own Compose configuration:

```yaml
services:
  stacks:
    environment:
      STACKS_SOURCES: '{"archive":"/sources/archive"}'
    volumes:
      - /your/existing/library:/sources/archive:ro
```

Keep actual deployment paths out of public configuration. The container user must
be able to read and traverse the mounted directory. Settings → Read-only sources
shows configured and unavailable aliases. Enter a path relative to a source for
one EPUB/PDF/CBZ/CBR/MP3/M4A/M4B, or multiple audio paths, one per line, for one
ordered audiobook. Disc folders and filenames use natural order. Source directory
scanning and batch review are the next intake slice.

Registration inspects and hashes the originals, checks that their file
observations stayed stable, and journals publication of Stacks-owned cover/cache
and catalog facts. It does not copy the original bytes. Interrupted publication
can resume at startup; unavailable or changed originals retain the journal and
catalog instead of being deleted. Wait for source writes to finish before
registering. An already registered file set resolves to its current Work, even
after grouping. Overlapping a different registered set is refused; use catalog
grouping instead of assigning one source path to two representations.

## Availability and relocation

Asset identity is a source alias plus a relative path. Change only the alias's
configured directory and restart Stacks to relocate a mount. Missing or
unconfigured sources leave Works and personal state intact. Original availability
on a work page reports missing or changed files; downloads and playback refuse
unavailable originals. Traversal and symlinks escaping the configured root are
rejected.

Registration verifies SHA-256. Subsequent opens check size and modification time;
they do not hash a large audiobook on every range request. This detects ordinary
source changes, not byte modifications that deliberately preserve both observations.
The stored checksum remains available for source-snapshot verification. Keep
source folders read-only to Stacks and stable after registration.

## What a library backup contains

The ZIP contains the consistent catalog, all Stacks-owned managed originals, and
owned covers/cache. **Registered external original files are not in this ZIP.**
Protect those source folders separately with your filesystem/NAS backup or
snapshot policy. Manifest version2 declares the number of registered assets per
external root. It contains aliases, not machine-specific source directories.

Restore retains registered references and checksums even when a source is offline;
it verifies every managed original and the external-root declarations. Configure
the source aliases again after restoring, then check actual availability. Version1
managed-only backups remain supported. Schema0008/export8 include root-relative
locations and source observations. A catalog export contains no original files.

SQLite startup upgrades run in an explicit transaction, briefly disable foreign
key enforcement on the private upgrade connection for batch table replacement,
validate every relationship before commit, and restore enforcement afterward.
A failed migration rolls back table definitions and data together. This follows
[Alembic's documented SQLite batch constraint requirement](https://alembic.sqlalchemy.org/en/latest/batch.html#dealing-with-referencing-foreign-keys).
Automatic pre-upgrade snapshots and archive-scale backup scheduling remain part
of operational qualification; take a library backup before deploying upgrades.
