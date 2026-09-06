# NAS recovery qualification — 2026-09-06

The deployment image recovered all 17 instrumented process-crash cases and four
storage-fault cases, retained external registrations through missing-root and
permission failures, and restored a full backup into a fresh container with
relocated source roots and empty derived caches. These are disposable synthetic
fixtures; no existing library originals or application installations were changed.

Application commit: `1cf2943e106a53e956503d0c40e336518754e824`.
Image: `stacks:qualification-1cf2943`, ID
`sha256:fb9783dc470cda9a60f34788f75792c8f690c472876829d2810204c58e05f24c`.
The Linux amd64 containers run as UID 10001 with two CPUs and 2 GiB RAM. The crash
container has no network and mounts only a fresh data volume plus the harness
read-only. The fresh/restore HTTP smoke binds ephemeral ports on NAS loopback;
its external source mount is read-only. Its disposable containers and volumes
are removed after verification. Crash evidence remains in its dedicated volume.

## Actual process termination

`scripts/qualify_crashes.py` creates a fresh catalog for each case. It runs the
operation in a separate process and sends that process SIGKILL at an instrumented
checkpoint. The parent requires the actual `-SIGKILL` exit status, verifies a
staged/managed original survives, and opens a new Library to recover. It then
checks original bytes, identity, duplicate behavior, SQLite integrity and foreign
keys. This is actual process termination, not an exception that runs cleanup.

| Operation | Checkpoints exercised | Passed |
| --- | --- | ---: |
| Import | Stage synced before journal; journal committed; directory renamed; managed directory synced; catalog committed | 5/5 |
| Trash | Request queued; exclusive link created; destination directory synced; source unlinked; source directory synced; file receipt committed | 6/6 |
| Restore | Same six move checkpoints, restoring a previously trashed original | 6/6 |

A pre-journal import correctly has no catalog entry on restart; its orphaned
stage is cleaned and a fresh import succeeds. Journaled imports recover the same
Representation identity. Repeated import creates no extra Work. All Trash and
restore cases converge, retain Work/Representation/Asset identities, and return
the original to readable Library storage. The comparison includes originals
stored under extensionless Trash asset names.

These cases do **not** simulate NAS power loss, filesystem-cache loss or storage
controller behavior. They test application process recovery at selected file
checkpoints. They do not claim every possible machine instruction was interrupted.

## Storage failures

| Fault | Method | Observed result |
| --- | --- | --- |
| Full storage | Inject `ENOSPC` at exclusive link creation | Explicit error, source retained; retry after restart completes |
| Link permission denial | Inject `EACCES` at exclusive link creation | Explicit error, source retained; retry after restart completes |
| Destination collision | Create an unrelated byte-identical destination inode | Neither file overwritten or deleted; explicit error; retry after removing only the fixture collision completes |
| Changed original | Replace the managed fixture bytes before relocation | Explicit error; unexpected bytes retained; retry succeeds after restoring the synthetic original |
| Missing source root | Rename the synthetic external directory away | Registration retained; remapping the alias restores byte access with the same identity |
| Unreadable external file | Actual mode-000 file under unprivileged UID | Read raises permission error; catalog retained; restoring read permission restores identical bytes |

`ENOSPC` is simulated; the NAS filesystem was never filled. The actual permission
case affects only one synthetic file. Every recovered catalog passes integrity
and foreign-key checks. The combined NAS crash/storage suite took 52.396 seconds.

## Fresh-container full backup restoration

`scripts/container_smoke.py` now covers personal state and media recovery together:

1. Start a fresh instance and import synthetic EPUB, CBR, MP3, M4A and M4B files.
   Register a separate read-only external EPUB.
2. Correct a title, set notes/rating/tags, select a PNG cover original, add the
   Work to a collection, and save M4B position 3.25 seconds at speed 1.25.
3. Take the full recovery archive through the authenticated API.
4. Restore into a distinct fresh volume/container. Mount the same external bytes
   at a different container path under the same stable alias.
5. Remove only the fixture's derived `cover.jpg` and `thumbnail.jpg` caches.
   Rebuild offline from verified original media and chosen cover bytes.
6. Verify managed and external byte identity, stable catalog IDs, all personal
   values and membership, selected cover original/thumbnail, saved audio state,
   a real audio Range response and built frontend JavaScript.
7. Verify both unauthenticated access and the pre-backup login cookie are rejected
   before issuing a new login on the restored instance.

Four derived thumbnails were removed and all four rebuilt. Three representations
have no embedded cover; zero originals were unavailable. Both fresh and restored
instances passed. This proves the tested full-backup recovery path; a catalog-only
backup still requires separately protected original media, as its UI explains.

## Running the checks

Use only fresh disposable paths. Install locked dependencies for local execution:

```sh
python scripts/qualify_crashes.py --root /tmp/stacks-new-crash-fixture
python scripts/container_smoke.py stacks:qualification-1cf2943 /tmp/stacks-new-restore-report.json
```

The crash command refuses an existing root. It requires a non-root process for
the actual mode-000 permission check. When bind-mounting the harness into the image,
make that synthetic script readable by UID 10001; a mode-0600 host script prevents
execution. No broader source permissions need changing. The container smoke runs
on the Docker host because it uses loopback port discovery and local bind paths.

Aggregate evidence: [recovery-nas-2026-09-06.json](recovery-nas-2026-09-06.json).
Scale/portability and real-source intake are separate qualification reports.
Fresh production adoption and actual reader/phone/daily-use acceptance remain
open; these results do not claim completion of the entire release plan.
