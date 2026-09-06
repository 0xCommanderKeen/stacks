# Formats and series

Phase 2a adds PDF, CBZ, CBR, MP3, M4A, and M4B beside EPUB. Browser uploads create separate publications. The ingestion interface also accepts a set of audio tracks as one representation; the folder/bulk intake workflow is Phase 4. A multi-track set sorts nested relative filenames naturally (`Disc 2/2` before `Disc 2/10` before `Disc 10/1`). It preserves every track's original name and bytes. It never deduplicates a complete audiobook against a single matching track.

Each inspector returns the same facts/cover result. Untrusted inspection runs in a subprocess with a 30-second deadline, a 20-second CPU budget, and a 512 MiB address-space limit on Linux. Archive entries are never unpacked onto application storage. EPUB has bounded XML/image limits; comics permit at most 10,000 entries and 2 GiB declared expanded content, with bounded reads for metadata and covers. Encrypted publications are rejected. PDF parsing does not render pages. The original is always the downloadable asset; no conversion is implicit.

PDF metadata uses [pypdf](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html). Audio tags/duration and MP4 chapters use [Mutagen](https://mutagen.readthedocs.io/en/latest/api/mp4.html). CBR uses [rarfile](https://rarfile.readthedocs.io/) with `libarchive-tools` in the container; a local source install needs a supported RAR decompression backend. Embedded covers are optional and may be absent. The current capability is `download`; audio playback arrives in Phase 3.

ComicInfo series name, volume/year, and issue designation remain extracted suggestions. Import never turns an ambiguous name into a series identity. The editor lets the owner create separate named runs or choose an existing series by ID. A membership has a display designation (for example `1/2` or `Annual 2024`) and a separate numeric reading position. Equal positions have a deterministic work-ID tie-break. The series API returns that order. Neither labels nor owned issue numbers imply a known publication count.

Edition edits retain language, publisher, identifier, narrator, and abridgement independently. All edition/membership changes check the owning work revision; series metadata uses its own revision. Editing never moves files. Catalog export schema 2 includes series and memberships. The restore command accepts schema 0001 and 0002 backups; opening an older Stacks library applies the additive migration. No Polica state is imported.

The model gate is not complete until Phase 2b exercises alternate representations, multiple editions, and reversible grouping/splitting. Real-device behavior and large-source throughput remain release gates.

RAR compatibility: rarfile is pinned to 4.2. Version 4.5 generated `bsdtar -f -- archive`, which fails on the Debian container despite passing on macOS. The compressed RAR5 fixture is exercised in the packaged image so dependency upgrades must preserve this path.
