"""OPDS navigation and exact-original acquisition, scoped to a reader credential."""

from pathlib import Path
from urllib.parse import urlencode
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from sqlalchemy import func, select

from stacks.covers import Covers
from stacks.inspection import FORMATS
from stacks.models import Asset, Edition, PersonalState, Representation, Work, now

ATOM = "http://www.w3.org/2005/Atom"
SEARCH = "http://a9.com/-/spec/opensearch/1.1/"
NAVIGATION = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQUISITION = "application/atom+xml;profile=opds-catalog;kind=acquisition"
register_namespace("", ATOM)
register_namespace("opensearch", SEARCH)


def clean(value):
    # XML1.0 permits fewer control characters than JSON/Python strings.
    return "".join(
        c
        for c in str(value)
        if c in "\t\n\r"
        or 0x20 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD
        or 0x10000 <= ord(c) <= 0x10FFFF
    )


def text(parent, tag, value, **attributes):
    node = SubElement(parent, f"{{{ATOM}}}{tag}", attributes)
    node.text = clean(value)
    return node


def link(parent, relation, url, media, title=None):
    attributes = {"rel": relation, "href": url, "type": media}
    if title:
        attributes["title"] = clean(title)
    return SubElement(parent, f"{{{ATOM}}}link", attributes)


def document(node):
    return tostring(node, encoding="utf-8", xml_declaration=True)


