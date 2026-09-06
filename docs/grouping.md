# Grouping and separating formats

Import starts conservatively with separate books. On a book page, **Group or separate formats** offers three deliberate operations:

- **Group as separate editions** moves all editions into another work. Languages, publication identifiers, narrations, and abridgement stay attached to their editions.
- **Attach a format to the same edition** moves one representation. Known conflicting language, narrator, abridgement, publisher, identifier, or medium blocks this choice; keep separate editions instead. Compatible known values supplement unspecified destination details. The owner must establish content equivalence.
- **Separate a format into its own book** creates a new work/edition for one representation, copying descriptive details and series memberships. A work with only one representation cannot be split further.

A preview captures both catalog states. Conflicting titles, authors, descriptions, or shared-series designations/orders require explicit source/target choices. Unique memberships are retained. Commit verifies the preview is still current in one database transaction. Retry of a committed operation is idempotent. No filesystem mutation takes place, and representation/asset IDs remain stable.

Superseded work IDs redirect to their current work; downloads and representation IDs need no redirection. Original descriptive values remain in the operation record. Source records and empty editions are retained internally for undo but do not produce empty catalog cards or edition choices.

Recent catalog history is paginated. Undo restores the captured ownership and descriptive state only when the affected catalog still matches the operation's result. It refuses to overwrite later edits. Revisions continue increasing through undo, protecting against a stale tab that observed a previous state. Undoing later operations can make earlier operations undoable again when all catalog facts match. Operation history and redirects survive backup/restore and are included in export schema 3.

This finishes the initial model exercise: ordinary EPUB/PDF formats fit an edition; different audio recordings remain editions of a work; a multi-track audiobook is a representation with ordered assets; comic membership belongs to the work. Files and user-facing labels are independent of these relationships. Personal-state tables added in Phase 3 must participate in regrouping conflict/undo semantics before those features are complete.
