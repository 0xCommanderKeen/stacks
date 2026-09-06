"""Durable source discovery. SQLite owns checkpoints; one worker owns bounded file work."""

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from sqlalchemy import func, literal, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from stacks.epub import InvalidBook, safe_member
from stacks.inspection import FORMATS, inspect_file
from stacks.models import (
    Asset,
    Edition,
    InboxCandidate,
    IntakeItem,
    IntakeJob,
    Representation,
    ScanDirectory,
    identity,
    now,
)
from stacks.schemas import CandidateOut, CandidatePage, JobOut, JobPage

ACTIVE = ("queued", "running")
LOG = logging.getLogger(__name__)


def touch(job):
    job.revision += 1
    job.updated_at = now()


def observation(path):
    stat = path.stat()
    return dict(
        size=stat.st_size,
        mtime=stat.st_mtime_ns,
        ctime=stat.st_ctime_ns,
        device=stat.st_dev,
        inode=stat.st_ino,
    )


class Interrupted(Exception):
    pass


class Intake:
    def __init__(self, library, stable_seconds=30):
        self.library = library
        self.stable_seconds = stable_seconds
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.directory = None
        self.iterator = None
        self.skipped = 0

    def start(self):
        if self.thread is not None:
            raise RuntimeError("The intake worker is already started.")
        self.thread = threading.Thread(target=self._run, name="stacks-intake", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join()
        self._close_directory()

    def _close_directory(self):
        if self.iterator is not None:
            self.iterator.close()
        self.iterator, self.directory, self.skipped = None, None, 0

    def _directory_path(self, root, relative):
        if root not in self.library.sources or (relative and not safe_member(relative)):
            raise ValueError("Choose a configured source and a safe relative folder.")
        source = self.library.sources[root]
        path = (source / relative).resolve()
        if not path.is_relative_to(source) or not path.is_dir():
            raise ValueError("The source folder is unavailable or outside its configured root.")
        return path

    def scan(self, request):
        path = self._directory_path(request.root, request.prefix)
        prefix = path.relative_to(self.library.sources[request.root]).as_posix()
        if prefix == ".":
            prefix = ""
        with self.library.lock, self.library.sessions.begin() as session:
            job = IntakeJob(root=request.root, prefix=prefix)
            session.add(job)
            session.flush()
            # Include previously seen paths so a rescan reports missing originals too.
            existing = select(
                func.lower(func.hex(func.randomblob(16))),
                literal(job.id),
                InboxCandidate.id,
                literal("pending"),
            ).where(InboxCandidate.root == request.root)
            if prefix:
                existing = existing.where(
                    InboxCandidate.relative_path.startswith(prefix + "/", autoescape=True)
                )
            session.execute(
                insert(IntakeItem).from_select(
                    ["id", "job_id", "candidate_id", "state"],
                    existing,
                )
            )
            session.add(ScanDirectory(job_id=job.id, path=prefix))
            session.flush()
            result = self._job_out(session, job)
        self.wake.set()
        return result

    def change(self, job_id, request):
        with self.library.lock, self.library.sessions.begin() as session:
            job = session.get(IntakeJob, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.revision != request.revision:
                raise ValueError("This job changed. Refresh before changing it.")
            if request.action == "cancel":
                if job.state not in ACTIVE:
                    raise ValueError("Only queued or running jobs can be cancelled.")
                job.state = "cancelled"
            else:
                if job.state in ACTIVE:
                    raise ValueError("This job is already active.")
                job.state, job.error = "queued", None
                session.execute(
                    update(IntakeItem)
                    .where(
                        IntakeItem.job_id == job.id,
                        IntakeItem.state.in_(["error", "waiting"]),
                    )
                    .values(state="pending")
                )
            touch(job)
            session.flush()
            result = self._job_out(session, job)
        self.wake.set()
        return result

    @staticmethod
    def _job_out(session, job):
        counts = dict(
            session.execute(
                select(IntakeItem.state, func.count())
                .where(IntakeItem.job_id == job.id)
                .group_by(IntakeItem.state)
            ).all()
        )
        skipped = session.scalar(
            select(func.coalesce(func.sum(ScanDirectory.skipped), 0)).where(
                ScanDirectory.job_id == job.id
            )
        )
        remaining_dirs = session.scalar(
            select(func.count())
            .select_from(ScanDirectory)
            .where(ScanDirectory.job_id == job.id, ScanDirectory.done.is_(False))
        )
        return JobOut(
            **{
                name: getattr(job, name)
                for name in (
                    "id",
                    "root",
                    "prefix",
                    "state",
                    "revision",
                    "error",
                    "created_at",
                    "updated_at",
                )
            },
            discovered=sum(counts.values()),
            completed=counts.get("done", 0),
            remaining=counts.get("pending", 0),
            skipped=skipped + counts.get("waiting", 0),
            failed=counts.get("error", 0),
            directories_remaining=remaining_dirs,
        )

    def jobs(self, limit=24, offset=0):
        with self.library.sessions() as session:
            return JobPage(
                items=[
                    self._job_out(session, job)
                    for job in session.scalars(
                        select(IntakeJob)
                        .order_by(IntakeJob.created_at.desc(), IntakeJob.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=session.scalar(select(func.count()).select_from(IntakeJob)),
                limit=limit,
                offset=offset,
            )

    def candidates(self, q="", state="", root="", job_id="", limit=24, offset=0):
        with self.library.sessions() as session:
            current_owner = (
                select(Edition.work_id)
                .join(Representation)
                .join(Asset)
                .where(Asset.sha256 == InboxCandidate.sha256)
                .order_by(Asset.id)
                .limit(1)
                .correlate(InboxCandidate)
                .scalar_subquery()
            )
            query = select(InboxCandidate, current_owner)
            if q.strip():
                query = query.where(
                    or_(
                        InboxCandidate.relative_path.contains(q.strip(), autoescape=True),
                        func.json_extract(InboxCandidate.facts_json, "$.title").contains(
                            q.strip(), autoescape=True
                        ),
                    )
                )
            if state:
                query = query.where(InboxCandidate.state == state)
            if root:
                query = query.where(InboxCandidate.root == root)
            if job_id:
                query = query.where(
                    select(IntakeItem.id)
                    .where(
                        IntakeItem.candidate_id == InboxCandidate.id, IntakeItem.job_id == job_id
                    )
                    .exists()
                )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            items = [
                CandidateOut(
                    **{
                        name: getattr(candidate, name)
                        for name in (
                            "id",
                            "root",
                            "relative_path",
                            "state",
                            "revision",
                            "sha256",
                            "error",
                            "updated_at",
                        )
                    },
                    facts=json.loads(candidate.facts_json),
                    edits=json.loads(candidate.edits_json),
                    work_id=current_work_id,
                )
                for candidate, current_work_id in session.execute(
                    query.order_by(
                        InboxCandidate.root, InboxCandidate.relative_path, InboxCandidate.id
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ]
            return CandidatePage(items=items, total=total, limit=limit, offset=offset)

    def _check(self, job_id):
        if self.stop.is_set():
            raise Interrupted()
        with self.library.sessions() as session:
            if session.get(IntakeJob, job_id).state not in ACTIVE:
                raise Interrupted()

    def _run(self):
        try:
            while not self.stop.is_set():
                if not self.step():
                    self.wake.wait(1)
                    self.wake.clear()
        finally:
            self._close_directory()

    def step(self):
        """One directory chunk and one inspection; also used for deterministic restart tests."""
        with self.library.lock, self.library.sessions.begin() as session:
            job = session.scalar(
                select(IntakeJob)
                .where(IntakeJob.state.in_(ACTIVE))
                .order_by(IntakeJob.created_at, IntakeJob.id)
                .limit(1)
            )
            if job is None:
                self._close_directory()
                return False
            job_id, root = job.id, job.root
            if job.state == "queued":
                job.state = "running"
                touch(job)
        try:
            self._check(job_id)
            self._discover(job_id, root)
            self._check(job_id)
            self._inspect_next(job_id)
            with self.library.lock, self.library.sessions.begin() as session:
                job = session.get(IntakeJob, job_id)
                pending = session.scalar(
                    select(IntakeItem.id)
                    .where(IntakeItem.job_id == job_id, IntakeItem.state == "pending")
                    .limit(1)
                )
                directory = session.scalar(
                    select(ScanDirectory.id)
                    .where(ScanDirectory.job_id == job_id, ScanDirectory.done.is_(False))
                    .limit(1)
                )
                if job.state in ACTIVE and pending is None and directory is None:
                    job.state = "completed"
                    touch(job)
        except Interrupted:
            self._close_directory()
        except Exception:
            self._close_directory()
            # Do not emit exception text: OS errors can contain configured host paths.
            LOG.error("intake_job_failed job_id=%s", job_id)
            with self.library.lock, self.library.sessions.begin() as session:
                job = session.get(IntakeJob, job_id)
                if job.state in ACTIVE:
                    job.state = "error"
                    job.error = "Scan interrupted. Check the source mount and storage, then retry."
                    touch(job)
        return True

    def _discover(self, job_id, root):
        with self.library.sessions() as session:
            directory = session.get(ScanDirectory, self.directory) if self.directory else None
            if directory is None or directory.job_id != job_id or directory.done:
                directory = session.scalar(
                    select(ScanDirectory)
                    .where(ScanDirectory.job_id == job_id, ScanDirectory.done.is_(False))
                    .order_by(ScanDirectory.id)
                    .limit(1)
                )
            if directory is None:
                self._close_directory()
                return
            directory_id, relative = directory.id, directory.path
        if self.directory != directory_id:
            self._close_directory()
            path = self._directory_path(root, relative)
            self.iterator, self.directory = os.scandir(path), directory_id
        entries = []
        finished = False
        for _ in range(32):
            self._check(job_id)
            try:
                entry = next(self.iterator)
            except StopIteration:
                finished = True
                break
            # Directory symlinks are deliberately not followed: no cycles or alias trees.
            if entry.is_dir(follow_symlinks=False):
                entries.append(("directory", (Path(relative) / entry.name).as_posix()))
            elif Path(entry.name).suffix.lower().lstrip(".") in FORMATS:
                file_relative = (Path(relative) / entry.name).as_posix()
                try:
                    file_relative = (
                        self.library.source_path(root, file_relative)
                        .relative_to(self.library.sources[root])
                        .as_posix()
                    )
                except (OSError, ValueError):
                    pass  # Inspection records an explicit unavailable/escaping-file exception.
                entries.append(("file", file_relative))
            else:
                self.skipped += 1
        with self.library.lock, self.library.sessions.begin() as session:
            job = session.get(IntakeJob, job_id)
            if job.state not in ACTIVE:
                raise Interrupted()
            for kind, relative_path in entries:
                if kind == "directory":
                    session.execute(
                        insert(ScanDirectory)
                        .values(
                            id=identity(), job_id=job_id, path=relative_path, done=False, skipped=0
                        )
                        .on_conflict_do_nothing(index_elements=["job_id", "path"])
                    )
                else:
                    session.execute(
                        insert(InboxCandidate)
                        .values(
                            id=identity(),
                            root=root,
                            relative_path=relative_path,
                        )
                        .on_conflict_do_nothing(index_elements=["root", "relative_path"])
                    )
                    candidate_id = session.scalar(
                        select(InboxCandidate.id).where(
                            InboxCandidate.root == root,
                            InboxCandidate.relative_path == relative_path,
                        )
                    )
                    session.execute(
                        insert(IntakeItem)
                        .values(
                            id=identity(),
                            job_id=job_id,
                            candidate_id=candidate_id,
                        )
                        .on_conflict_do_nothing(index_elements=["job_id", "candidate_id"])
                    )
            if finished:
                directory = session.get(ScanDirectory, directory_id)
                directory.done, directory.skipped = True, self.skipped
            touch(job)
        if finished:
            self._close_directory()

    def _inspect_next(self, job_id):
        with self.library.sessions() as session:
            item = session.scalar(
                select(IntakeItem)
                .where(IntakeItem.job_id == job_id, IntakeItem.state == "pending")
                .order_by(IntakeItem.id)
                .limit(1)
            )
            if item is None:
                return
            item_id = item.id
            candidate = session.get(InboxCandidate, item.candidate_id)
            candidate_id, revision = candidate.id, candidate.revision
            root, relative = candidate.root, candidate.relative_path
            previous = json.loads(candidate.observation_json)
            facts, sha = json.loads(candidate.facts_json), candidate.sha256
        state, error, observed = "ready", None, {}
        try:
            path = self.library.source_path(root, relative)
            observed = observation(path)
            if time.time_ns() - observed["mtime"] < self.stable_seconds * 1_000_000_000:
                state, error = "waiting", "Recently modified file; retry after writing finishes."
            else:
                if observed != previous or not sha:
                    facts = inspect_file(path, path.name).facts
                    self._check(job_id)
                    checksum = hashlib.sha256()
                    with path.open("rb") as source:
                        while chunk := source.read(1024 * 1024):
                            self._check(job_id)
                            checksum.update(chunk)
                    sha = checksum.hexdigest()
                if observation(path) != observed:
                    state, error = (
                        "waiting",
                        "The source changed during inspection; retry when stable.",
                    )
                elif facts.get("medium") == "audio":
                    state = "review"
        except InvalidBook as exc:
            state, error = "error", str(exc)
        except (OSError, ValueError):
            state, error = (
                "error",
                "Original unavailable or outside its source. Check the mount and relative path.",
            )
        self._check(job_id)
        with self.library.lock, self.library.sessions.begin() as session:
            job = session.get(IntakeJob, job_id)
            if job.state not in ACTIVE:
                raise Interrupted()
            candidate = session.get(InboxCandidate, candidate_id)
            if candidate.revision != revision:
                return  # A later owner edit wins; retry against its current revision.
            work_id = None
            if state in {"ready", "review"}:
                work_id = session.scalar(
                    select(Edition.work_id)
                    .join(Representation)
                    .join(Asset)
                    .where(Asset.sha256 == sha)
                    .limit(1)
                )
                if work_id:
                    state = "duplicate"
            candidate.state, candidate.error = state, error
            candidate.observation_json = (
                json.dumps(observed) if state not in {"error", "waiting"} else "{}"
            )
            if state not in {"error", "waiting"}:
                candidate.facts_json, candidate.sha256 = json.dumps(facts), sha
            candidate.revision += 1
            candidate.updated_at = now()
            session.get(IntakeItem, item_id).state = (
                state if state in {"error", "waiting"} else "done"
            )
            touch(job)
