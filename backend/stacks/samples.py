"""Original synthetic publications for development and tests; no copyrighted book content."""

import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw


def epub_bytes(title="The Quiet Library", authors=("Alex Reed",), cover=True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles></container>""",
        )
        creators = "".join(f"<dc:creator>{escape(name)}</dc:creator>" for name in authors)
        cover_item = (
            '<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
            if cover
            else ""
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">urn:stacks:sample:{escape(title)}</dc:identifier>
<dc:title>{escape(title)}</dc:title>{creators}<dc:language>en</dc:language>
<dc:publisher>Stacks Press</dc:publisher>
<dc:description>An original sample publication about finding time to read.
Created for Stacks development and testing.</dc:description>
<meta property="dcterms:modified">2026-09-06T00:00:00Z</meta></metadata>
<manifest><item id="text" href="chapter.xhtml" media-type="application/xhtml+xml"/>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{cover_item}</manifest>
<spine><itemref idref="text"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/chapter.xhtml",
            f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{escape(title)}</title></head><body><h1>{escape(title)}</h1>
<p>The afternoon light fell across the reading table. One book was enough to begin.</p>
</body></html>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"
xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head><body>
<nav epub:type="toc">
<ol><li><a href="chapter.xhtml">Chapter one</a></li></ol>
</nav></body></html>""",
        )
        if cover:
            colors = ["#344c40", "#975035", "#ba9c59", "#3b5369", "#73535f"]
            image = Image.new("RGB", (400, 600), colors[sum(map(ord, title)) % len(colors)])
            draw = ImageDraw.Draw(image)
            draw.line((40, 60, 360, 60), fill="#eee7d5", width=3)
            draw.text(
                (40, 100), authors[0] if authors else "Stacks Press", fill="#eee7d5", font_size=18
            )
            words, lines, current = title.replace("—", "-").split(), [], ""
            for word in words:
                if len(current + word) > 17:
                    lines.append(current.strip())
                    current = ""
                current += word + " "
            lines.append(current.strip())
            for i, line in enumerate(lines):
                draw.text((40, 190 + i * 45), line, fill="#eee7d5", font_size=32)
            draw.text((40, 530), "STACKS  /  SAMPLE EDITION", fill="#eee7d5", font_size=13)
            content = io.BytesIO()
            image.save(content, "JPEG")
            archive.writestr("OEBPS/cover.jpg", content.getvalue())
    return output.getvalue()


def main():
    target = Path("samples")
    target.mkdir(exist_ok=True)
    for i, title in enumerate(
        (
            "The Quiet Library",
            "A Field Guide to Rain",
            "Notes from the Coast",
            "An Ordinary Afternoon",
            "The Long Way Home",
            "Small Hours",
        )
    ):
        path = target / f"{title}.epub"
        path.write_bytes(
            epub_bytes(title, ("Alex Reed" if i % 2 else "Robin Vale",), cover=i % 3 != 0)
        )
    print(f"Created six original sample EPUBs in {target}/")


if __name__ == "__main__":
    main()
