# Chosen covers

Open a work and choose **Choose a cover**. Preview a JPEG, PNG or WebP image, then
select **Use this cover**. The work shows that it was chosen by you. Download the
original image at any time, or use **Use embedded cover** to return to a file's
embedded cover. Changes are revision-checked, so a stale page cannot overwrite a
newer selection. Trashed works must be restored before changing their cover.

Cover selection is local and does not modify book/comic/audiobook originals.
Inspection runs in the same bounded subprocess used by publication extraction,
with a 30-second wall deadline, CPU limit, and Linux memory limit. Uploads are
limited to 10 MiB and decoded images to 12 million pixels. Stacks preserves the
uploaded image bytes and generates a separate JPEG thumbnail.

A CoverBlob records the immutable original's SHA-256, size, MIME type, manual
origin and creation time. A work selects it by stable ID. Files live under
`managed/.covers/<id>/original` and `thumbnail.jpg`, independently of representation
folders. This keeps the chosen cover available through managed Trash relocation.
Catalog, detail and OPDS work feeds use the selection; OPDS cover access still
checks current shelf scope and Trash status.

File preparation happens outside the catalog lock. Files and their directory are
flushed before publication; publication and the work selection run under the
catalog lock. The destination and managed-root directories are flushed before the
database commit. Storage errors leave the previous selection intact. A crash
before catalog commit can retain an unselected cover directory; no incomplete
cover becomes selected. Files are never overwritten on selection.

Reset/replacement retains previous CoverBlob rows and originals. Grouping offers
an explicit source/target cover choice when source and target selections differ.
Splitting carries the selected cover to the new work. Guarded undo can recover
prior choices and refuses to erase a subsequent selection. Retained cover data is
not garbage-collected in this version; repeated replacements consume additional
storage. Interrupted preparation directories under uploads may also remain until
operator cleanup; do not delete upload directories while Stacks is running.

Full backups verify cover-original hashes and include chosen originals and
thumbnails. Portable catalog export includes CoverBlob rows and selected IDs,
but no image bytes; original images require the backup bundle. Thumbnails are
separate derivative files and can be regenerated from retained originals; a
missing thumbnail currently reports unavailable until rebuilt, without discarding
the selected original. Later metadata refresh must leave this manual selection
unchanged unless the owner explicitly chooses a replacement.

Tests cover exact original round-trip, backup/restore/export, invalid/oversized
uploads, stale revisions, failures before and after filesystem publication,
grouping conflicts, split/undo, later edits blocking undo, Trash/restore, scoped
OPDS access, and browser preview/selection/reload/reset.
