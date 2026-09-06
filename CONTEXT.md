# Stacks — proposed domain language

Proposed vocabulary for a personal library of books, comics, and audiobooks. This describes the successor, not the current application's schema.

## Language

**Work**:
A recognizable book, comic issue, or collected volume, independent of its language, edition, recording, or file format. A collected volume is its own work even when it contains previously published issues.
_Avoid_: Item, file, title (when identifying the entity)

**Edition**:
A particular textual, visual, or audio version of a work, distinguished where known by language, publication, revision, narrator, or abridgement. An edition may have several available representations.
_Avoid_: Format, copy

**Representation**:
One usable way to read or listen to an edition, consisting of one file or an ordered set of files. An EPUB, a PDF, an M4B, and a folder of MP3 tracks are examples.
_Avoid_: Edition, folder audiobook (as a separate kind of library entity)

**Asset**:
An individual original file belonging to a representation, with a known location and content identity. Two assets may contain identical bytes without being the same physical file.
_Avoid_: Book, work

**Series**:
A named publication or reading sequence containing works in a defined order. A comic run is a series distinguished from other runs by publication context, even when names match.
_Avoid_: Folder, collection

**Series membership**:
A work's place in a series, including its displayed issue or volume designation and its ordering position. Displayed designations may include words or punctuation.

**Contributor**:
A person or group credited for a work or edition, with a stated role such as author, artist, translator, or narrator. Names alone do not establish identity.

**Library shelf**:
The works deliberately kept visible for everyday browsing and choosing what to read or listen to.

**Archive**:
Owned works kept searchable and accessible without appearing on the everyday library shelf.

**Following**:
The intent to keep up with a series. Following does not itself mean that any of its works have been read.

**Collection**:
A personally curated, ordered list of works, potentially spanning media and series.
_Avoid_: Series, genre

**Progress**:
A saved reading or listening location in a particular representation. Progress in one representation does not imply an equivalent location in another.

**Reading record**:
A period of reading or listening to a work, optionally associated with a particular edition and with start and finish dates. Re-reading creates another record.

**Metadata suggestion**:
A proposed descriptive value from a file, filename, or external catalog, distinct from a value the owner has deliberately accepted or corrected.

**Import candidate**:
A discovered file or file group being assessed for inclusion in the library. It may be ready to import, need a decision, be an exact duplicate, or have an error.

### Ordered collections (implemented)

A Collection is a named personal reading order of distinct Works, across media.
CollectionEntry has its own identity and an integer position unique within that
collection. Adding a series appends its currently owned Works in publication
order; future membership changes are not silently mirrored. Showing a collection
on Home is an explicit choice. Collection revisions guard client writes; a
separate content-state identity supports guarded, chained catalog undo. See
[collections](docs/collections.md) for grouping, split, and next-up rules.


### Read-only source roots (implementation underway)

Root aliases identify configured source directories without storing machine paths
in portable catalog data. External Assets retain root-relative locations and file
observations; their original bytes are never managed or copied by registration.
New registrations default to Archive. A library backup includes owned files and
external references; registered original bytes require separate source protection.
See [read-only sources](docs/read-only-sources.md).


### Trash (implemented)

Trash hides a Work while preserving its bibliographic identity, personal choices,
reading history, and ordered memberships. Managed originals relocate through a
verified per-asset journal; external registrations only change catalog visibility.
Restore preserves Work/Representation/Asset identities. Historical storage receipts
prevent an older catalog undo from erasing newer recovery history. See
[recoverable Trash](docs/recoverable-trash.md).
