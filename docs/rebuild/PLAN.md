# Stacks: clean-start implementation plan

Date: 2026-09-06. Status: implementation proposal; application development and deployment have not started. Owner decisions: start from scratch with no migration; name the app Stacks and the repository `stacks`; make the repository public.

## 1. Recommendation

Build Stacks in a new public repository named `stacks`. The owner has selected Stacks as the app name and `stacks` as the repository name. Start with an empty database and freshly import chosen book/comic/audio files through the normal product workflow. Old metadata, curation, reading positions, IDs, integrations, and database history are not compatibility requirements. No legacy importer, reconciliation project, or bidirectional synchronization is needed.

Use one application with a few substantial modules, one database, one deployment image, and a web interface. Keep Python, FastAPI, Svelte, and SQLite unless an early implementation experiment exposes a concrete obstacle. Replace the file-centric domain model, metadata-driven automatic moves, and obligatory per-file review.

The rebuild succeeds when collecting, finding, organizing, and consuming books/comics/audio feels coherent and is dependable at archive scale. It does not need to reproduce every existing screen, nor does changing frameworks count as progress by itself. Starting fresh does not require deleting the old application or original files.

The decisive early deliverable is one complete workflow: import an EPUB, find it in the catalog, edit its metadata without moving its file, download it, restart the application, and restore a backup. Then exercise the model with comics and multi-file audio before expanding the feature set.

## 2. Evidence and assumptions

This proposal is based on the local checkout's models, catalog/export code, file mover, tests, frontend, README, original plans, and project memory. It is not an audit of the running deployment.

- The original plan assumed slow incremental ingestion and acceptable individual review. The current UI explicitly handles a large comic archive using series browsing and active/archive shelves.
- Project memory records approximately 38,000 items and 2.15 TB on the NAS. Inventory these again; they are planning estimates, not verified current counts.
- The local model combines descriptive metadata, physical storage, curation, and playback in `Item`. Folder audio uses additional tracks and a manifest hash.
- The local series uniqueness rule uses name and media type even though start year is stored. A successor must allow distinct runs with identical names.
- The README documents the historical Book/Item migration mismatch. The successor should not inherit that migration history.
- The existing implementation is a source of extraction logic, recovery scenarios, and product lessons. Its database and unfinished branches do not constrain the new design.

Planning defaults: one owner, NAS deployment, private network access, locally owned files, browser audio, device delivery, and no requirement to become a general media server. Old curation may be left behind, as explicitly authorized. Existing media may be used as fresh-import sources, but modifying or deleting that source collection is not part of this plan. Validate actual device habits before the corresponding release gate.

## 3. Repository and development strategy

### Why a separate repository

A new repository gives the successor its own schema history, issue tracker, releases, and deployment configuration. It avoids a long-lived rewrite branch repeatedly absorbing unrelated maintenance changes. With no compatibility requirement, there is no need to keep the two projects synchronized. Consult the old code only when a particular behavior or fix is relevant.

An isolated worktree in the existing repository could also avoid checkout conflicts. It would be a reasonable choice for an incremental refactor, but this is a clean product/schema start. A separate successor is clearer here. Separate repos do not prevent agents from conflicting within one checkout: separate task worktrees still matter.

### Concrete setup

1. Create a public `stacks` repository in a separate sibling checkout. Do not nest its Git repository inside this one.
2. Move this proposal and proposed glossary into the successor and mark decisions accepted as they are settled. Record only consequential tradeoffs as short ADRs.
3. Establish one check command, CI, image builds, a synthetic demo library, and feature-branch PR delivery. Exclude actual library material, databases, secrets, and private import reports from Git.
4. Leave old Polica available if useful, with maintenance performed only when needed. Do not backport new features or create compatibility adapters.
5. Use a separate worktree for each simultaneous implementation task. Sequence shared schema changes through a single reviewed migration head. Parallelize independent features only after their interfaces are stable.
6. Use separate service names, ports, databases, cache directories, and configuration. Never have the two applications write the same database or manage the same files concurrently.
7. Use Stacks as the permanent product name and `stacks` as the repository name. Keep the old Polica repository under its existing name; archiving it later is independent of launching Stacks.

Keep a short porting ledger for reused code: origin commit, behavior retained, changes made, relevant tests, and license/attribution obligations. Copy focused extraction and safety logic when useful; do not fork the whole application and then spend months deleting its assumptions.

## 4. Product scope

