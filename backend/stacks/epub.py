"""Bounded EPUB inspection. Never extract archive paths onto the filesystem."""

import io
import posixpath
import warnings
import zipfile
from pathlib import PurePosixPath
from urllib.parse import unquote

from defusedxml import ElementTree as XML
from PIL import Image

DC = "http://purl.org/dc/elements/1.1/"


class InvalidBook(ValueError):
    pass


def safe_member(name: str) -> bool:
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name


def inspect_epub(path, original_name: str) -> tuple[dict, bytes | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(i.file_size for i in entries) > 512 * 1024**2:
                raise InvalidBook("This EPUB exceeds the inspection limits.")
            names = [i.filename for i in entries]
            if len(set(names)) != len(names) or any(not safe_member(n) for n in names):
                raise InvalidBook("The EPUB contains ambiguous or unsafe archive paths.")
            if any(i.flag_bits & 1 for i in entries):
                raise InvalidBook("Encrypted EPUB archives are not supported.")

            def read(name: str, limit: int = 2 * 1024**2) -> bytes:
                if not safe_member(name) or archive.getinfo(name).file_size > limit:
                    raise InvalidBook("An EPUB metadata entry exceeds the inspection limits.")
                with archive.open(name) as source:
                    content = source.read(limit + 1)
                if len(content) > limit:
                    raise InvalidBook("An EPUB metadata entry exceeds the inspection limits.")
                return content

            if read("mimetype", 100).strip() != b"application/epub+zip":
                raise InvalidBook("This file is not an EPUB publication.")
            container = XML.fromstring(read("META-INF/container.xml"))
            root = container.find(".//{*}rootfile")
            if root is None or not root.get("full-path"):
                raise InvalidBook("The EPUB has no publication metadata.")
            opf_path = root.attrib["full-path"]
            package = XML.fromstring(read(opf_path))

            def values(tag: str, limit: int) -> list[str]:
                return [
                    " ".join("".join(e.itertext()).split())[:limit]
                    for e in package.findall(f".//{{{DC}}}{tag}")[:100]
                    if "".join(e.itertext()).strip()
                ]

            def first(tag: str, limit: int = 1024) -> str:
                return next(iter(values(tag, limit)), "")

            metadata = {
                "title": first("title") or PurePosixPath(original_name).stem[:1024] or "Untitled",
                "authors": values("creator", 512)[:20],
                "description": first("description", 20000),
                "language": first("language", 64),
                "publisher": first("publisher"),
                "identifier": first("identifier"),
            }
            cover_id = next(
                (
                    m.get("content")
                    for m in package.findall(".//{*}meta")
                    if m.get("name") == "cover"
                ),
                None,
            )
            item = next(
                (
                    i
                    for i in package.findall(".//{*}manifest/{*}item")
                    if "cover-image" in i.get("properties", "").split()
                    or (cover_id and i.get("id") == cover_id)
                ),
                None,
            )
            cover = None
            if item is not None:
                href = unquote(item.get("href", ""))
                cover_path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
                if safe_member(cover_path) and cover_path in names:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("error", Image.DecompressionBombWarning)
                            with Image.open(io.BytesIO(read(cover_path, 10 * 1024**2))) as im:
                                if im.width * im.height > 12_000_000:
                                    raise ValueError("Cover too large")
                                im.thumbnail((600, 900))
                                output = io.BytesIO()
                                im.convert("RGB").save(output, "JPEG", quality=85)
                                cover = output.getvalue()
                    except (
                        OSError,
                        ValueError,
                        Image.DecompressionBombWarning,
                        Image.DecompressionBombError,
                    ):
                        pass  # A bad optional cover does not invalidate a readable publication.
            return metadata, cover
    except InvalidBook:
        raise
    except Exception as exc:
        raise InvalidBook("The EPUB is damaged or has invalid publication metadata.") from exc
