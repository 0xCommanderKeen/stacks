# Reader access

In Settings → Reader devices, create a named password and choose Library only or
Library and Archive. Copy the displayed catalog URL, username and password into
an OPDS reader. The password is displayed once; revoke and replace a lost one.
Each reader can have a separate password. Revocation prevents subsequent requests;
files already downloaded remain on the reader.

Use Stacks through HTTPS for reader connections. TLS termination belongs at the
reverse proxy; configure forwarded scheme/host only from the trusted proxy so
catalog links use the external HTTPS address. The catalog uses HTTP Basic with a
random reader password, not the owner's login password. Do not place credentials
in URLs. Reader passwords authorize catalog/cover/original reads only and cannot
edit works, export the catalog, create backups or manage other readers.

The [OPDS 1.2 specification](https://specs.opds.io/opds-1.2) defines Atom-based
navigation and acquisition feeds. Stacks separates navigation (media, search and
paged works) from acquisition (paged originals for one work). Search is advertised
through OpenSearch. Links are absolute, and original downloads retain their MIME
type and filename. Multi-file audiobooks expose tracks in representation order;
this does not synthesize a combined audiobook or synchronize reader progress.

Scope is checked again for each original and cover using its current work owner,
including after grouping. Trashed works are excluded from both scopes. A Library
credential loses access when its work moves to Archive. This applies to guessed
URLs too. Missing external originals report their normal availability error.

Only SHA-256 digests of high-entropy reader passwords are stored. Lists never
return passwords or digests. Last-used timestamps update at most every five
minutes. Lists and feeds use SQL pagination; at most 100 named credentials can be
active. Reader credentials are excluded from portable exports and removed from
full backups alongside owner sessions. Restoring a backup requires reissuing them.
Backup snapshot connections close before packaging, ensuring removal is flushed
out of SQLite's write-ahead log into the archived database.

Automated coverage exercises navigation, search, paging, exact downloads, audio
track ordering, metadata XML escaping, scope after grouping/Trash, revocation,
authority separation, and restored-backup credentials. The browser journey covers
creation, one-time display, reload and revocation on desktop and phone Chromium
viewports. Actual OPDS client compatibility and physical reader acceptance remain
release gates; these tests do not establish Safari or hardware compatibility.
