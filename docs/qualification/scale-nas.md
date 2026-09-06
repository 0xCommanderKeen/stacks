# NAS catalog-scale qualification — 2026-09-06

Stacks was measured on the NAS using the production image built from
`1cf2943e106a53e956503d0c40e336518754e824`. The owner revised the proposed
500 ms search p95 target during qualification: it is a reference, not a release
blocker. We retain the measured latency rather than adding complexity solely to
cross that threshold. This report does not establish physical-device acceptance
or a complete production release.

## Environment and fixture

Image `stacks:qualification-1cf2943`, image ID
`sha256:fb9783dc470cda9a60f34788f75792c8f690c472876829d2810204c58e05f24c`,
Linux amd64, UID 10001, limited to two CPUs and 2 GiB RAM. Separate disposable
named volumes held the catalog and synthetic fixtures. Fixtures were mounted
read-only by the web service. No existing library originals were mounted and
no existing application was replaced. Only one benchmark web service ran at a
time; it was stopped before offline portability measurements.

The two datasets contain 50,000 and 100,000 synthetic Works, plus one imported,
verified 20-second M4B. Distribution: 80% comic, 18% ebook, 2% audio; 10% Archive;
75% use a shared small derived JPEG. Each Work has an author from 1,000 contributors.
Series contain 5–25 comic entries, with 2,000/4,000 distinct runs and repeated names.
Ten percent of Works belong to collections. All synthetic creation timestamps
are equal, deliberately exercising a large ordering tie. Real imports normally
have different timestamps. The artificial catalog rows reference absent originals;
this measures catalog scale, not discovery or hashing of 100,000 media files.
Five hundred generated EPUB files exercise actual bounded intake separately.
Seeding took 10.347 and 22.170 seconds respectively.

## HTTP and browser results

Requests traveled over the LAN from a separate Mac using authenticated HTTP.
Each of eight queries ran 30 times, sequentially within each round, while a
separate thread requested 64 KiB audio ranges every 250 ms. A new intake scan
started before the warm query loop. Times include reading the complete HTTP body.
Percentiles select sorted sample index `floor(n * .95)` (zero-based, capped at
`n-1`); with 30 samples this is the second-highest observation. These small
samples describe this run, not a latency guarantee.

| Request | 50k median / p95, ms | 100k median / p95, ms |
| --- | ---: | ---: |
| Library catalog, 24 entries | 93 / 148 | 151 / 246 |
| Common author search | 475 / 559 | 1,055 / 2,358 |
| Title substring search | 421 / 505 | 945 / 2,226 |
| Missing search | 447 / 519 | 977 / 2,330 |
| Archive, 24 entries | 223 / 318 | 508 / 1,009 |
| Series, 24 runs | 213 / 299 | 480 / 1,013 |
| Collections, 24 entries | 38 / 116 | 39 / 103 |
| Collection Works, 24 entries | 42 / 106 | 46 / 122 |

The 100k browser navigation/playback measurement ran concurrently with the HTTP
run. Overlap with the 50k browser run was not recorded, so the two runs are not
an isolated scaling comparison. At 100k, a sampled Docker reading during load
showed 201% CPU and 188 MiB memory. At 50k a sampled reading showed 100% CPU and
158 MiB. These are observations, not peak memory measurements.

At 50k, all 199 audio ranges succeeded (p95 119 ms). Intake had processed 274/500
files with zero failures when the HTTP measurement ended. At 100k all 459 audio
ranges succeeded (p95 132 ms); intake completed all 500 files without failures.
Intake therefore did not necessarily overlap every final query sample.

Chromium desktop used a 1365×900 viewport and a fresh authenticated context.
Navigation timing ended when 24 catalog tiles and their available cover images
had loaded; it includes tiles below the fold. One fresh-browser-cache navigation
was followed by 15 warm navigations. No JavaScript page errors were observed.

