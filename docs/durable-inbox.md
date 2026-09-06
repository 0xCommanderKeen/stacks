# Durable Inbox discovery

Inbox discovers configured read-only sources without creating catalog works or changing original files. Choose a source alias and optional relative folder, then start a scan. The page shows saved job progress and paged file candidates; it is safe to navigate away or restart Stacks. Batch metadata editing and acceptance are the next intake slice, tracked under #22.

Each source-relative file has one stable candidate identity. Internal file aliases resolve to the same identity. Directory symlinks are skipped to avoid cycles; files escaping their configured root become explicit errors. Rescans revisit previously seen paths under the chosen prefix, so missing originals become visible rather than silently retaining a ready state. Missing roots never delete catalog facts or files.

The worker stores directory checkpoints and per-candidate job items in SQLite. It streams at most 32 directory entries and inspects at most one file in each step. A restart replays the interrupted directory; unique directory, candidate, and job-item keys prevent repeated records and counts. Existing candidates are added to rescans with an SQL insert/select, without loading the source tree or every candidate ID into application memory.

Files modified in the last 30 seconds wait for retry. Stable candidates receive extracted raw facts and a full SHA-256 checksum. Device, inode, size, modification time, and change time must match before and after inspection/hashing. A changed file waits for a later retry. Parser subprocesses retain the existing 30-second timeout and resource limits. Hashing checks cancellation and shutdown between 1 MiB chunks. Raw facts and accepted edits have separate storage; discovery does not overwrite accepted metadata.

Candidate states:

- `pending`: discovered and awaiting inspection.
- `ready`: inspected ebook/comic with no matching catalog original.
- `review`: inspected audio whose recording boundaries need confirmation.
- `duplicate`: a catalog asset has the same SHA-256 checksum. The evidence identifies its current work; matching titles alone never create duplicates or merge works.
- `waiting`: recently written or changed during inspection; retry when stable.
- `error`: damaged, unsupported, missing, or unsafe file; correct the source problem and retry.

Jobs report discovered files, completed inspections, pending files, skipped entries/waiting files, failed files, and remaining directories. A completed scan can contain exceptions; completion means its current pass finished. Retry preserves completed checkpoints and reprocesses waiting/error items. Start a new scan to enumerate source changes again. Cancel persists immediately and stops at a checkpoint; current parser inspection may finish first. Shutdown signals and joins the worker before closing the library database. One process owns the library and one worker executes intake work.

Catalog locks cover only short SQLite mutations. Source enumeration, extraction, hashing, and waiting happen outside that lock, allowing catalog and listening-progress writes to continue. The catalog backup includes durable jobs, checkpoints, candidates, and raw facts; it excludes registered source-original bytes. A restored running scan resumes against reconfigured root aliases. Portable export version 9 includes the four intake tables and aliases even when no original has been accepted. No configured absolute host paths are exposed in job errors or exports.

Verification covers restart mid-directory, idempotent rescans, SQL paging, duplicate checksum/current-owner evidence, symlink aliases and escapes, recently modified and changing files, missing paths/roots, cancellation/retry, concurrent catalog writes, graceful shutdown, backup/restore, authenticated APIs, and the built desktop/phone Inbox workflow. Phone browser emulation does not establish actual-device acceptance.
