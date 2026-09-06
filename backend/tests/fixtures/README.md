# Original audio fixtures

`tone.mp3` and `tone.m4a` are two seconds of a generated 440 Hz sine wave, created for Stacks tests. They contain no third-party recording. M4B inspection uses the same MP4 container bytes with an `.m4b` filename.

Generated with FFmpeg (Debian bookworm):

```sh
ffmpeg -f lavfi -i sine=frequency=440:duration=2 -metadata title="A Small Sound" -metadata artist="Stacks Samples" -metadata album="A Listening Room" tone.m4a
ffmpeg -f lavfi -i sine=frequency=440:duration=2 -metadata title="A Small Sound" -metadata artist="Stacks Samples" -metadata album="A Listening Room" tone.mp3
```

PDF and comic fixtures are generated in the test itself. The CBR fixture is a stored RAR4 archive assembled from original metadata and a generated image; compressed CBR compatibility also depends on the packaged libarchive backend.
