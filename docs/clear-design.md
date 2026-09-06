# Clear interface

The owner selected Clear (A) from the three interactive directions in PR50. The working app uses a white sidebar, cobalt actions and active states, a pale background, compact sans-serif headings, and a responsive cover grid. Phone navigation exposes every destination in two rows. The persistent player sits beside the desktop sidebar and spans the phone viewport.

Library includes up to three recent, incomplete audiobook representations from the existing continue API. Each card opens its work or resumes through the existing player; the caption reports the saved position within the current track, rather than claiming whole-book progress. The strip is omitted when nothing is in progress. Home retains the complete paginated continuation list, followed runs, and collection choices.

The design preserves imports, shelf/search/pagination, editing, grouping, covers, curation, collections, Inbox, backups, devices, source roots, Trash, and playback conflict handling. Sample titles and statistics from the prototypes are not product data. No database or API contract change is required.

Validation uses the existing desktop/phone browser journeys, including keyboard-only navigation and the added Library resume step in the audio journey. Layout inspection covers 1440, 900, and 390 CSS pixel widths. Physical-device acceptance remains separate from browser viewport checks.