The product should answer five questions: What do I own? Where is it? What do I want next? How do I read or listen? Does anything need attention?

### Required for first dependable release

- Search the whole collection and browse a deliberately smaller library shelf.
- Browse comic runs in useful order, including annuals, specials, and repeated series names.
- Create and edit metadata, covers, tags, collections, ratings, notes, and reading records.
- Import both individual additions and large batches with clear progress and recoverable failures.
- Distinguish exact file duplicates, alternate formats, different editions, and genuinely different works.
- Download supported originals; provide the device delivery paths confirmed necessary in Phase 0.
- Play single-file and multi-file audio, seek, select chapters/tracks, and resume across sessions and devices.
- Back up, restore, export, recover interrupted operations, and report inaccessible files.
- Keep new import candidates and trashed material visible and recoverable.

### Deferred unless confirmed habits make them release requirements

Built-in EPUB/comic readers, elaborate statistics/goals, automated gap discovery, comic conversion presets, many enrichment providers, smart recommendations, offline browser downloads, native mobile apps, and cross-format position synchronization.

If the browser reader is the owner's preferred reading path, move it into required scope before adoption. Choose OPDS and Kindle conversion based on actual devices. Configure integrations fresh and create new saved views only if basic filters prove insufficient. Do not rebuild a feature merely because the old application has it.

No movies, TV, games, multi-tenancy, plugin platform, microservices, generic workflow framework, or AI dependency in the core import path.

## 5. Domain model

Canonical terms are in [CONTEXT.md](../../CONTEXT.md). These are internal concepts: the owner should normally see a book or comic page with available formats, not four entity editors.

### Identity and relationships

```text
Series --< SeriesMembership >-- Work --< Edition --< Representation --< Asset
                                 |
                                 +-- personal curation / collections / reading records

Progress belongs to a Representation.
Contributors have role-bearing credits on Works or Editions.
```

| Entity | Owns | Rules |
|---|---|---|
| Work | Recognizable book/issue/collected-volume identity, common description and authorship | Stable internal ID; never inferred solely from title |
| Edition | Language, publication details, medium, identifiers, recording/narrator/abridgement | Unknown details allowed; different narrations remain different editions |
| Representation | Format, playable/readable structure, representation-specific metadata | One usable file or ordered file set; explicit default for consumption |
| Asset | Storage root + relative path, byte size, hash, verification state | Stable asset ID; hashes identify content, paths identify locations |
| SeriesMembership | Series, work, displayed designation, explicit sort position | Labels such as `1/2`, `Annual 2024`, and `Special` need not parse as decimal |
| Contributor/Credit | Person/group identity and role at work or edition level | Two people may share a name; don't maintain a second writable author model |
| Personal state | Shelf, tags, ratings, notes, reading records | Curation survives missing files, reorganization, and backup restoration |
| Progress | Representation, asset/locator, offset, update revision | Never copy an EPUB locator into a PDF or assume text/audio alignment |

Start with relational tables and ordinary constraints. Do not build a universal graph or a generic entity/attribute/value store. Four identity levels earn their place through real multi-format and multi-track cases; add no further bibliographic layers without evidence.

### Specific choices that avoid future ambiguity

- A scanned comic and a digital comic can be representations of the same edition only when their edition/content equivalence is established. Similar titles do not prove it.
- A collected volume is its own work. Linking the individual issues it contains is optional later; do not explode one imported omnibus into many invented records.
- A work can appear in more than one series. Collections represent personal reading orders without forcing a full comics-universe model.
- Series IDs are authoritative. Name, year, publisher, and provider identifiers help matching but are not individually universal identifiers.
- Shelf selection lives on the work. Following lives on the series. Following can explicitly promote its existing works and set the default for future imports, but individual archive choices remain overrides; unfollowing does not silently undo those choices.
- Ratings and notes default to work-level curation. Edition-specific observations can remain associated with an edition. Regrouping records must not silently overwrite conflicting values.
- Progress is representation-specific. Reading records preserve the distinction between reading and listening, and allow re-reading. The UI can summarize both at work level without marking an unfinished audiobook finished because its ebook was read.
- Store saved locator data together with representation identity and locator type/version. Future reader changes must explicitly handle locator compatibility rather than guessing equivalent positions.
- Avoid shared physical assets across representations initially. Identical hashes are duplicate candidates, not automatic deletion authorization. Shared storage would add reference-counting and deletion complexity before it provides much value.

