"""Catalog and managed imports. One durable journal hides the DB/filesystem seam."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from stacks.db import initialize
from stacks.epub import InvalidBook, safe_member
from stacks.inspection import inspect_file, natural_key
from stacks.models import (
    Asset,
    Contributor,
    Credit,
    Edition,
    ImportOperation,
    Representation,
    Series,
    SeriesMembership,
    Work,
    identity,
)
from stacks.schemas import (
    CatalogPage,
    ImportResult,
    SeriesEdit,
    SeriesOut,
    SeriesPage,
    WorkEdit,
    WorkOut,
)


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def sync_dir(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_durable(path: Path, content: bytes):
    with path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def series_out(series: Series) -> SeriesOut:
    return SeriesOut(id=series.id, name=series.name, run=series.run, revision=series.revision)


def work_out(work: Work) -> WorkOut:
    return WorkOut(
        id=work.id,
        title=work.title,
        authors=[c.contributor.name for c in work.credits],
        description=work.description,
        revision=work.revision,
        created_at=work.created_at,
        memberships=[
            dict(
                series_id=m.series_id,
                designation=m.designation,
                position=m.position,
                series=series_out(m.series),
            )
            for m in work.memberships
        ],
        editions=[
            dict(
                id=e.id,
                medium=e.medium,
                narrator=e.narrator,
                abridgement=e.abridgement,
                language=e.language,
                publisher=e.publisher,
                identifier=e.identifier,
                representations=[
                    dict(
                        id=r.id,
                        format=r.format,
                        facts={
                            k: v
                            for k, v in json.loads(r.extracted_json).items()
                            if k in {"page_count", "duration_seconds", "series_hint"}
                        },
                        has_cover=bool(r.cover_path),
                        capabilities=["download"],
                        assets=[
                            dict(
                                id=a.id, original_name=a.original_name, size=a.size, sha256=a.sha256
                            )
                            for a in r.assets
                        ],
                    )
                    for r in e.representations
                ],
            )
            for e in work.editions
        ],
    )


class Library:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = (self.data_dir / ".owner.lock").open("a")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_file.close()
            raise RuntimeError(
                "This data directory is already open. Run one Stacks process."
            ) from None
        self.lock = threading.RLock()
        try:
            self.managed = self.data_dir / "managed"
            self.staging = self.data_dir / "staging"
            self.managed.mkdir(exist_ok=True)
            self.staging.mkdir(exist_ok=True)
            self.engine, self.sessions = initialize(self.data_dir / "catalog.sqlite3")
            self.recover()
        except BaseException:
            self._lock_file.close()
            raise

    def close(self):
        self.engine.dispose()
        self._lock_file.close()

    def resolve(self, relative: str) -> Path:
        path = (self.managed / relative).resolve()
        if not path.is_relative_to(self.managed.resolve()) or not path.is_file():
            raise FileNotFoundError("The original file is unavailable.")
        return path

    def list(
        self, q: str = "", limit: int = 60, offset: int = 0, series_id: str | None = None
    ) -> CatalogPage:
        with self.sessions() as session:
            query = select(Work)
            ordering = (Work.created_at.desc(), Work.id)
            if series_id:
                if session.get(Series, series_id) is None:
                    raise KeyError(series_id)
                query = query.join(SeriesMembership).where(SeriesMembership.series_id == series_id)
                ordering = (SeriesMembership.position, Work.id)
            if q.strip():
                pattern = (
                    "%"
                    + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    + "%"
                )
                query = query.where(
                    or_(
                        Work.title.ilike(pattern, escape="\\"),
                        Work.credits.any(
                            Credit.contributor.has(Contributor.name.ilike(pattern, escape="\\"))
                        ),
                    )
                )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            query = (
                query.options(
                    selectinload(Work.memberships).selectinload(SeriesMembership.series),
                    selectinload(Work.credits).selectinload(Credit.contributor),
                    selectinload(Work.editions)
                    .selectinload(Edition.representations)
                    .selectinload(Representation.assets),
                )
                .order_by(*ordering)
                .limit(limit)
                .offset(offset)
            )
            return CatalogPage(
                items=[work_out(w) for w in session.scalars(query)],
                total=total,
                limit=limit,
                offset=offset,
            )

    def get(self, work_id: str) -> WorkOut:
        with self.sessions() as session:
            work = session.get(Work, work_id)
            if work is None:
                raise KeyError(work_id)
            return work_out(work)

    def edit(self, work_id: str, edit: WorkEdit) -> WorkOut:
        with self.lock, self.sessions.begin() as session:
            work = session.get(Work, work_id)
            if work is None:
                raise KeyError(work_id)
            if work.revision != edit.revision:
                raise ValueError("This book changed in another tab. Reload before saving.")
            if edit.editions is not None:
                editions = {e.id: e for e in work.editions}
                if len({e.id for e in edit.editions}) != len(edit.editions):
                    raise ValueError("An edition was specified twice.")
                for details in edit.editions:
                    if details.id not in editions:
                        raise ValueError("Edition does not belong to this work.")
                    for name, value in details.model_dump(exclude={"id"}).items():
                        setattr(editions[details.id], name, value)
            if edit.memberships is not None:
                if len({m.series_id for m in edit.memberships}) != len(edit.memberships):
                    raise ValueError("A work can belong to each series only once.")
                existing = {m.series_id: m for m in work.memberships}
                updated = []
                for details in edit.memberships:
                    series = session.get(Series, details.series_id)
                    if series is None:
                        raise ValueError("Series no longer exists.")
                    member = existing.get(details.series_id) or SeriesMembership(series=series)
                    member.designation, member.position = details.designation, details.position
                    updated.append(member)
                work.memberships = updated
            work.title, work.description = edit.title, edit.description
            work.revision += 1
            # Names aren't identities: update ordered credits without globally merging names.
            for i, name in enumerate(edit.authors):
                if i < len(work.credits):
                    work.credits[i].contributor.name = name
                else:
                    work.credits.append(Credit(position=i, contributor=Contributor(name=name)))
            work.credits[:] = work.credits[: len(edit.authors)]
            session.flush()
            return work_out(work)

    def series(self, q: str = "", limit: int = 60, offset: int = 0) -> SeriesPage:
        with self.sessions() as session:
            query = select(Series)
            if q:
                query = query.where(Series.name.contains(q, autoescape=True))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            query = query.order_by(Series.name, Series.run, Series.id).limit(limit).offset(offset)
            return SeriesPage(
                items=[series_out(s) for s in session.scalars(query)],
                total=total,
                limit=limit,
                offset=offset,
            )

    def save_series(self, edit: SeriesEdit, series_id: str | None = None) -> SeriesOut:
        with self.lock, self.sessions.begin() as session:
            series = session.get(Series, series_id) if series_id else Series()
            if series is None:
                raise KeyError(series_id)
            if series_id and series.revision != edit.revision:
                raise ValueError("Series changed. Reload before saving.")
            series.name, series.run = edit.name, edit.run
            series.revision = (series.revision + 1) if series_id else 1
            session.add(series)
            session.flush()
            return series_out(series)

    def import_file(self, source: Path, original_name: str) -> ImportResult:
        """Source is an owned temporary upload. Caller cleans it up; never touch external files."""
        return self.import_files([(source, original_name)])

    def import_files(self, sources: list[tuple[Path, str]]) -> ImportResult:
        """An ordered audio set is one representation; other formats have exactly one asset."""
        if not sources or len(sources) > 2000:
            raise InvalidBook("Choose between 1 and 2000 files.")
        sources = sorted(sources, key=lambda item: (natural_key(item[1]), item[1]))
        if any(not safe_member(name) or len(name) > 1024 for _, name in sources):
            raise InvalidBook("Invalid original filename.")
        inspections = [inspect_file(path, name) for path, name in sources]
        if len(sources) > 1 and any(i.facts["medium"] != "audio" for i in inspections):
            raise InvalidBook("Only audio tracks can be imported as one file set.")
        metadata = dict(inspections[0].facts)
        cover = next((i.cover for i in inspections if i.cover), None)
        entries = []
        for index, ((source, name), inspection) in enumerate(
            zip(sources, inspections, strict=True)
        ):
            fmt = inspection.facts["format"]
            entries.append(
                dict(
                    filename=f"original.{fmt}" if len(sources) == 1 else f"track-{index:04d}.{fmt}",
                    original_name=name,
                    sha256=digest(source),
                    size=source.stat().st_size,
                    facts=inspection.facts,
                )
            )
        metadata["assets"] = entries
        if len(entries) > 1:
            metadata["format"] = "audio-set"
            metadata["duration_seconds"] = sum(i.facts["duration_seconds"] for i in inspections)
        sha = (
            entries[0]["sha256"]
            if len(entries) == 1
            else hashlib.sha256("".join(e["sha256"] for e in entries).encode()).hexdigest()
        )
        original_name = sources[0][1]
        with self.lock:
            with self.sessions() as session:
                existing = session.scalar(
                    select(Work.id)
                    .join(ImportOperation, ImportOperation.work_id == Work.id)
                    .where(ImportOperation.sha256 == sha, ImportOperation.state == "complete")
                )
            if existing:
                return ImportResult(work=self.get(existing), duplicate=True)
            with self.sessions() as session:
                pending = session.scalar(
                    select(ImportOperation.id)
                    .where(ImportOperation.sha256 == sha, ImportOperation.state != "complete")
                    .order_by(ImportOperation.created_at)
                )
            if pending:
                work_id = self._publish(pending)
                return ImportResult(work=self.get(work_id), duplicate=False)
            operation_id = identity()
            stage = self.staging / operation_id
            stage.mkdir()
            try:
                for (source, _), entry in zip(sources, entries, strict=True):
                    destination = stage / entry["filename"]
                    with source.open("rb") as incoming, destination.open("xb") as out:
                        shutil.copyfileobj(incoming, out, 1024**2)
                        out.flush()
                        os.fsync(out.fileno())
                    if digest(destination) != entry["sha256"]:
                        raise OSError("File verification failed; the upload was not imported.")
                if cover:
                    write_durable(stage / "cover.jpg", cover)
                sync_dir(stage)
                sync_dir(self.staging)
                with self.sessions.begin() as session:
                    session.add(
                        ImportOperation(
                            id=operation_id,
                            sha256=sha,
                            size=sum(e["size"] for e in entries),
                            original_name=original_name,
                            extracted_json=json.dumps(metadata, ensure_ascii=False),
                        )
                    )
            except BaseException:
                # If a journal commit is ambiguous, preserve the stage for startup recovery.
                with self.sessions() as session:
                    recorded = session.get(ImportOperation, operation_id)
                if recorded is None:
                    shutil.rmtree(stage)
                raise
            work_id = self._publish(operation_id)
            return ImportResult(work=self.get(work_id), duplicate=False)

    def _publish(self, operation_id: str) -> str:
        with self.sessions() as session:
            operation = session.get(ImportOperation, operation_id)
            if operation.state == "complete":
                return operation.work_id
            metadata = json.loads(operation.extracted_json)
            entries = metadata.get("assets") or [
                dict(
                    filename="original.epub",
                    sha256=operation.sha256,
                    size=operation.size,
                    original_name=operation.original_name,
                )
            ]
        stage = self.staging / operation_id
        destination = self.managed / operation_id
        if destination.exists() and stage.exists():
            raise OSError("Import destination collision; staged copy retained.")
        location = destination if destination.exists() else stage
        for entry in entries:
            if not safe_member(entry["filename"]):
                raise OSError("Unsafe journal path; copies retained.")
            original = location / entry["filename"]
            if (
                not original.is_file()
                or original.stat().st_size != entry["size"]
                or digest(original) != entry["sha256"]
            ):
                raise OSError("Import original missing or checksum mismatch; copies retained.")
        if location == stage:
            os.rename(stage, destination)
        # Recovery may observe a rename whose directory sync failed before the crash.
        # Re-establish durability on both paths before acknowledging the catalog commit.
        sync_dir(self.managed)
        sync_dir(self.staging)
        with self.sessions.begin() as session:
            operation = session.get(ImportOperation, operation_id)
            metadata = json.loads(operation.extracted_json)
            work = Work(title=metadata["title"], description=metadata["description"])
            work.credits = [
                Credit(position=i, contributor=Contributor(name=name))
                for i, name in enumerate(metadata["authors"])
            ]
            edition = Edition(
                medium=metadata.get("medium", "ebook"),
                language=metadata["language"],
                publisher=metadata["publisher"],
                identifier=metadata["identifier"],
            )
            representation = Representation(
                id=operation_id,
                format=metadata.get("format", "epub"),
                extracted_json=operation.extracted_json,
                cover_path=f"{operation_id}/cover.jpg"
                if (destination / "cover.jpg").is_file()
                else None,
            )
            representation.assets = [
                Asset(
                    relative_path=f"{operation_id}/{entry['filename']}",
                    original_name=entry["original_name"],
                    sha256=entry["sha256"],
                    size=entry["size"],
                    position=index,
                )
                for index, entry in enumerate(entries)
            ]
            edition.representations = [representation]
            work.editions = [edition]
            session.add(work)
            session.flush()
            operation.work_id, operation.state, operation.error = work.id, "complete", None
            return work.id

    def recover(self):
        with self.lock, self.sessions() as session:
            pending = list(
                session.scalars(
                    select(ImportOperation.id).where(ImportOperation.state != "complete")
                )
            )
        for operation_id in pending:
            try:
                self._publish(operation_id)
            except (OSError, ValueError, InvalidBook) as exc:
                with self.sessions.begin() as session:
                    operation = session.get(ImportOperation, operation_id)
                    operation.state, operation.error = "error", str(exc)
        # Unjournaled upload/staging copies have no library ownership yet and are disposable.
        with self.sessions() as session:
            known = set(session.scalars(select(ImportOperation.id)))
        for path in self.staging.iterdir():
            if path.name not in known and not path.is_symlink():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

    def export(self) -> dict:
        """Versioned portable catalog. No sessions, secrets, or machine-specific paths."""
        with self.lock, self.engine.connect() as connection:
            tables = {}
            for model in (
                Work,
                Contributor,
                Credit,
                Edition,
                Representation,
                Asset,
                Series,
                SeriesMembership,
            ):
                tables[model.__tablename__] = [
                    dict(row)
                    for row in connection.execute(
                        select(model.__table__).order_by(model.__table__.c.id)
                    ).mappings()
                ]
            return {"schema_version": 2, "roots": {"managed": "managed/"}, "tables": tables}
