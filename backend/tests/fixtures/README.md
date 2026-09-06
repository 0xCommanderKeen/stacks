# Original audio fixtures

`tone.mp3` and `tone.m4a` are two seconds of a generated 440 Hz sine wave, created for Stacks tests. They contain no third-party recording. M4B inspection uses the same MP4 container bytes with an `.m4b` filename.

Generated with FFmpeg (Debian bookworm):

```sh
ffmpeg -f lavfi -i sine=frequency=440:duration=2 -metadata title="A Small Sound" -metadata artist="Stacks Samples" -metadata album="A Listening Room" tone.m4a
ffmpeg -f lavfi -i sine=frequency=440:duration=2 -metadata title="A Small Sound" -metadata artist="Stacks Samples" -metadata album="A Listening Room" tone.mp3
```

PDF and comic fixtures are generated in the test itself. The CBR fixture is a stored RAR4 archive assembled from original metadata and a generated image; `compressed.cbr` is an original RAR5 fixture containing a generated green PNG and repetitive original ComicInfo text, created with RAR 7.01 (`rar a -ep -m5`). Its compressed metadata is decoded in tests and the packaged-container smoke using the packaged unar backend. No writer executable is distributed.

`listening.m4b` contains 20 seconds of a generated 220 Hz sine wave encoded as AAC at 24 kbit/s, with original chapters First Room (0–10 seconds) and Second Room (10–20). FFmpeg maps an FFMETADATA1 chapter file into the output. It is used for browser navigation/resume and automatic track-transition tests.
