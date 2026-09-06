# Personal shelves and reading history

Library opens on the everyday library shelf. Switch to Archive for owned works kept out of daily browsing, or Everything owned to search both. The scope remains in the URL through book details, Back, and reload. Managed imports default to Library. Each work can explicitly choose Library or Archive, or use its stored default; this supports a later archive default for registered intake without overriding deliberate choices.

Work details offer personal notes, a one-to-five rating, and tags separately from descriptive metadata. Personal saves use the work revision, so another tab or catalog operation cannot silently overwrite an older editing form.

Reading & listening stores repeated periods with start and optional finish dates. A record can describe the whole work or a particular available format. Reading requires a reading format; listening requires an audio format. Whole-work records support reading or listening outside this app. Editing and removing records check their own revisions. History is paginated in SQL. Audio completion does not automatically create a reading record.

Grouping previews include conflicting notes, ratings, tags, and shelf policies. Choose source or target values; the operation record retains both original states. Fully grouping a work moves all its reading records. Moving one format moves only its linked records while work-only history remains with the source. Splitting copies personal values and moves linked records to the new work. Undo restores prior personal values and history ownership only when no later relevant facts changed. Work and reading-record revisions never move backward; audio progress remains independent and is never rewound.

Schema 0005 and export version 5 include personal state and reading records. Full backup and restore preserve both. Earlier grouping history remains undoable when no new personal facts would be overwritten. Following and series-first browsing are described in [followed series](followed-series.md). Ordered collections remain the final curation milestone.
