"""Read format facts behind one bounded process; never unpack or modify originals."""

import base64
import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as XML
from PIL import Image

from stacks.epub import InvalidBook, inspect_epub, safe_member

FORMATS = {
    "epub": ("ebook", "application/epub+zip"),
    "pdf": ("ebook", "application/pdf"),
    "cbz": ("comic", "application/vnd.comicbook+zip"),
    "cbr": ("comic", "application/vnd.comicbook-rar"),
    "mp3": ("audio", "audio/mpeg"),
    "m4a": ("audio", "audio/mp4"),
    "m4b": ("audio", "audio/mp4"),
}


@dataclass
class Inspection:
    facts: dict
    cover: bytes | None = None


def natural_key(value: str):
    return tuple(
        (0, int(p)) if p.isdigit() else (1, p.casefold()) for p in re.split(r"(\d+)", value)
    )


def thumbnail(content: bytes) -> bytes | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as im:
                if im.width * im.height > 12_000_000:
                    return None
                im.thumbnail((600, 900))
                out = io.BytesIO()
                im.convert("RGB").save(out, "JPEG", quality=85)
                return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        return None


def _comic(path: Path, fmt: str, facts: dict) -> bytes | None:
    import rarfile

    with zipfile.ZipFile(path) if fmt == "cbz" else rarfile.RarFile(path) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if (
            len(entries) > 10000
            or sum(e.file_size for e in entries) > 2 * 1024**3
            or len(names) != len(set(names))
            or any(not safe_member(n) for n in names)
        ):
            raise InvalidBook("Comic archive exceeds limits or has unsafe/ambiguous paths.")
        if any((e.flag_bits & 1) if fmt == "cbz" else e.needs_password() for e in entries):
            raise InvalidBook("Encrypted comics are not supported.")

        def read(name, limit):
            if archive.getinfo(name).file_size > limit:
                raise InvalidBook("Comic entry exceeds the inspection limit.")
            with archive.open(name) as source:
                content = source.read(limit + 1)
            if len(content) > limit:
                raise InvalidBook("Comic entry exceeds the inspection limit.")
            return content

        pages = sorted(
            [n for n in names if Path(n).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}],
            key=natural_key,
        )
        if not pages:
            raise InvalidBook("The comic has no supported image pages.")
        facts["page_count"] = len(pages)
        facts["pages"] = pages
        info = next((n for n in names if n.casefold() == "comicinfo.xml"), None)
        if info:
            root = XML.fromstring(read(info, 2 * 1024**2))

            def field(name, limit=1024):
                return (root.findtext(name) or "").strip()[:limit]

            facts.update(
                title=field("Title") or facts["title"],
                authors=[x.strip()[:512] for x in field("Writer").split(",") if x.strip()][:20],
                description=field("Summary", 20000),
                publisher=field("Publisher"),
                language=field("LanguageISO", 64),
                series_hint={
                    "name": field("Series"),
                    "designation": field("Number"),
                    "year": field("Year", 20),
                    "volume": field("Volume", 100),
                },
            )
        return thumbnail(read(pages[0], 20 * 1024**2))


def _audio(path: Path, fmt: str, facts: dict) -> bytes | None:
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4

    audio = MP3(path) if fmt == "mp3" else MP4(path)
    tags = audio.tags or {}
    keys = (
        {"title": "TIT2", "album": "TALB", "authors": "TPE1"}
        if fmt == "mp3"
        else {"title": "\xa9nam", "album": "\xa9alb", "authors": "\xa9ART"}
    )

    def values(key):
        value = tags.get(keys[key], [])
        return [str(v)[:512] for v in (value.text if hasattr(value, "text") else value)][:20]

    facts["title"] = next(iter(values("album") or values("title")), facts["title"])
    facts["track_title"] = next(iter(values("title")), facts["title"])
    facts["authors"] = values("authors")
    duration = float(audio.info.length)
    if not math.isfinite(duration) or duration <= 0:
        raise InvalidBook("Audio duration is invalid.")
    facts["duration_seconds"] = duration
    facts["chapters"] = []
    if fmt != "mp3" and audio.chapters:
        facts["chapters"] = [{"start": c.start, "title": c.title[:512]} for c in audio.chapters][
            :10000
        ]
    if fmt == "mp3":
        pictures = tags.getall("APIC") if hasattr(tags, "getall") else []
        content = pictures[0].data if pictures else None
    else:
        pictures = tags.get("covr", [])
        content = bytes(pictures[0]) if pictures else None
    return thumbnail(content) if content and len(content) <= 10 * 1024**2 else None


def _inspect(path: Path, name: str) -> Inspection:
    fmt = Path(name).suffix.lower().lstrip(".")
    if fmt not in FORMATS:
        raise InvalidBook("Unsupported publication format.")
    facts = dict(
        title=Path(name).stem[:1024] or "Untitled",
        authors=[],
        description="",
        language="",
        publisher="",
        identifier="",
    )
    cover = None
    if fmt == "epub":
        facts, cover = inspect_epub(path, name)
    elif fmt == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise InvalidBook("Encrypted PDF files are not supported.")
        facts["page_count"] = len(reader.pages)
        if not 0 < facts["page_count"] <= 20000:
            raise InvalidBook("PDF page count exceeds the inspection limit.")
        meta = reader.metadata
        if meta:
            facts.update(
                title=str(meta.title or facts["title"])[:1024],
                authors=[str(meta.author)[:512]] if meta.author else [],
                description=str(meta.subject or "")[:20000],
            )
    elif fmt in {"cbz", "cbr"}:
        cover = _comic(path, fmt, facts)
    else:
        cover = _audio(path, fmt, facts)
    facts.update(format=fmt, medium=FORMATS[fmt][0])
    return Inspection(facts, cover)


def inspect_file(path: Path, name: str) -> Inspection:
    """A malformed parser input cannot monopolize the application process."""
    with subprocess.Popen(
        [sys.executable, "-m", "stacks.inspection", str(path.resolve()), name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as child:
        try:
            output, _ = child.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            raise InvalidBook("Inspection exceeded the 30-second limit.") from None
    if child.returncode != 0 or len(output) > 8 * 1024**2:
        raise InvalidBook("Publication is damaged, unsupported, or exceeds inspection limits.")
    data = json.loads(output)
    if "error" in data:
        raise InvalidBook(data["error"])
    return Inspection(data["facts"], base64.b64decode(data["cover"]) if data["cover"] else None)


if __name__ == "__main__":
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    try:
        result = _inspect(Path(sys.argv[1]), sys.argv[2])
        print(
            json.dumps(
                {
                    "facts": result.facts,
                    "cover": base64.b64encode(result.cover).decode() if result.cover else None,
                },
                ensure_ascii=False,
            )
        )
    except InvalidBook as exc:
        print(json.dumps({"error": str(exc)}))
    except Exception:
        print(json.dumps({"error": "Publication is damaged or has invalid metadata."}))
