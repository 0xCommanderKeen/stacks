# Behavioral reuse ledger

Stacks is a separate implementation and schema history. This ledger records the
legacy behaviors used as references and their successor boundaries; it does not
assert a verbatim file copy where none was recorded. The Polica checkout inspected
for this ledger on 2026-09-06 was at
`e4a251a6336ab20ce4c43c04cca412c21a4653a2`. Earlier design discussions do not provide
an independently verified per-file copy revision, so this is a reference revision,
not a reconstructed claim about the origin of every line.

| Reference behavior / legacy area | Successor and deliberate change | Regression evidence |
| --- | --- | --- |
| EPUB package metadata and embedded covers; `ingest/extract/epub.py` | `backend/stacks/epub.py`: bounded archive/XML inspection; extracted facts feed new catalog identities; no old model dependency | `test_inputs.py`, `test_formats.py`, `test_library.py` |
| Comic metadata, cover/page order; `ingest/extract/comic*` | `inspection.py`: bounded CBZ/CBR inspection, supported decompressor in the image; distinct series-run identities | `test_formats.py`, real compressed CBR container smoke |
| Single/folder audiobook tags and natural track order; `ingest/extract/audiobook*` | `inspection.py`, `library.py`, `reading.py`: explicit ordered Asset sets and representation-specific revisioned progress; ambiguous folder grouping is reviewed | `test_formats.py`, `test_reading.py`, `test_acceptance.py` |
| Hash-based identity, verified publication and interrupted-operation recovery | `library.py`, `trash.py`: immutable managed originals, independent catalog identities, staged publication and per-asset move receipts | `test_library.py`, `test_trash.py`, NAS SIGKILL/storage-fault qualification |
| Original downloads and OPDS links; `api/opds.py` | `devices.py`, `opds.py`: per-reader scoped/revocable hashed credentials; absolute request-base links; no authority in exports | `test_devices.py`, connect/revoke browser journey |
| Restore and external-root relocation guarantees | `backup.py`, `snapshots.py`, `portable.py`: fresh-destination validated archives/JSON, selected-cover originals, streaming bounded catalog portability | `test_maintenance.py`, `test_portable.py`, NAS fresh-container restore and scale round trips |

No old database, schema history, legacy-ID mapping, write-through synchronization
or whole application tree is an adoption dependency. Historical first-slice notes
record the implementation's stable ID-only managed directory names; original
filenames remain catalog/download metadata and metadata corrections do not move
files. The plan's illustrative readable-label directory shape was not used.

No new third-party code license or attribution assertion is made by this behavioral
ledger. Future direct source ports must record the exact origin commit/file,
retained code, adaptation, tests and applicable attribution/license obligations
in this ledger before merging. Locked third-party packages remain dependencies,
not copied legacy application modules.
