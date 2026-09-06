# Collections

Collections are personal reading orders spanning books, comics, and audiobooks.
Create one from **Collections**, name it, and optionally show its next unfinished
Library work on Home. Add works from a paginated search of the whole catalog,
including Archive. Adding an existing work keeps its original position.

**A whole owned series** appends the currently owned works in publication order,
without duplicating or moving existing entries. It is a deliberate snapshot of
that run's owned works, not a subscription: future imports can be added later.
Distinct series runs remain distinct choices.

Contents are paginated in SQL. Up and Down move one place, including across page
boundaries, and can be used with a keyboard. Removing an entry removes only its
collection membership. Work details, originals, shelves, and records stay intact.
Detail links retain collection and page context across reload and Back.

Home shows one next work per collection explicitly marked **Show on Home**. It
skips Archive choices and works with a finished reading or listening record.
This is a suggestion for the collection's reading order; it does not complete an
audiobook's separate listening progress. Collections can contain the same work
independently and therefore can suggest the same work.

## Grouping and undo

- A full merge moves source-only entries to the target in their existing places.
- If both works occur in a collection, the preview asks which position to keep.
  The chosen entry retains its ID and position; the other membership is removed.
- Attaching one format while the source still has other formats keeps source
  memberships and appends the target where it is absent. Existing target entries
  keep their places.
- Splitting a format appends the new work to its source's collections. Every
  pre-existing position stays intact.
- Undo restores the affected entries and collection state. Later collection
  edits, including ordering other entries, block an undo that could overwrite
  newer choices. Revisions never go backwards, including after chained undo.

Collections use their own optimistic revisions. A stale save or reorder asks for
reload instead of overwriting another client's change. A content-state identity
allows a later undo to restore an earlier operation's expected state without
reusing an API revision. Operation snapshots contain affected entries and their
collections' state identities, not every member of a large collection.

Schema `0007` and JSON export version `7` include collections, entry identities,
positions, revisions, and state identities. Full backup/restore preserves them.
No original file is moved or changed by collection operations.
