# NAS intake qualification — 2026-09-06

This bounded real-file run qualifies the intake throughput portion of #22/#7.
The aggregate machine-readable report is `intake-nas-2026-09-06.json` beside this
file. Private paths, titles, inventory manifests and originals are excluded.

## Environment and selection

- Docker 29.4.3 on the x86_64 NAS; current-main image revision
  `7cf9f93cdc67bdc26614dc53f01844200a63d36f`, catalog schema 11.
- Image digest: `sha256:2ead25674c8295b39639908bd6f4f669a7aed453f38fc31754a8c933057e3d9a`.
- Disposable named catalog volume, source bind mounted read-only, no network,
  no exposed ports, 2 CPU and 2 GiB memory limits. Existing services unchanged.
- Deterministic selection of 56 bounded leaf directories: 337 originals,
  16,229,383,396 bytes. CBR 194, CBZ 96, EPUB 27, PDF 17, M4B 1, MP3 2.
- The full read-only inventory counted 38,692 supported files. This is a selected
  sample, not a full-archive benchmark or a claim about all file variants.

The default image UID could not traverse protected source directories. Running
with the source owner's UID/GID resolved that without changing source permissions.
A new Docker volume initially inherited the image's UID; only that disposable
volume was assigned to the selected runtime UID, using `volume-nocopy` for the
ownership helper. Both early permission failures preceded intake. Deployment must
provision a writable data volume and use an identity that can read source mounts.

## Procedure and results

`scripts/qualify_intake.py` uses ordinary scan, saved acceptance, registration,
rescan and repeat-acceptance code against a fresh catalog. Source files retain
normal stability checks. During discovery and acceptance it stops the worker,
closes the catalog and recreates both in the same Python process, exercising
persisted checkpoints. This is a graceful worker/catalog restart, not a container
kill, host power loss or ungraceful process interruption.

All 337 files were eligible: 334 Ready and three Review audio files. For this
disposable measurement each audio file was explicitly accepted as an individual
recording. Real adoption still requires the owner's intended recording boundaries.
The test registered external originals; it did not copy the collection into Stacks.

| Phase | Seconds | Catalog query p95 | Maximum query |
| --- | ---: | ---: | ---: |
| Discovery | 307.896 | 6.33 ms | 98.44 ms |
| Acceptance | 345.369 | 35.12 ms | 259.12 ms |
| Rescan | 5.301 | 39.52 ms | 43.54 ms |
| Repeat acceptance | 317.848 | 34.65 ms | 91.44 ms |

Discovery averaged 1.09 files/second; acceptance averaged 0.98 files/second.
Repeat acceptance verifies bytes again, explaining why it is slower than rescan.
There were 337 accepted works, zero failed or remaining acceptance items, then
337 duplicates and zero new works on repeat. All 337 original assets remained
registered externally, with zero managed originals and zero asset/candidate hash
mismatches. Source size, modification/metadata times, device and inode observations
were unchanged before and after; the read-only mount prevented Stacks writes.
This is not a separate before/after full hash of every source file.

Search timings measure an in-process `Library.list(q="a", scope="all", limit=24)`
call approximately every 200 ms while jobs run. They exclude HTTP, rendering and
cover delivery and query a catalog growing only to 337 works. They do not qualify
the 50k/100k warm-search or useful-grid targets, nor concurrent audio playback.

## Repeating the bounded test

Prepare a private JSON list of relative source directories and run the script
inside the built image with read-only source and disposable writable data mounts:

```sh
python /opt/qualify_intake.py --source /source --prefixes /opt/prefixes.json \
  --data /data/catalog --report /data/result.json --revision IMAGE_COMMIT \
  --max-files 500 --timeout 3600
```

The catalog and report must not exist and must be outside the source. Selection
is bounded to at most 2,000 files; the default is 500. The timeout is per phase.
The script retains the disposable catalog for failure inspection. Report output
contains aggregate counts/timings only. Keep input manifests and failure logs
private because underlying filesystem errors can contain source paths.

The checked-in script adds cleanup on failure and explicit completeness/bounds
checks after the measured run; these do not change successful intake operations
or timing measurement. Its synthetic regression runs the full six-EPUB workflow,
checks duplicate identity and rejects source-write destinations/excessive samples.

Earlier merged regression suites cover changed files, unavailable roots, bounded
paging, cancel/retry, journal recovery, collisions, permission errors and disk-full
faults. Those synthetic tests plus this sample support the intake milestone.
Large-catalog/HTTP/grid/audio load, crash recovery in a fresh container, deployment,
physical reader playback and daily-use acceptance remain the qualification phase.