| Grid navigation | 50k | 100k |
| --- | ---: | ---: |
| First navigation | 0.688 s | 2.182 s |
| Warm median | 0.811 s | 1.835 s |
| Warm p95 / maximum (15 samples) | 0.837 s | 2.363 s |
| Loaded cover images among 24 tiles | 17 | 18 |

The 100k grid exceeded the proposed two-second reference under concurrent load.
Catalog paging remained responsive; search visibly takes longer at this scale.
No application optimization was introduced for this qualification. Read-only
SQL probes suggested bounded cache and query alternatives, but those are not
release evidence and were not applied to these measurements.

Both browser runs played the actual M4B, navigated back to Library with the player
active, sampled playback every 500 ms for about 16 seconds, then paused normally.
All samples advanced, remained unpaused with readyState 4, and reported no audio
error. This exercises the normal player and its autosave path; it does not prove
long-duration listening, physical phone/Safari behavior, lockscreen controls or
cross-device resume. HTTP Range polling alone would not establish playback.

First HTTP requests are recorded separately in the JSON. They are first requests
after service startup, **not** measurements after flushing NAS filesystem caches.
The 100k first series request took 3.891 seconds. Shared caches and concurrent
activity can affect all results.

## Portable catalog round trips

Both offline NAS round trips completed with zero mismatched catalog tables.
Every column was compared in stable primary-key order, including saved progress.
Both restored databases passed integrity and foreign-key checks and contained
zero login sessions or device credentials. These checks ran before the additional
progress-continuity follow-up described above.

| Portable operation | 50k | 100k |
| --- | ---: | ---: |
| Export size | 81,061,918 bytes | 161,495,113 bytes |
| Export duration | 12.600 s | 17.921 s |
| Export peak RSS | 75.1 MiB | 75.4 MiB |
| Import duration | 47.181 s | 102.842 s |
| Import peak RSS | 76.1 MiB | 77.8 MiB |

Doubling the catalog did not double process memory; both phases stayed below
78 MiB peak RSS in this fixture. Each measurement includes normal application
initialization in a fresh Python process. Export includes snapshot and file
publication; import includes format/domain validation, database insertion,
integrity checks and publication. Originals and chosen-cover bytes are omitted
by the portable format; this is catalog recovery, not a media backup restore.

## Reproducing the disposable measurement

Install the locked backend/frontend dependencies and build the deployment image.
Use fresh data/fixture paths and a private password file, never a production
catalog. The seed command refuses existing directories:

```sh
python scripts/qualify_scale.py seed \
  --data-dir /data/50000 --fixtures /fixtures/50000 --count 50000 \
  --audio backend/tests/fixtures/listening.m4b --output seed-50000.json
```

Run the image with its data directory set to that fixture, and configure the
`benchmark` and `intake` source aliases to the corresponding read-only catalog
and intake directories. From the LAN client:

```sh
python scripts/qualify_scale.py measure --url "$BENCHMARK_URL" \
  --password-file "$PRIVATE_PASSWORD_FILE" --fixture-report seed-50000.json \
  --rounds 30 --output http-50000.json
node scripts/qualify_grid.mjs "$BENCHMARK_URL" "$PRIVATE_PASSWORD_FILE" \
  grid-50000.json seed-50000.json
```

Run those two processes concurrently to reproduce the 100k load combination.
Use count 100000 and fresh paths for the larger fixture. Stop the disposable
service after its intake jobs settle, then run the offline portability check:

```sh
python scripts/qualify_portable.py --data-dir /data/50000 \
  --output-dir /data/portable-50000
```

The output directory must be new. Export and import use separate child processes
so each reports its own elapsed time and peak RSS. Verification streams every
allowlisted table in primary-key order and compares all columns, checks SQLite
integrity/foreign keys, and confirms restored authentication tables are empty.
Use only settled fixtures: active jobs intentionally change state on import.

Machine-readable aggregate results: [scale-nas-2026-09-06.json](scale-nas-2026-09-06.json).
Private passwords, service environment files and real-library source paths are
not included. Real-source intake evidence is separate in [intake-nas.md](intake-nas.md).
