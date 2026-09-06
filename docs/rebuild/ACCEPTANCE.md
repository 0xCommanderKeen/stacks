# Release acceptance evidence

Snapshot: 2026-09-06, application and qualification work merged through
`101c2a18e3d8adafffa0db4ef4087e1998ed1a2a` (PR46). This is an evidence map, not a
release-complete declaration. Parent issues [8](https://github.com/0xCommanderKeen/stacks/issues/8)
and [9](https://github.com/0xCommanderKeen/stacks/issues/9) remain open.

“Verified” below means the named automated or qualification scope passed. It
never substitutes for actual-device or daily-use acceptance. CI run
[34053059310](https://github.com/0xCommanderKeen/stacks/actions/runs/34053059310)
passed 197 backend tests, 42 Chromium desktop/phone-viewport journeys, generated
contract checks, lint/type/build checks and the enhanced container restore smoke.
This acceptance slice adds the keyboard-only journey; both viewport runs passed
locally against the production build, bringing the suite to 44 browser journeys.

## Workflow and invariant matrix

| Required workflow or invariant | Implementation and evidence | State / limit |
| --- | --- | --- |
| New public repository; no Polica database migration | Separate Stacks history, [README](../../README.md), [domain model](../../CONTEXT.md); independent image/config/data | Verified repository structure; original installations retained |
| Import, find, correct and download an EPUB without renaming its original | [First slice](../first-book.md), `test_library.py`, `test_inputs.py`, first browser journey | Verified; first-slice operational notes are historical, later backup behavior supersedes them |
| EPUB/PDF/CBZ/CBR/MP3/M4A/M4B inspection | [Formats](../formats-and-series.md), `test_formats.py`; actual compressed CBR and media in container smoke | Verified representative fixtures; unsupported/encrypted/malformed input is explicit |
| Exact duplicates separate from editions and Works | [Grouping](../grouping.md), `test_operations.py`, format/narration browser journey | Verified explicit grouping/split/undo, conflict resolution, stable Representation/Asset IDs and redirects |
| Personal shelves, tags, ratings, notes and repeated reading/listening records | [Curation](../personal-library.md), `test_curation.py`, browser reload/scope journeys | Verified; personal state also survives fresh-container restore |
| Distinct comic runs, annual/special ordering and following | [Runs](../followed-series.md), `test_formats.py`, `test_series_reading.py`, comic/Home browser journeys | Verified run IDs, explicit designation/position, following and Archive overrides |
| Ordered collections and Home next-up | [Collections](../collections.md), `test_collections.py`, cross-page/navigation browser journeys | Verified stable membership/order and stale-edit guards |
| Chosen cover originals protected independently of thumbnails | [Covers](../chosen-covers.md), `test_covers.py`, [NAS restore](../qualification/recovery-nas.md) | Verified chosen original and selected identity survive backup, group/undo and cache rebuild |
| Incremental discovery, review, batch metadata and explicit audio grouping | [Inbox](../durable-inbox.md), [acceptance](../batch-acceptance.md), `test_inbox.py`, `test_acceptance.py`, `test_intake.py` | Verified durable paging/checkpoints, cancellation/retry, previewed acceptance and duplicate receipts |
| Real-source bulk intake without changing existing files | [NAS intake](../qualification/intake-nas.md) | 337 representative files / 16.229 GB registered; repeat duplicates, zero failures; read-only mount. Not whole-archive ingestion |
| Read-only registration, relocated/missing roots and immutable originals | [Sources](../read-only-sources.md), `test_sources.py`, [NAS recovery](../qualification/recovery-nas.md) | Verified path guards, retained catalog on missing/unreadable sources and byte access after remapping |
| Recoverable managed Trash and external visibility-only removal | [Trash](../recoverable-trash.md), `test_trash.py`, removal/restore browser journeys | Verified collision protection, per-asset journal and identity/curation retention |
| Process-crash recovery and explicit file failures | [NAS recovery](../qualification/recovery-nas.md), `qualify_crashes.py` | 17 actual SIGKILL checkpoints, injected ENOSPC/EACCES, real synthetic collision/change/missing-root/permission cases. Not NAS power loss |
| Audio tracks/chapters, seek/speed, navigation continuity and revised resume | [Audio](../audio.md), `test_reading.py`, browser audio/stale-device journeys | Verified automated single/multi-track behavior, backwards seeks and one-winner revision conflicts; actual phone acceptance open |
| Audio and progress remain usable during catalog/intake work | [NAS scale](../qualification/scale-nas.md) | 658 Range reads succeeded; explicit follow-ups at both scales saved all 5/5 progress writes and matched the final asset/position during active intake; short desktop playback only |
| Whole-catalog search, SQL pagination and useful grid at 50k/100k | [NAS scale](../qualification/scale-nas.md), `qualify_scale.py`, `qualify_grid.mjs` | Catalog p95 148/246 ms; search p95 505–559 ms / 2.2–2.4 s under differing browser overlap. 500 ms is now a reference, not a blocker. 100k grid exceeded the 2 s reference under load; documented, no hidden optimization claim |
| Authentication, mutation protection and separate reader authority | `test_inputs.py`, `test_devices.py`, [reader access](../reader-access.md), fresh-container old-session denial | Verified owner sessions, protected mutations, scoped/revocable reader credentials; credentials excluded from portability |
| OPDS navigation/search/covers/acquisition and original downloads | [Reader access](../reader-access.md), `test_devices.py`, connect/revoke browser journey | Implemented and protocol-tested; no actual external reader app has been certified |
| Optional provider suggestions with provenance and protected corrections | [Metadata](../metadata-suggestions.md), `test_enrichment.py`, provider-preview browser journey | Verified explicit bounded Open Library lookup/acceptance, manual-value protection and no provider dependency for import |
| Health, backup history and queued recovery downloads | [Recovery operations](../backup-recovery.md), `test_maintenance.py`, Settings browser journey | Verified root/free-space/job health, archive history and native downloads |
| Full backup restores originals, catalog and personal state into a fresh container | [NAS recovery](../qualification/recovery-nas.md), enhanced `container_smoke.py` | Verified relocated read-only source, stable IDs, notes/rating/tags/collection, chosen cover, audio progress/Range, rebuilt caches and rejected old session |
| Catalog-only recovery declares missing publication media | [Recovery operations](../backup-recovery.md), `test_maintenance.py` | Verified chosen-cover originals retained and explicit consent/marker for omitted publication media; separate source protection still required |
| Populated successor upgrades have a pre-upgrade recovery point | `test_formats.py`, `test_maintenance.py`, [recovery operations](../backup-recovery.md) | Verified populated upgrade scenarios, private snapshot and fail-before-schema-change behavior; this is successor maintenance, not Polica migration |
| Portable versioned catalog preserves all relationships and IDs without unbounded materialization | [Portable catalog](../portable-catalog.md), `test_portable.py`, [NAS scale](../qualification/scale-nas.md) | 50k/100k round trips: zero table mismatches, valid integrity/FKs, no authority; export/import peak RSS below 78 MiB. Media bytes deliberately separate |
| Responsive built UI and direct/navigation URLs | `frontend/tests/library.spec.ts`, [NAS scale](../qualification/scale-nas.md) | 42 desktop/phone-viewport journeys; real Chromium grid measurements. Phone viewport is not Safari/physical-device acceptance |
| Keyboard access | Keyboard-only browser journey: Tab/Enter login, search, book detail, cancelled edit, Settings/Library and logout; existing audio slider key checks | Verified in desktop and phone-sized Chromium; every target reached through Tab and checked in the viewport. Not physical keyboard/assistive-technology certification |
| Fresh persistent installation, configured roots/backups and chosen-file adoption | [Plan §9](PLAN.md#9-fresh-setup-and-adoption), [README](../../README.md) runbooks | Open: Mac review preview is disposable sample data, not persistent adoption; installation target clarification pending |
| Required personal workflows on actual reader/phone, then daily use | [Plan §4](PLAN.md#4-product-scope), [reader access](../reader-access.md), [audio](../audio.md) | Open: primary apps/devices and owner UI feedback requested; do not infer completion from automation |

Backend test references above are files under [`backend/tests`](../../backend/tests).
The browser journeys are in [`frontend/tests/library.spec.ts`](../../frontend/tests/library.spec.ts).
Qualification reports include image IDs, limits, aggregate data and methodology.
No private passwords, library titles or absolute original paths belong in this map.

## Conditional scope

Kindle SMTP delivery, conversion and built-in EPUB/comic readers remain conditional
on confirmed owner habits, as the original plan specifies. They are **not** marked
implemented or accepted. If selected, implement and test the real configured path
before adoption; ambiguous SMTP outcomes must remain unknown until an explicit
resend decision. Optional physical reorganization, statistics, automatic gap
finding, native apps, additional providers and cross-format progress are deferred.

## Remaining sequence

1. Incorporate the owner's review of the live Mac UI.
2. Confirm the actual reader/phone apps and persistent installation target. The
   owner questioned NAS use after seeing benchmark screenshots; the Mac is now
   the review environment, and NAS production rollout must wait for clarification.
3. Configure the selected installation with its own database, media root, login
   and tested backup destination. Use a small chosen selection through ordinary
   intake, preserving existing source files and installations.
4. Verify real delivery/playback/resume and daily use, then close parent gates.

The full goal stays incomplete until those applicable gates are evidenced. A full
2 TB hash pass is not required to launch with a smaller verified selection.