### Safe matching and regrouping

Import conservatively: an unrecognized file or confirmed audio group creates one work, one edition, one representation, and one or more assets automatically. Group with existing records only on explicit, reliable evidence; offer ambiguous matches for review. The result can contain separate cards temporarily, but preserves distinctions.

Implement merge/split as deliberate catalog operations with previews before mass regrouping. Conflicting curation requires explicit resolution. Keep redirect mappings for superseded IDs and an audit record sufficient to undo the operation. Physical files stay unchanged.

## 6. Storage and import

### Separate descriptive changes from physical changes

The database owns accepted metadata and relationships. The filesystem owns original bytes. Paths are recorded locations, not identities and not a permanently synchronized rendering of metadata.

Support two explicit intake modes through the same catalog workflow. Register-in-place indexes files in a read-only source root without copying them; this is useful for a large existing archive. Managed import copies new files into successor-owned storage. Start with managed import on a small sample, then add register-in-place before loading the full archive. Neither mode reads the old database.

Managed imports receive a readable initial folder name with a stable identifier, for example `managed/<representation-id> - <initial-label>/...`. Later title corrections do not move it. Read-only registered files remain where they are. Removing them from the catalog never deletes their source bytes; restoring catalog visibility is supported. Managed representations can be moved into recoverable trash. These different storage permissions are visible where a user takes a destructive action.

Storage roots have configured locations and read/write capabilities; assets store relative paths. Changing a mount point updates a root mapping. Imported paths must stay within approved roots after normalization and symlink resolution. Missing mounts must produce an unavailable-root state rather than thousands of deletions.

Optional physical organization is a separate operation: preview destination and conflicts, confirm the concrete plan, execute with a journal, verify, and recover after interruption. It is deferred until after the first release. Keep original bytes immutable through extraction, enrichment, and conversion; generated formats and thumbnails are derivatives.

### Import workflow

1. Discover files incrementally, waiting for uploads/copies to finish. Polling and manual scans remain sufficient initially.
2. Recognize one-file representations and ordered audio sets. Ambiguous folder grouping needs review; don't assume every directory is one audiobook.
3. Hash and extract metadata with bounded concurrency. Recheck size/mtime or stronger stability evidence to catch files that changed while inspected.
4. Record extracted facts separately from accepted metadata and proposed matches.
5. Classify as ready, duplicate candidate, needs review, or error, with actionable reasons.
6. Auto-import only when file grouping and the chosen policy are unambiguous. Unknown metadata is allowed; guessing a confident-looking title is not required for acceptance.
7. For new managed files, copy to staging, make durable, verify hashes, publish to the managed location, and commit catalog state through a recoverable operation. Source cleanup is a separate recorded step after a verified destination exists. Never overwrite a destination on a name collision.
8. Regenerate derived covers/search documents and expose the result immediately.

Rescanning or retrying the same candidate must not create extra records or repeat completed file operations. Duplicate detection is byte-based; edition/work matching uses separate evidence. Cancel takes effect at a safe checkpoint. Report completed, remaining, skipped, and failed counts and allow targeted retry.

Use a small database-backed jobs table and one bounded executor in the application initially. Persist checkpoints and recovery state; serialize file mutations per representation. Do not build a generic job platform. Media parsing and hashing must not block catalog requests or audio delivery.

### Metadata policy

Prefer embedded facts to filename guesses. External enrichment proposes changes, including provenance, without requiring network access to import. Manual corrections and chosen covers remain protected from later refreshes. Use a compact field-origin record and selected-value flag; a complete event-sourced metadata history is unnecessary.

Archive extraction needs path, entry-count, expanded-size, time, and resource limits. External fetches need destination restrictions and bounded downloads. Retain existing tests for these real input surfaces when porting extraction logic.

## 7. Application architecture and stack

Recommended stack: Python/FastAPI, SQLAlchemy with Alembic, SQLite on a local NAS volume, and a SvelteKit static web build served from the same application image. Choose and lock supported versions at implementation time rather than copying broad ranges from the old project.

