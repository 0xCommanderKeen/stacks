"""Catalog and managed imports. One durable journal hides the DB/filesystem seam."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

from sqlalchemy import func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from stacks.db import initialize
from stacks.epub import InvalidBook, safe_member
from stacks.inspection import inspect_file, natural_key
from stacks.models import (
    Asset,
    CatalogOperation,
    Collection,
    CollectionEntry,
    Contributor,
    Credit,
    Edition,
    ImportOperation,
    InboxCandidate,
    IntakeItem,
    IntakeJob,
    PersonalState,
    Progress,
    ReadingRecord,
    Representation,
    ScanDirectory,
    Series,
    SeriesMembership,
    TrashFile,
    TrashOperation,
    Work,
    WorkRedirect,
    identity,
)
from stacks.schemas import (
    AcceptedMetadata,
    CatalogPage,
    ImportResult,
    PersonalOut,
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
    return SeriesOut(
        id=series.id,
        name=series.name,
        run=series.run,
        revision=series.revision,
        following=series.following,
    )


def personal_out(state):
    if state is None:
        return PersonalOut()
    return PersonalOut(
        default_shelf=state.default_shelf,
        shelf_override=state.shelf_override,
        shelf=state.shelf_override or state.default_shelf,
        notes=state.notes,
        rating=state.rating,
        tags=json.loads(state.tags_json),
    )


def work_out(work: Work) -> WorkOut:
    return WorkOut(
        id=work.id,
        trashed_at=work.trashed_at,
        updated_at=work.updated_at,
        personal=personal_out(work.personal),
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
                        capabilities=["download", "listen"]
                        if r.format in {"mp3", "m4a", "m4b", "audio-set"}
                        else ["download"],
                        assets=[
                            dict(
                                id=a.id,
                                root=a.root,
                                original_name=a.original_name,
                                size=a.size,
                                sha256=a.sha256,
                            )
                            for a in r.assets
                        ],
                    )
                    for r in e.representations
                ],
            )
            for e in work.editions
            if e.representations
        ],
    )


class Library:
    def __init__(self, data_dir: Path, sources: dict[str, Path] | None = None):
        self.sources = {alias: path.resolve() for alias, path in (sources or {}).items()}
        self.data_dir = data_dir.resolve()
        if any(
            self.data_dir.is_relative_to(root) or root.is_relative_to(self.data_dir)
            for root in self.sources.values()
        ):
            raise ValueError("Source directories and Stacks data must not overlap.")
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
        self.ingest_lock = threading.RLock()
        try:
            self.managed = self.data_dir / "managed"
            self.staging = self.data_dir / "staging"
            self.uploads = self.data_dir / "uploads"
            self.managed.mkdir(exist_ok=True)
            self.staging.mkdir(exist_ok=True)
            self.uploads.mkdir(exist_ok=True)
            # The exclusive owner lock makes startup the only safe orphan-upload cleanup.
            for upload in self.uploads.glob("upload-*"):
                if upload.is_file() and not upload.is_symlink():
                    upload.unlink()
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

    def source_path(self, root: str, relative: str) -> Path:
        if root not in self.sources or not safe_member(relative):
            raise FileNotFoundError("The source is unconfigured or its relative path is invalid.")
        directory = self.sources[root]
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise FileNotFoundError(
                "The registered original is unavailable. Check its source mount."
            )
        return path

    def resolve_asset(self, asset: Asset) -> Path:
        if asset.root == "managed":
            return self.resolve(asset.relative_path)
        path = self.source_path(asset.root, asset.relative_path)
        observation = path.stat()
        if observation.st_size != asset.size or observation.st_mtime_ns != asset.observed_mtime_ns:
            raise FileNotFoundError(
                "The registered original changed. Review the source before using it."
            )
        return path

    def register_files(self, root: str, paths: list[str]) -> ImportResult:
        if root not in self.sources:
            raise InvalidBook("Choose a configured source.")
        paths = [
            self.source_path(root, relative).relative_to(self.sources[root]).as_posix()
            for relative in paths
        ]
        if len(set(paths)) != len(paths):
            raise InvalidBook("Choose each source file only once.")
        sources = [(self.source_path(root, relative), relative) for relative in paths]
        return self._ingest(sources, root)

    def list(
        self,
        q: str = "",
        limit: int = 60,
        offset: int = 0,
        series_id: str | None = None,
        scope: str = "all",
        medium: str | None = None,
        unassigned: bool = False,
    ) -> CatalogPage:
        with self.sessions() as session:
            query = select(Work).where(
                Work.trashed_at.is_(None),
                ~select(WorkRedirect.source_id).where(WorkRedirect.source_id == Work.id).exists(),
            )
            if scope != "all":
                query = query.outerjoin(PersonalState).where(
                    func.coalesce(
                        PersonalState.shelf_override, PersonalState.default_shelf, "library"
                    )
                    == scope
                )
            if unassigned:
                query = query.where(~Work.memberships.any())
            if medium:
                query = query.where(
                    Work.editions.any((Edition.medium == medium) & Edition.representations.any())
                )
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
                    selectinload(Work.personal),
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
            seen = set()
            while redirect := session.get(WorkRedirect, work_id):
                if work_id in seen:
                    raise ValueError("Catalog redirect cycle detected.")
                seen.add(work_id)
                work_id = redirect.target_id
            work = session.get(Work, work_id)
            if work is None:
                raise KeyError(work_id)
            return work_out(work)

    def edit(self, work_id: str, edit: WorkEdit) -> WorkOut:
        with self.lock, self.sessions.begin() as session:
            work = session.get(Work, work_id)
            if work is None:
                raise KeyError(work_id)
            if session.get(WorkRedirect, work_id):
                raise ValueError("This work was regrouped. Open its current page before saving.")
            if work.trashed_at:
                raise ValueError("Restore this book from Trash before editing it.")
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
                    if series.following and work.personal is not None:
                        work.personal.default_shelf = "library"
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
        return self._ingest(sources)

    def accept_sources(
        self,
        root,
        paths,
        expected_hashes,
        accepted: AcceptedMetadata,
        mode="register",
        checkpoint=None,
    ):
        if mode not in {"register", "copy"}:
            raise InvalidBook("Choose register or copy storage.")
        sources = []
        for name in paths:
            path = self.source_path(root, name)
            sources.append((path, path.relative_to(self.sources[root]).as_posix()))
        if accepted.series_id:
            with self.lock, self.sessions() as session:
                if session.get(Series, accepted.series_id) is None:
                    raise InvalidBook("Choose an existing series/run.")
        if len({name for _, name in sources}) != len(sources):
            raise InvalidBook("Choose each source file only once.")
        if set(paths) != set(expected_hashes):
            raise InvalidBook("Every source needs its preview checksum.")
        expected_hashes = {
            canonical: expected_hashes[name]
            for name, (_, canonical) in zip(paths, sources, strict=True)
        }
        return self._ingest(
            sources,
            root,
            managed_copy=mode == "copy",
            expected_hashes=expected_hashes,
            accepted=accepted,
            checkpoint=checkpoint,
        )

    def _ingest(
        self,
        sources: list[tuple[Path, str]],
        root: str | None = None,
        *,
        managed_copy=False,
        expected_hashes=None,
        accepted=None,
        checkpoint=None,
    ) -> ImportResult:
        with self.ingest_lock:
            return self._ingest_locked(
                sources,
                root,
                managed_copy=managed_copy,
                expected_hashes=expected_hashes,
                accepted=accepted,
                checkpoint=checkpoint,
            )

    def _ingest_locked(
        self,
        sources,
        root,
        *,
        managed_copy=False,
        expected_hashes=None,
        accepted=None,
        checkpoint=None,
    ):
        def checked_digest(path):
            if checkpoint is None:
                return digest(path)
            checksum = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    checkpoint()
                    checksum.update(chunk)
            return checksum.hexdigest()

        if not sources or len(sources) > 2000:
            raise InvalidBook("Choose between 1 and 2000 files.")
        sources = sorted(sources, key=lambda item: (natural_key(item[1]), item[1]))
        if any(not safe_member(name) or len(name) > 1024 for _, name in sources):
            raise InvalidBook("Invalid original filename.")
        observations = {name: path.stat() for path, name in sources} if root else {}
        inspections = []
        for path, name in sources:
            if checkpoint:
                checkpoint()
            inspections.append(inspect_file(path, name))
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
                    sha256=checked_digest(source),
                    size=source.stat().st_size,
                    facts=inspection.facts,
                )
            )
        if root:
            for (_, name), entry in zip(sources, entries, strict=True):
                original, current = observations[name], self.source_path(root, name).stat()
                fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
                if any(getattr(original, field) != getattr(current, field) for field in fields):
                    raise InvalidBook("A source file changed while inspecting it. Wait and retry.")
                entry["relative_path"] = name
                entry["observed_mtime_ns"] = current.st_mtime_ns
            metadata["input_root"] = root
            if not managed_copy:
                metadata["source_root"] = root
        if expected_hashes is not None and any(
            expected_hashes.get(entry["original_name"]) != entry["sha256"] for entry in entries
        ):
            raise InvalidBook("Source bytes changed since preview. Rescan and review them again.")
        if accepted is not None:
            metadata["accepted_metadata"] = accepted.model_dump(exclude_none=True)
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
            if root:
                with self.sessions() as session:
                    registered = session.scalars(
                        select(Asset).where(
                            Asset.root == root,
                            Asset.relative_path.in_([name for _, name in sources]),
                        )
                    )
                    expected = {entry["relative_path"]: entry for entry in entries}
                    for asset in registered:
                        if asset.sha256 != expected[asset.relative_path]["sha256"]:
                            raise InvalidBook(
                                "A registered source path has different bytes. "
                                "Review it before replacing it."
                            )
            with self.sessions() as session:
                existing = session.execute(
                    select(Work.id, Representation.id)
                    .select_from(Work)
                    .join(Edition)
                    .join(Representation)
                    .join(ImportOperation, ImportOperation.id == Representation.id)
                    .where(ImportOperation.sha256 == sha, ImportOperation.state == "complete")
                ).first()
            if not existing and accepted is not None:
                with self.sessions() as session:
                    asset_owner = session.execute(
                        select(Edition.work_id, Representation.id)
                        .select_from(Edition)
                        .join(Representation)
                        .join(Asset)
                        .where(Asset.sha256.in_([entry["sha256"] for entry in entries]))
                        .order_by(Asset.id)
                        .limit(1)
                    ).first()
                    if asset_owner and len(entries) == 1:
                        existing = asset_owner
                    elif asset_owner:
                        raise InvalidBook(
                            "Some tracks already belong to a recording. Regroup that work first."
                        )
            if existing:
                if root and accepted is not None:
                    with self.sessions.begin() as session:
                        for asset in session.scalars(
                            select(Asset).where(
                                Asset.root == root,
                                Asset.relative_path.in_([name for _, name in sources]),
                            )
                        ):
                            match = next(
                                entry
                                for entry in entries
                                if entry["relative_path"] == asset.relative_path
                            )
                            if asset.sha256 == match["sha256"]:
                                asset.observed_mtime_ns = match["observed_mtime_ns"]
                return ImportResult(
                    work=self.get(existing[0]), representation_id=existing[1], duplicate=True
                )
            if root:
                with self.sessions() as session:
                    overlap = session.scalar(
                        select(Asset.id)
                        .where(
                            Asset.root == root,
                            Asset.relative_path.in_([name for _, name in sources]),
                        )
                        .limit(1)
                    )
                    if overlap:
                        raise InvalidBook(
                            "Some source files are already registered in a different set. "
                            "Regroup the existing works first."
                        )
            if root:
                with self.sessions() as session:
                    entries_table = func.json_each(
                        ImportOperation.extracted_json, "$.assets"
                    ).table_valued("value")
                    reserved = session.scalar(
                        select(ImportOperation.id)
                        .join(entries_table, true())
                        .where(
                            ImportOperation.state != "complete",
                            ImportOperation.sha256 != sha,
                            func.coalesce(
                                func.json_extract(ImportOperation.extracted_json, "$.input_root"),
                                func.json_extract(ImportOperation.extracted_json, "$.source_root"),
                            )
                            == root,
                            func.json_extract(entries_table.c.value, "$.relative_path").in_(
                                [name for _, name in sources]
                            ),
                        )
                        .limit(1)
                    )
                    if reserved:
                        raise InvalidBook(
                            "A pending registration already reserves these source files. "
                            "Recover it before choosing a different set."
                        )
            with self.sessions() as session:
                pending = session.scalar(
                    select(ImportOperation.id)
                    .where(ImportOperation.sha256 == sha, ImportOperation.state != "complete")
                    .order_by(ImportOperation.created_at)
                )
        if pending:
            with self.lock, self.sessions.begin() as session:
                operation = session.get(ImportOperation, pending)
                prior = json.loads(operation.extracted_json)
                if accepted is not None and (
                    prior.get("accepted_metadata") != accepted.model_dump(exclude_none=True)
                    or prior.get("source_root") != metadata.get("source_root")
                    or prior.get("input_root", prior.get("source_root")) != root
                    or [entry["original_name"] for entry in prior.get("assets", [])]
                    != [entry["original_name"] for entry in entries]
                ):
                    raise InvalidBook(
                        "An earlier import has different pending choices. "
                        "Recover it before creating a new preview."
                    )
                # A verified retry can refresh source observation times without changing bytes,
                # accepted metadata, storage mode, or original ownership.
                if root and prior.get("source_root") == root:
                    current = {entry["relative_path"]: entry for entry in entries}
                    for old in prior.get("assets", []):
                        verified = current.get(old.get("relative_path"))
                        if verified and old["sha256"] == verified["sha256"]:
                            old["observed_mtime_ns"] = verified["observed_mtime_ns"]
                    operation.extracted_json = json.dumps(prior, ensure_ascii=False)
            work_id = self._publish(pending)
            return ImportResult(work=self.get(work_id), representation_id=pending, duplicate=False)
        operation_id = identity()
        stage = self.staging / operation_id
        stage.mkdir()
        try:
            copying = [] if root and not managed_copy else zip(sources, entries, strict=True)
            for (source, _), entry in copying:
                destination = stage / entry["filename"]
                with source.open("rb") as incoming, destination.open("xb") as out:
                    if checkpoint is None:
                        shutil.copyfileobj(incoming, out, 1024**2)
                    else:
                        while chunk := incoming.read(1024 * 1024):
                            checkpoint()
                            out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if checked_digest(destination) != entry["sha256"]:
                    raise OSError("File verification failed; the upload was not imported.")
            if root:
                for _, name in sources:
                    original, current = observations[name], self.source_path(root, name).stat()
                    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
                    if any(getattr(original, field) != getattr(current, field) for field in fields):
                        raise InvalidBook("A source changed during copying. Rescan and retry.")
            if checkpoint:
                checkpoint()
            if cover:
                write_durable(stage / "cover.jpg", cover)
            sync_dir(stage)
            sync_dir(self.staging)
            with self.lock, self.sessions.begin() as session:
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
        return ImportResult(work=self.get(work_id), representation_id=operation_id, duplicate=False)

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
            root = metadata.get("source_root")
            original = (
                self.source_path(root, entry["relative_path"])
                if root
                else location / entry["filename"]
            )
            if (
                not original.is_file()
                or original.stat().st_size != entry["size"]
                or digest(original) != entry["sha256"]
                or (root and original.stat().st_mtime_ns != entry["observed_mtime_ns"])
            ):
                raise OSError("Import original missing or checksum mismatch; copies retained.")
        if location == stage:
            os.rename(stage, destination)
        # Recovery may observe a rename whose directory sync failed before the crash.
        # Re-establish durability on both paths before acknowledging the catalog commit.
        sync_dir(self.managed)
        sync_dir(self.staging)
        with self.lock, self.sessions.begin() as session:
            operation = session.get(ImportOperation, operation_id)
            metadata = json.loads(operation.extracted_json)
            accepted = metadata.get("accepted_metadata", {})
            chosen = metadata | {key: value for key, value in accepted.items() if value is not None}
            work = Work(title=chosen["title"], description=chosen["description"])
            if metadata.get("source_root") or accepted:
                shelf = accepted.get("shelf", "default")
                work.personal = PersonalState(
                    default_shelf="archive", shelf_override=None if shelf == "default" else shelf
                )
            if accepted.get("series_id"):
                series = session.get(Series, accepted["series_id"])
                if series is None:
                    raise InvalidBook("The accepted series is unavailable. Review before retrying.")
                work.memberships = [
                    SeriesMembership(
                        series_id=series.id,
                        designation=accepted.get("designation", ""),
                        position=accepted.get("position", 0),
                    )
                ]
                if series.following and work.personal:
                    work.personal.default_shelf = "library"
            work.credits = [
                Credit(position=i, contributor=Contributor(name=name))
                for i, name in enumerate(chosen["authors"])
            ]
            edition = Edition(
                medium=metadata.get("medium", "ebook"),
                language=chosen["language"],
                publisher=chosen["publisher"],
                identifier=chosen["identifier"],
                narrator=chosen.get("narrator", ""),
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
                    root=metadata.get("source_root", "managed"),
                    relative_path=entry["relative_path"]
                    if metadata.get("source_root")
                    else f"{operation_id}/{entry['filename']}",
                    observed_mtime_ns=entry.get("observed_mtime_ns"),
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
        with self.ingest_lock:
            self._recover_locked()

    def _recover_locked(self):
        with self.lock, self.sessions() as session:
            pending = list(
                session.scalars(
                    select(ImportOperation.id).where(ImportOperation.state != "complete")
                )
            )
        for operation_id in pending:
            try:
                self._publish(operation_id)
            except (OSError, ValueError, InvalidBook, IntegrityError) as exc:
                with self.lock, self.sessions.begin() as session:
                    operation = session.get(ImportOperation, operation_id)
                    operation.state, operation.error = (
                        "error",
                        (
                            "Catalog ownership conflict; pending files retained for review."
                            if isinstance(exc, IntegrityError)
                            else str(exc)
                        ),
                    )
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
                WorkRedirect,
                CatalogOperation,
                Collection,
                CollectionEntry,
                Progress,
                PersonalState,
                ReadingRecord,
                IntakeJob,
                ScanDirectory,
                InboxCandidate,
                IntakeItem,
                TrashOperation,
                TrashFile,
            ):
                tables[model.__tablename__] = [
                    dict(row)
                    for row in connection.execute(
                        select(model.__table__).order_by(*model.__table__.primary_key.columns)
                    ).mappings()
                ]
            roots = {"managed": {"kind": "managed"}}
            roots.update(
                {
                    row["root"]: {"kind": "external"}
                    for row in tables["asset"]
                    if row["root"] != "managed"
                }
            )
            roots.update({row["root"]: {"kind": "external"} for row in tables["inbox_candidate"]})
            roots.update(
                {row["root"]: {"kind": "external"} for row in tables["intake_job"] if row["root"]}
            )
            return {"schema_version": 12, "roots": roots, "tables": tables}