class Opds:
    def __init__(self, library, scope, base):
        self.library, self.scope, self.base = library, scope, base.rstrip("/")

    def url(self, path="", **query):
        suffix = "?" + urlencode(query) if query else ""
        return self.base + path + suffix

    def _feed(self, title, url, media):
        feed = Element(f"{{{ATOM}}}feed")
        text(feed, "id", url)
        text(feed, "title", title)
        text(feed, "updated", now())
        text(SubElement(feed, f"{{{ATOM}}}author"), "name", "Stacks")
        link(feed, "self", url, media)
        link(feed, "start", self.url(), NAVIGATION)
        link(feed, "search", self.url("/search.xml"), "application/opensearchdescription+xml")
        return feed

    def _pages(self, feed, path, total, limit, offset, media, **query):
        SubElement(feed, f"{{{SEARCH}}}totalResults").text = str(total)
        SubElement(feed, f"{{{SEARCH}}}startIndex").text = str(offset)
        SubElement(feed, f"{{{SEARCH}}}itemsPerPage").text = str(limit)
        if offset:
            link(
                feed,
                "previous",
                self.url(path, **query, limit=limit, offset=max(0, offset - limit)),
                media,
            )
        if offset + limit < total:
            link(feed, "next", self.url(path, **query, limit=limit, offset=offset + limit), media)

    def root(self):
        feed = self._feed(
            "Stacks · " + ("Library shelf" if self.scope == "library" else "Everything owned"),
            self.url(),
            NAVIGATION,
        )
        for title, medium in (
            ("Books", "ebook"),
            ("Comics", "comic"),
            ("Audiobooks", "audio"),
            ("All publications", ""),
        ):
            entry = SubElement(feed, f"{{{ATOM}}}entry")
            target = self.url("/catalog", medium=medium)
            text(entry, "id", target)
            text(entry, "title", title)
            text(entry, "updated", now())
            link(entry, "subsection", target, NAVIGATION)
        return document(feed)

    def search(self):
        root = Element(f"{{{SEARCH}}}OpenSearchDescription")
        SubElement(root, f"{{{SEARCH}}}ShortName").text = "Stacks"
        SubElement(
            root, f"{{{SEARCH}}}Description"
        ).text = "Search titles and authors in your reader's library scope"
        SubElement(root, f"{{{SEARCH}}}InputEncoding").text = "UTF-8"
        SubElement(
            root,
            f"{{{SEARCH}}}Url",
            {
                "type": NAVIGATION,
                "template": self.url("/catalog") + "?q={searchTerms}",
            },
        )
        return document(root)

    def catalog(self, q="", medium=None, limit=24, offset=0):
        page = self.library.list(q=q, medium=medium, scope=self.scope, limit=limit, offset=offset)
        url = self.url("/catalog", q=q, medium=medium or "", limit=limit, offset=offset)
        feed = self._feed("Search results" if q else "Your publications", url, NAVIGATION)
        self._pages(
            feed, "/catalog", page.total, limit, offset, NAVIGATION, q=q, medium=medium or ""
        )
        for work in page.items:
            entry = SubElement(feed, f"{{{ATOM}}}entry")
            text(entry, "id", "urn:uuid:" + work.id)
            text(entry, "title", work.title)
            text(entry, "updated", work.updated_at)
            for author in work.authors:
                text(SubElement(entry, f"{{{ATOM}}}author"), "name", author)
            text(entry, "summary", work.description, type="text")
            link(entry, "subsection", self.url("/works/" + work.id), ACQUISITION)
            cover = next(
                (
                    rep
                    for edition in work.editions
                    for rep in edition.representations
                    if rep.has_cover
                ),
                None,
            )
            if cover or work.selected_cover_id:
                link(
                    entry,
                    "http://opds-spec.org/image",
                    self.url("/works/" + work.id + "/cover"),
                    "image/jpeg",
                )
        return document(feed)

    def _allowed(self, session, work):
        if work is None or work.trashed_at:
            raise KeyError("Publication unavailable")
        personal = session.get(PersonalState, work.id)
        shelf = (personal.shelf_override or personal.default_shelf) if personal else "library"
        if self.scope == "library" and shelf != "library":
            raise KeyError("Publication unavailable")

    def originals(self, work_id, limit=24, offset=0):
        with self.library.sessions() as session:
            work = session.get(Work, work_id)
            self._allowed(session, work)
            query = (
                select(Asset, Representation, Edition)
                .select_from(Asset)
                .join(Representation)
                .join(Edition)
                .where(Edition.work_id == work_id)
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            feed = self._feed(
                work.title + " · Formats and originals",
                self.url("/works/" + work_id, limit=limit, offset=offset),
                ACQUISITION,
            )
            self._pages(feed, "/works/" + work_id, total, limit, offset, ACQUISITION)
            for asset, representation, edition in session.execute(
                query.order_by(Edition.id, Representation.id, Asset.position, Asset.id)
                .limit(limit)
                .offset(offset)
            ):
                entry = SubElement(feed, f"{{{ATOM}}}entry")
                text(entry, "id", "urn:uuid:" + asset.id)
                title = work.title + " · " + representation.format.upper()
                if edition.narrator:
                    title += " · " + edition.narrator
                if representation.format == "audio-set":
                    title += f" · Track {asset.position + 1}: {asset.original_name}"
                text(entry, "title", title)
                text(entry, "updated", work.updated_at)
                for credit in work.credits:
                    text(SubElement(entry, f"{{{ATOM}}}author"), "name", credit.contributor.name)
                text(entry, "summary", work.description, type="text")
                media = FORMATS.get(
                    Path(asset.original_name).suffix.lower().lstrip("."),
                    ("", "application/octet-stream"),
                )[1]
                link(
                    entry,
                    "http://opds-spec.org/acquisition",
                    self.url("/assets/" + asset.id),
                    media,
                    asset.original_name,
                ).set("length", str(asset.size))
                if representation.cover_path or work.selected_cover_id:
                    link(
                        entry,
                        "http://opds-spec.org/image",
                        self.url("/works/" + work.id + "/cover"),
                        "image/jpeg",
                    )
            return document(feed)

    def asset(self, asset_id):
        with self.library.sessions() as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                raise KeyError(asset_id)
            representation = session.get(Representation, asset.representation_id)
            edition = session.get(Edition, representation.edition_id)
            self._allowed(session, session.get(Work, edition.work_id))
            media = FORMATS.get(
                Path(asset.original_name).suffix.lower().lstrip("."),
                ("", "application/octet-stream"),
            )[1]
            return self.library.resolve_asset(asset), asset.original_name, media

    def cover(self, representation_id):
        with self.library.sessions() as session:
            representation = session.get(Representation, representation_id)
            if representation is None or not representation.cover_path:
                raise KeyError(representation_id)
            edition = session.get(Edition, representation.edition_id)
            self._allowed(session, session.get(Work, edition.work_id))
            return self.library.resolve(representation.cover_path)

    def work_cover(self, work_id):
        with self.library.sessions() as session:
            self._allowed(session, session.get(Work, work_id))
            return Covers(self.library).thumbnail(work_id)
