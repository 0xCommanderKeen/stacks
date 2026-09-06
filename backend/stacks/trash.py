"""Recoverable work removal: durable original locations, no source-root writes."""

import hashlib
import os

from sqlalchemy import func, literal, select
from sqlalchemy.dialects.sqlite import insert

from stacks.epub import safe_member
from stacks.library import sync_dir, work_out
from stacks.models import (
    Asset,
    Edition,
    Representation,
    TrashFile,
    TrashOperation,
    Work,
    WorkRedirect,
    now,
)
from stacks.schemas import TrashEntryOut, TrashOperationOut, TrashPage


class Stopped(Exception):
    pass


class Trash:
    def __init__(self, library):
        self.library = library

    @staticmethod
    def _out(session, operation):
        total = session.scalar(
            select(func.count())
            .select_from(TrashFile)
            .where(TrashFile.operation_id == operation.id)
        )
        completed = session.scalar(
            select(func.count())
            .select_from(TrashFile)
            .where(TrashFile.operation_id == operation.id, TrashFile.done.is_(True))
        )
        return TrashOperationOut(
            **{
                name: getattr(operation, name)
                for name in ("id", "work_id", "action", "state", "revision", "error", "created_at")
            },
            total=total,
            completed=completed,
        )

    def operation(self, operation_id):
        with self.library.sessions() as session:
            operation = session.get(TrashOperation, operation_id)
            if operation is None:
                raise KeyError(operation_id)
            return self._out(session, operation)

    def for_work(self, work_id):
        with self.library.sessions() as session:
            operation = session.scalar(
                select(TrashOperation)
                .where(TrashOperation.work_id == work_id)
                .order_by(TrashOperation.created_at.desc(), TrashOperation.id.desc())
                .limit(1)
            )
            return self._out(session, operation) if operation else None

    def list(self, q="", limit=24, offset=0):
        with self.library.sessions() as session:
            query = select(Work).where(Work.trashed_at.is_not(None))
            if q.strip():
                query = query.where(Work.title.contains(q.strip(), autoescape=True))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            items = []
            for work in session.scalars(
                query.order_by(Work.trashed_at.desc(), Work.id).limit(limit).offset(offset)
            ):
                operation = session.scalar(
                    select(TrashOperation)
                    .where(TrashOperation.work_id == work.id)
                    .order_by(TrashOperation.created_at.desc(), TrashOperation.id.desc())
                    .limit(1)
                )
                items.append(
                    TrashEntryOut(work=work_out(work), operation=self._out(session, operation))
                )
            return TrashPage(items=items, total=total, limit=limit, offset=offset)

    def request(self, work_id, request):
        with self.library.lock, self.library.sessions.begin() as session:
            work = session.get(Work, work_id)
            if work is None:
                raise KeyError(work_id)
            if session.get(WorkRedirect, work_id):
                raise ValueError("This work was regrouped. Open its current page first.")
            if work.revision != request.revision:
                raise ValueError("This book changed. Reload before moving it.")
            prior = session.scalar(
                select(TrashOperation)
                .where(TrashOperation.work_id == work_id)
                .order_by(TrashOperation.created_at.desc(), TrashOperation.id.desc())
                .limit(1)
            )
            if prior and prior.state != "complete":
                raise ValueError("Finish the existing trash operation before starting another.")
            if request.action == "trash" and work.trashed_at:
                raise ValueError("This book is already in Trash.")
            if request.action == "restore" and (
                not work.trashed_at or not prior or prior.action != "trash"
            ):
                raise ValueError("This book is not ready to restore.")
            operation = TrashOperation(work_id=work_id, action=request.action)
            session.add(operation)
            session.flush()
            if request.action == "trash":
                # One SQL insertion snapshots the owned assets without loading a work's file list.
                files = (
                    select(
                        func.lower(func.hex(func.randomblob(16))),
                        literal(operation.id),
                        Asset.id,
                        Asset.relative_path,
                        literal(".trash/" + operation.id + "/") + Asset.id,
                        Asset.sha256,
                        Asset.size,
                        literal(False),
                    )
                    .select_from(Asset)
                    .join(Representation)
                    .join(Edition)
                    .where(Edition.work_id == work_id, Asset.root == "managed")
                )
                work.trashed_at = now()
            else:
                files = select(
                    func.lower(func.hex(func.randomblob(16))),
                    literal(operation.id),
                    TrashFile.asset_id,
                    TrashFile.destination,
                    TrashFile.source,
                    TrashFile.sha256,
                    TrashFile.size,
                    literal(False),
                ).where(TrashFile.operation_id == prior.id)
            session.execute(
                insert(TrashFile).from_select(
                    [
                        "id",
                        "operation_id",
                        "asset_id",
                        "source",
                        "destination",
                        "sha256",
                        "size",
                        "done",
                    ],
                    files,
                )
            )
            work.revision += 1
            session.flush()
            return self._out(session, operation)

    def retry(self, operation_id, revision):
        with self.library.lock, self.library.sessions.begin() as session:
            operation = session.get(TrashOperation, operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.revision != revision:
                raise ValueError("This operation changed. Refresh before retrying.")
            if operation.state != "error":
                raise ValueError("Only an interrupted operation needs retrying.")
            operation.state, operation.error = "queued", None
            operation.revision += 1
            session.flush()
            return self._out(session, operation)

    def _path(self, relative):
        if not safe_member(relative):
            raise ValueError("The original location is invalid. Storage recovery is required.")
        root = self.library.managed
        path = root / relative
        for part in [path, *path.parents]:
            if part == root:
                break
            if part.is_symlink():
                raise ValueError("Managed original locations must not contain symbolic links.")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("The original location is outside managed storage.")
        return path

    def _verify(self, path, file, stopped):
        before = path.stat()
        if not path.is_file() or before.st_size != file.size:
            raise ValueError(
                "An original has changed. Resolve its storage problem before retrying."
            )
        checksum = hashlib.sha256()
        with path.open("rb") as reader:
            while chunk := reader.read(1024 * 1024):
                if stopped():
                    raise Stopped()
                checksum.update(chunk)
        after = path.stat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if checksum.hexdigest() != file.sha256 or any(
            getattr(before, field) != getattr(after, field) for field in fields
        ):
            raise ValueError(
                "An original has changed. Resolve its storage problem before retrying."
            )

    def _move(self, file, stopped):
        source, destination = self._path(file.source), self._path(file.destination)
        if stopped():
            raise Stopped()
        if destination.exists():
            if source.exists() and not source.samefile(destination):
                raise ValueError(
                    "The destination is occupied. Move the unexpected file aside and retry."
                )
            self._verify(destination, file, stopped)
        else:
            self._verify(source, file, stopped)
            missing = []
            parent = destination.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(exist_ok=True)
                sync_dir(directory.parent)
            self._path(file.destination)
            # Same-filesystem exclusive link never overwrites a destination, even in a race.
            os.link(source, destination)
            self._verify(destination, file, stopped)
        # Recovery must re-establish every destination name's durability too: a prior
        # attempt may have linked/mkdir'd successfully and failed before its directory fsync.
        parent = destination.parent
        while True:
            sync_dir(parent)
            if parent == self.library.managed:
                break
            parent = parent.parent
        if source.exists():
            if not source.samefile(destination):
                raise ValueError("The source changed during relocation. Recovery needs inspection.")
            source.unlink()
        # A destination-only replay may follow a successful unlink but a failed source fsync.
        sync_dir(source.parent)

    def step(self, stopped=lambda: False):
        # Serialize file relocation with direct imports/recovery, never while holding catalog.lock.
        with self.library.ingest_lock:
            with self.library.lock, self.library.sessions.begin() as session:
                operation = session.scalar(
                    select(TrashOperation)
                    .where(TrashOperation.state.in_(["queued", "running"]))
                    .order_by(TrashOperation.created_at, TrashOperation.id)
                    .limit(1)
                )
                if operation is None:
                    return False
                file = session.scalar(
                    select(TrashFile)
                    .where(TrashFile.operation_id == operation.id, TrashFile.done.is_(False))
                    .order_by(TrashFile.id)
                    .limit(1)
                )
                operation.state = "running"
                operation.revision += 1
                operation_id = operation.id
                if file is None:
                    work = session.get(Work, operation.work_id)
                    if operation.action == "restore":
                        work.trashed_at = None
                    work.revision += 1
                    operation.state = "complete"
                    return True
            try:
                self._move(file, stopped)
                with self.library.lock, self.library.sessions.begin() as session:
                    asset = session.get(Asset, file.asset_id)
                    if asset.root != "managed" or asset.relative_path != file.source:
                        raise ValueError("Original ownership changed. Recovery needs inspection.")
                    asset.relative_path = file.destination
                    session.get(TrashFile, file.id).done = True
                    session.get(TrashOperation, operation_id).revision += 1
            except Stopped:
                return False
            except (OSError, ValueError) as exc:
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else (
                        "Relocation interrupted. Check free space, permissions and storage; "
                        "then retry."
                    )
                )
                with self.library.lock, self.library.sessions.begin() as session:
                    operation = session.get(TrashOperation, operation_id)
                    operation.state, operation.error = "error", message
                    operation.revision += 1
            return True
