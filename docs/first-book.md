# First book: scope and operational notes

Historical milestone: current additions are covered in [Formats and series](formats-and-series.md).

This slice implements the foundation and first complete EPUB workflow from the [rebuild plan](rebuild/PLAN.md). It is a development milestone, not the archive-scale release.

## What works

- A single owner signs in with a configured password; sessions survive restarts and are revoked on logout or password change.
- Upload one or several EPUBs from the browser. Embedded metadata and optional covers are inspected within resource limits. Exact file duplicates are recognized without merging similar titles.
- Each accepted EPUB creates a Work, Edition, Representation, and Asset with separate stable IDs. Contributor names do not act as global identities.
- Browse/search by title and author, paginate, open a book, edit title/authors/description, and download the exact original bytes. Metadata edits do not rename files. Concurrent stale edits return a conflict.
- Full backup includes the catalog, originals, and covers; JSON export includes all current catalog relationships and extracted metadata. Login sessions are excluded from backups/exports.
- Interrupted journaled publication resumes at startup or on re-upload. Bad/missing staged copies remain on disk and appear as an attention count; they are never silently removed.

Phase 0 defaults for this slice: EPUB download is the reading path, desktop and phone browsers are supported, and the server runs as a single process. Selection of actual OPDS/Kindle clients and browser readers remains a later release decision. No old Polica state is imported.

## Storage guarantees and limits

`STACKS_DATA_DIR` contains `catalog.sqlite3`, `managed/`, `staging/`, and the process ownership lock. The database is on a local filesystem. Do not put the live database on SMB/NFS, and do not run multiple app workers against the same root.

Uploads are disposable copies. The ingestion module hashes and inspects the upload, copies it into a unique stage, fsyncs and rechecks the bytes, and commits a journal row. It then renames that stage into managed storage and fsyncs directory entries before committing the catalog and marking the operation complete in one database transaction. Recovery examines the journal and disk state. No external source file is moved or deleted.

A stage with no journal row is an unfinished upload copy and is removed on startup. A stage or managed directory with a journal row is retained until its operation completes. If recovery reports an error, keep these files, check the storage problem, and restart. There is no bulk recovery/repair screen yet. Full backup refuses unresolved imports or missing/changed originals so it cannot claim to be a complete restorable library.

Physical names use stable representation IDs. In this slice there is one `original.epub` per representation and an optional derived `cover.jpg`. The shape allows ordered assets later; alternate editions/formats and audio are not yet exposed.

Backup holds the mutation lock while copying. This is appropriate for the initial small library but must evolve before archive-scale use. The web backup downloads a full ZIP including originals and therefore needs free temporary disk space and browser memory approximately proportional to the library size. Use the offline CLI for larger local backup files; incremental backup and background maintenance belong to later phases.

## Verification

`make check` runs Python lint/format checks, backend integration tests, generated-contract drift detection, Svelte/TypeScript checks, frontend formatting, and the production build. `make test-browser` runs Chromium desktop and phone viewport journeys against a disposable real server serving the production build. It is not Safari or physical-device certification.

`uv run python scripts/container_smoke.py stacks:test` starts disposable containers, imports and edits an EPUB, verifies exact download bytes and JavaScript content types, creates a backup, restores it through the packaged CLI, and verifies the catalog and original bytes in a second container. The script removes only its own temporary containers and volume.

The synthetic corpus is original Stacks test content. It does not certify every third-party EPUB or DRM-protected publication. XML external entities, archive traversal, ambiguous ZIP entries, oversized metadata, upload limits, duplicate retries, interrupted publication, schema drift, stale edits, and tampered backups have dedicated coverage.

## Next slice

Prove the model with comics, repeated run names, annual/special ordering, alternate representations, and multi-file audio inspection before adding broad curation or enrichment features. Real NAS scale and actual reading-device acceptance remain Phase 6 release gates.