Keep SQLite because the database contains catalog metadata, not terabytes of books, and the proposed workload has modest write concurrency. Keep transactions short and file/network work outside them. Reconsider a server database only if measured contention or multi-host requirements justify it. SQLite documents both this application-server use and its single-writer/network-filesystem limitations. [SQLite guidance](https://www.sqlite.org/whentouse.html)

Change the persistence layer to eliminate the existing Tortoise-specific schema-history compromise and make migrations explicit. This is a project design recommendation, not a claim that Alembic makes migration risk disappear: generated migrations still need review, and renames are not reliably inferred. Test populated upgrades and restoration, not only empty-schema creation. [Alembic migration guidance](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

Retain Svelte to avoid an unrelated frontend rewrite experiment. A static SPA suits this authenticated personal application; accept its initial-load tradeoffs and test direct deep links and asset serving. [SvelteKit SPA guidance](https://svelte.dev/docs/kit/single-page-apps)

### Modules and their interfaces

| Module | Small interface offered to callers | Complexity it owns |
|---|---|---|
| Catalog | Search, retrieve, edit, group/ungroup | Domain constraints, relationships, search queries, metadata provenance |
| Ingestion | Discover, inspect, accept batch, retry | Format extraction, grouping, hashes, duplicate candidates, checkpoints |
| Storage | Resolve asset, publish verified import, trash/restore, inspect health | Root mapping, path safety, journaled mutations, recovery |
| Reading | Get/update progress, record reading, select next | Locator types, revision conflicts, reading history, curation rules |
| Delivery | Download, stream, send to configured device | Ranges, ordered audio, OPDS, delivery status, optional conversion |

Backup, configuration, database setup, and job execution are shared implementation support, not a platform layer. Enrichment providers sit behind one concrete suggestion interface inside Catalog/Ingestion. Format extractors share the inspection result shape because there are already multiple real formats.

HTTP handlers validate requests, invoke these interfaces, and return explicit schemas. They do not rename files or duplicate domain rules. Modules own their writes; do not add generic repository/service wrappers for every table. Generate frontend contract types from the server schema and verify generation in CI. Media actions depend on the selected representation and actual installed support, not media type alone.

Use ordinary synchronous transactions executed outside the request event loop where needed. Start with one application server process plus bounded background execution; document that deployment assumption. Introduce additional processes only with explicit job claiming and concurrency tests.

### Operations

- One container image, persistent database/config volume, separate library roots and disposable cache.
- Apply versioned migrations as a controlled startup/release step after backup; fail readiness on schema mismatch.
- Authentication on catalog and content, protected mutations, scoped device credentials, secret redaction, and configured delivery destinations.
- Structured job/error logs, ready/live checks, storage availability, queue state, and last successful backup visible in Settings.
- Tested full backup bundle: consistent database, custom covers and other non-rebuildable assets, manifest, and recovery instructions. Original media requires a separate backup/snapshot policy; a database backup does not protect books.
- Versioned portable export including relationships, curation, progress, provenance, paths relative to roots, and IDs. Keep credentials separate from routine exports.
- Rebuildable search/thumbnail caches; chosen cover originals are backed-up data, stored separately from disposable thumbnails.

## 8. Interface plan

Primary navigation: Home, Library, Inbox, Collections. Settings contains health, backups, storage, and integrations. Archive is a library scope, not a competing application.

- Home: continue reading/listening, next issue in followed runs, and a small deliberate next-up selection. Avoid defaulting to the full import history.
- Library: Books, Comics, Audio; books grouped by work, comics by run, audio with recording/narrator context. Search can reach the entire archive with its scope made visible.
- Work detail: description, cover, personal state, available editions/formats, and a clear Read/Listen/Download/Send action for the selected representation.
- Series detail: ordered works, owned availability, progress, and next unread. Never equate the largest owned issue number with a verified publication count.
- Inbox: batches and exceptions; bulk edit common author/series/shelf fields, inspect duplicate evidence, preview acceptance, and retry failures.
- Persistent audio player: navigation does not interrupt playback; track transitions, speed, seek, and resume work on the actual phone/browser used.

Paginate on the server, query and sort in SQL, load cover thumbnails lazily, and retain navigation/filter state in URLs. A request must not load every matching ID into application memory to page results. Mobile layout and keyboard access are acceptance requirements, not a final cosmetic phase.

## 9. Fresh setup and adoption

There is no old-database import, legacy-ID map, curation reconciliation, final database handoff, compatibility export, or state synchronization. Future schema upgrades within the successor still need normal versioned migrations and backups; those are ordinary maintenance, not a migration from old Polica.

### First setup

1. Start a fresh container with an empty database and its own managed media directory.
2. Configure the owner login, storage roots, and backup destination.
3. Import a small representative selection through the ordinary inbox. Choose the initial shelf: active for deliberate additions, archive by default for bulk loads.
4. Verify the complete book/comic/audio workflows on the actual devices.
5. Register larger source directories read-only if avoiding a second multi-terabyte copy is desirable. This creates entirely new catalog metadata from the files.
6. Let extraction and hashing run in resumable batches. Correct common metadata by batch and review ambiguous grouping.
7. Start daily use when the release gates pass. Configure only the integrations actually used.

The old application can stay available separately, but its edits do not appear in the new catalog and new reading progress does not appear in the old one. If the old application still manages files being registered in place, pause its moves/ingestion or use a stable read-only snapshot of those files. A read-only mount protects against writes by the successor; it cannot prevent the old application from renaming a shared source.

### Failure recovery

During development, disposable databases and sample imports can be recreated freely. Once the owner starts creating new notes, metadata, and progress, preserve them with tested successor backups and export. A bad successor update is recovered using the previous successor image and a compatible backup, retaining a snapshot of newer data for recovery. No conversion back to the old schema is promised or required.

Do not delete the old installation or source collection as an automatic cleanup step. If storage is later consolidated, treat that as a separate verified file operation with explicit scope.

## 10. Delivery phases and acceptance gates

Phases are working vertical slices, each delivered through focused PRs. Begin the next phase when its prerequisites work; avoid a large backend-only build followed by a large frontend-only build. Calendar estimates should follow the first complete import experiment.

| Phase | Deliverable | Acceptance gate |
|---|---|---|
| 0 — Foundation | New repo, CI/image, glossary, representative corpus, workflow checklist | One documented command runs checks; fresh container starts; default device/reader paths identified |
| 1 — One complete book | Core schema, login, managed import, work page, search, metadata edit, download, backup/export | Import an EPUB, correct its title without moving bytes, download identical bytes, restart, restore backup |
| 2 — Prove the model | Comics, multi-format editions, audio inspection, run browsing, merge/split | Same-name runs stay separate; EPUB/PDF choices work; annuals sort correctly; multi-disc audio groups correctly |
| 3 — Daily consumption | Audio playback/progress, reading records, Home, shelves/archive, basic collections and notes | Read/listen/continue/choose-next journeys work on desktop and phone; stale progress cannot overwrite newer progress |
| 4 — Archive-scale intake | Register-in-place, batch metadata edits, duplicate review, durable jobs, managed trash/restore | Rescan creates no duplicates; large import resumes after restart; unavailable roots are reported without data deletion |
| 5 — Delivery and metadata quality | Confirmed device integrations, first enrichment provider, provenance and protected corrections | Real device receives/opens a book; external failure does not block import; refresh preserves manual edits |
| 6 — Release qualification | Scale benchmark, failure injection, backup restoration, visual QA, deployment runbook | Release gates below pass using the deployment image on the NAS |
| 7 — Adoption | Fresh production install, chosen files imported/registered, integrations configured | Daily use works, backups restore, and remaining import exceptions are visible and actionable |

Basic visual quality, accessibility, authentication, and recovery belong in each phase. Phase 6 verifies them together rather than introducing them at the end. File safety is part of Phase 1; Phase 4 expands it to bulk work and more failure cases.

### Initial issue-sized slices

1. Create repository scaffold, image, CI, synthetic corpus, and run/check commands.
2. Build the initial schema and complete import-one-EPUB/search/download workflow.
3. Add metadata editing independent of storage paths, backup/restore, and portable export.
4. Add CBZ/CBR/PDF inspection and comic run browsing with annual/special ordering.
5. Add alternate representations and deliberate grouping/ungrouping.
6. Inspect M4B and multi-file audio with stable asset order and chapter metadata.
7. Implement audio playback and revision-checked resume across devices.
8. Add shelves, following, reading records, notes/ratings, and basic collections.
9. Add read-only source registration and resumable bulk ingestion with batch edits.
10. Implement duplicate review, managed trash/restore, and missing-root behavior.
11. Add the chosen device delivery path and one optional enrichment provider.
12. Prove scale, failure recovery, backup restoration, mobile usability, and fresh NAS deployment.

These are a sequencing outline, not newly created tracker tickets. Each ticket should describe its visible result and acceptance evidence; split a ticket further if it cannot be reviewed coherently. Keep issue status synchronized with implementation/review and open a PR for each completed implementation task.

After Phase 2, stop and assess whether Work/Edition/Representation/Asset actually makes the tested journeys simpler. Resolve any model confusion there before building more screens. After Phase 4, measure a substantial real-file import before promising full-archive throughput.

## 11. Verification strategy

Reuse old regression scenarios where they test meaningful guarantees; rewrite tests against successor module interfaces rather than carrying ORM-specific test structure forward.

Representative corpus: EPUB/PDF variants, identical bytes under different names, same title by different authors, translations, two narrators, abridged/unabridged audio, one M4B, nested multi-disc MP3s, malformed archives, Unicode paths, repeated comic run names, annuals/specials, a collected volume, pending/trash/lost items, custom covers, conflicting curation, and saved reading positions created during tests.

Required exercises:

- Kill/restart at each durable import/move checkpoint; inject disk-full, destination collision, missing mount, permission failure, and changed-source-file conditions.
- Restore a backup into a fresh container with empty caches and relocated storage roots.
- Repeat fresh imports, rescans, retries, and register-in-place operations; verify stable identities and no duplicate catalog growth.
- Verify migrations against populated databases, with foreign-key and integrity checks and backup restoration.
- Test browser navigation during audio playback, range seeking, cross-device resume conflicts, and old/stale progress updates. Use revision checks so delayed updates cannot overwrite newer progress; backwards seeks remain valid user actions.
- Do not blindly retry a device email after an ambiguous SMTP result; expose unknown delivery status and an explicit resend action.
- Exercise actual client downloads/OPDS/Kindle paths selected for replacement. A passing mock cannot establish device compatibility.
- Test responsive UI with real viewport sizes, keyboard navigation, direct URLs, and the exact built production assets.
- Benchmark at roughly 50,000 and 100,000 catalog entries with a representative series distribution, while import runs. Proposed targets on the agreed NAS: warm catalog/search p95 below 500 ms, useful initial grid below 2 s on LAN, and no audio interruption caused by catalog/import activity. Record cold-cache results separately and revisit targets explicitly using Phase 4 measurements.

Release gates: successful imports have verified asset identities; incomplete imports and exceptions are explicit; new curation and progress survive restart/restore; required personal workflows pass; backup restores into a fresh install; production image and NAS behavior verified; no unresolved data-loss, corruption, or unauthorized-access defect. Completing a whole-archive hash pass is not required to launch with a smaller verified selection.

## 12. Reuse and deletion decisions

| Existing work | Treatment |
|---|---|
| Format extraction and embedded metadata parsing | Selectively port with representative fixtures and resource limits |
| Hashing, manifests, recovery logic and tests | Reuse invariants and proven details; adapt ownership to representation/assets |
| Backup and safe external fetching | Port useful logic and failure tests; include custom covers in backup scope |
| OPDS/SMTP/conversion code | Port after required device behavior is identified; keep conversions optional |
| Audio UI | Reuse interaction knowledge and appropriate code; replace item-index progress assumptions |
| Whole current schema/migration history | Leave behind; start a new schema history with no compatibility layer |
| Existing page architecture | Replace around tasks and grouped works; selectively reuse good visual primitives |
| Old movies/TV plan and compatibility naming | Leave in old repository; do not seed successor abstractions with it |
| Current tests | Keep meaningful behavioral scenarios; retire tests tied only to discarded structures |

## 13. Risks and decision checkpoints

- Over-modeling: validate the four identity levels with the representative corpus across Phases 1–2. Most import paths create defaults automatically; there must not be four manual forms.
- Rewrite drift: use Phase 2 as a stop/go gate. If ordinary books, comics, and audio require awkward special cases, fix the model before adding features.
- Incorrect automatic grouping: prioritize false-negative matches over false-positive merges. Use stable IDs and support deliberate regrouping.
- Scope creep: the workflow checklist governs the first release, not every feature in the old UI or old issue tracker.
- Archive size: measure hashing and extraction throughput early; checkpoint processing and use read-only registration to avoid an unnecessary full copy.
- Apparent simplification that moves complexity elsewhere: evaluate total application and operational burden. Removing the file journal would shrink code while making ownership of valuable files harder.
- Repeated rebuilding: export/import and stable identities are first-version features, so a future application can replace this one without reconstructing personal history.

Recommended next implementation action after repository setup: deliver Phases 0–1 as small PRs. The owner has explicitly removed migration from scope and approved a public repository. This plan does not imply that the application or its deployment has been implemented.
