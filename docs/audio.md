# Audiobook playback

Choose Listen on an imported MP3, M4A, M4B, or ordered audio set. The player stays open while moving between Library, Home, book details, and Settings. It streams original bytes with authenticated HTTP range requests; downloads remain available when a browser cannot decode a format.

Controls include play/pause, seek, playback speed, previous/next track, and extracted chapters. Tracks advance automatically. Home lists unfinished listening sessions with server-side pagination. Continue resumes the saved track, position, and speed; a completed recording starts again at its first track.

Listening progress belongs to a representation and its asset. Periodic saves, pauses, seeks, speed changes, navigation between recordings, and hidden-tab events save through revision-checked updates. A legitimate backward seek is allowed. If another device has saved a newer revision, playback pauses and offers Reload saved position. An unavailable original keeps its saved position and offers the original download as a fallback. A network failure leaves unsaved progress eligible for retry; abrupt browser termination can lose the most recent interval of playback.

Grouping, splitting, and undo preserve representation and asset IDs. Catalog undo does not rewind listening progress. Progress is included in full backup/restore and catalog export schema 4.

Verification covers authenticated ranges and invalid ranges, ordered tracks, chapter seek, backward seek, restart/resume, concurrent writes, missing originals, grouping/undo, backup/restore, keyboard controls, and persistent playback through navigation. The browser journeys run in Chromium with desktop and phone viewports. Physical devices, Safari background playback, and long-session NAS performance remain release qualification gates.
