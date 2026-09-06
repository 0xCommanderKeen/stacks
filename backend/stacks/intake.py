"""Durable source discovery. SQLite owns checkpoints; one worker owns bounded file work."""

import hashlib
import json
import logging
import os
import re
import threading
import time
from fractions import Fraction
from pathlib import Path

from sqlalchemy import func, literal, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from stacks.epub import InvalidBook, safe_member
from stacks.inspection import FORMATS, inspect_file, natural_key
from stacks.library import series_out
from stacks.models import (
    Asset,
    Edition,
    InboxCandidate,
    IntakeItem,
    IntakeJob,
    Representation,
    ScanDirectory,
    Series,
    identity,
    now,
)
from stacks.schemas import (
    AcceptanceItemOut,
    AcceptancePage,
    AcceptedMetadata,
    CandidateOut,
    CandidatePage,
    JobOut,
    JobPage,
)
from stacks.trash import Trash

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
        self.trash = Trash(library)
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
        with self.library.lock, self.library.sessions.begin() as session:
            session.execute(
                update(IntakeItem).where(IntakeItem.state == "running").values(state="pending")
            )
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
            if request.action == "confirm":
                if job.state != "preview" or job.kind != "accept":
                    raise ValueError("Only an acceptance preview can be confirmed.")
                stale = session.scalar(
                    select(IntakeItem.id)
                    .join(InboxCandidate)
                    .where(
                        IntakeItem.job_id == job.id,
                        IntakeItem.candidate_revision != InboxCandidate.revision,
                    )
                    .limit(1)
                )
                if stale:
                    raise ValueError("Candidates changed. Create a new preview before accepting.")
                job.state = "queued"
            elif request.action == "cancel":
                if job.state not in (*ACTIVE, "preview"):
                    raise ValueError("Only previews or active jobs can be cancelled.")
                job.state = "cancelled"
            else:
                if job.state in ACTIVE or job.state == "preview":
                    raise ValueError("This job is active or still needs preview confirmation.")
                if job.kind == "accept" and not json.loads(job.options_json).get("confirmed"):
                    raise ValueError("Create a new preview to accept these files.")
                job.state, job.error = "queued", None
                session.execute(
                    update(IntakeItem)
                    .where(
                        IntakeItem.job_id == job.id,
                        IntakeItem.state.in_(["error", "waiting"]),
                    )
                    .values(state="pending")
                )
            if request.action == "confirm":
                options = json.loads(job.options_json)
                options["confirmed"] = True
                job.options_json = json.dumps(options)
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
                    "kind",
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
            completed=counts.get("done", 0) + counts.get("accepted", 0),
            remaining=counts.get("pending", 0) + counts.get("running", 0),
            skipped=skipped + counts.get("waiting", 0) + counts.get("duplicate", 0),
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
                try:
                    worked = self.step()
                except Exception:
                    # A full/unavailable database may prevent even recording a job error.
                    # Keep the executor alive so durable work can retry when storage returns.
                    LOG.error("intake_storage_unavailable")
                    worked = False
                if not worked:
                    self.wake.wait(1)
                    self.wake.clear()
        finally:
            self._close_directory()

    def step(self):
        """One bounded storage/acceptance/scan step; SQLite owns recovery checkpoints."""
        if self.trash.step(self.stop.is_set):
            self._close_directory()
            return True
        with self.library.lock, self.library.sessions.begin() as session:
            job = session.scalar(
                select(IntakeJob)
                .where(IntakeJob.state.in_(ACTIVE))
                .order_by(IntakeJob.kind, IntakeJob.created_at, IntakeJob.id)
                .limit(1)
            )
            if job is None:
                self._close_directory()
                return False
            job_id, root, kind = job.id, job.root, job.kind
            if job.state == "queued":
                job.state = "running"
                touch(job)
        try:
            self._check(job_id)
            if kind == "scan":
                self._discover(job_id, root)
                self._check(job_id)
                self._inspect_next(job_id)
            else:
                self._close_directory()
                self._accept_next(job_id)
            with self.library.lock, self.library.sessions.begin() as session:
                job = session.get(IntakeJob, job_id)
                pending = session.scalar(
                    select(IntakeItem.id)
                    .where(
                        IntakeItem.job_id == job_id, IntakeItem.state.in_(["pending", "running"])
                    )
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
                elif session.scalar(
                    select(IntakeItem.id)
                    .where(
                        IntakeItem.candidate_id == candidate.id,
                        IntakeItem.state.in_(["accepted", "duplicate"]),
                    )
                    .limit(1)
                ):
                    state = "review"
                    error = (
                        "Source bytes changed after acceptance. Review this replacement explicitly."
                    )
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

    def edit_candidate(self, candidate_id, request):
        with self.library.lock, self.library.sessions.begin() as session:
            candidate = session.get(InboxCandidate, candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate.revision != request.revision:
                raise ValueError("This candidate changed. Refresh before editing.")
            active = session.scalar(
                select(IntakeItem.id)
                .join(IntakeJob)
                .where(
                    IntakeItem.candidate_id == candidate_id,
                    IntakeJob.kind == "accept",
                    or_(
                        IntakeItem.state == "running",
                        (IntakeItem.state == "pending") & IntakeJob.state.in_(ACTIVE),
                    ),
                )
                .limit(1)
            )
            if active:
                raise ValueError("This candidate is being accepted. Wait for its job to stop.")
            if (
                request.metadata.series_id
                and session.get(Series, request.metadata.series_id) is None
            ):
                raise ValueError("Choose an existing series/run.")
            candidate.edits_json = request.metadata.model_dump_json(exclude_unset=True)
            candidate.revision += 1
            candidate.updated_at = now()
        return self.candidate(candidate_id)

    def candidate(self, candidate_id):
        with self.library.sessions() as session:
            candidate = session.get(InboxCandidate, candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            return self._candidate_out(session, candidate)

    @staticmethod
    def _candidate_out(session, candidate):
        current_owner = session.scalar(
            select(Edition.work_id)
            .join(Representation)
            .join(Asset)
            .where(Asset.sha256 == candidate.sha256)
            .order_by(Asset.id)
            .limit(1)
        )
        return CandidateOut(
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
            work_id=current_owner,
            facts=json.loads(candidate.facts_json),
            edits=json.loads(candidate.edits_json),
        )

    def preview_acceptance(self, request):
        if request.group_audio and request.candidate_ids is None:
            raise ValueError("Choose explicit audio tracks before grouping a recording.")
        with self.library.lock, self.library.sessions.begin() as session:
            query = select(InboxCandidate)
            if request.candidate_ids is not None:
                query = query.where(InboxCandidate.id.in_(request.candidate_ids))
            else:
                if request.q.strip():
                    query = query.where(
                        or_(
                            InboxCandidate.relative_path.contains(
                                request.q.strip(), autoescape=True
                            ),
                            func.json_extract(InboxCandidate.facts_json, "$.title").contains(
                                request.q.strip(), autoescape=True
                            ),
                        )
                    )
                if request.root:
                    query = query.where(InboxCandidate.root == request.root)
                if request.state:
                    query = query.where(InboxCandidate.state == request.state)
                else:
                    query = query.where(InboxCandidate.state.in_(["ready", "duplicate"]))
                if request.scan_id:
                    query = query.where(
                        select(IntakeItem.id)
                        .where(
                            IntakeItem.candidate_id == InboxCandidate.id,
                            IntakeItem.job_id == request.scan_id,
                        )
                        .exists()
                    )
            count = session.scalar(select(func.count()).select_from(query.subquery()))
            if not count or (
                request.candidate_ids is not None and count != len(set(request.candidate_ids))
            ):
                raise ValueError("Choose existing eligible candidates for the preview.")
            if session.scalar(
                query.where(
                    or_(
                        InboxCandidate.state.not_in(["ready", "review", "duplicate"]),
                        InboxCandidate.sha256.is_(None),
                    )
                ).limit(1)
            ):
                raise ValueError("Some candidates need a stable rescan before acceptance.")
            audio = func.json_extract(InboxCandidate.facts_json, "$.medium") == "audio"
            if request.group_audio:
                roots = session.scalars(
                    query.with_only_columns(InboxCandidate.root).distinct()
                ).all()
                if len(roots) != 1 or session.scalar(query.where(~audio).limit(1)):
                    raise ValueError("A recording must contain only audio files from one source.")
            elif not request.audio_singles_confirmed and session.scalar(
                query.where(audio).limit(1)
            ):
                raise ValueError(
                    "Review audio grouping or explicitly confirm individual audio files."
                )
            if (
                request.metadata.series_id
                and session.get(Series, request.metadata.series_id) is None
            ):
                raise ValueError("Choose an existing series/run.")
            options = request.model_dump(exclude={"candidate_ids", "metadata"})
            options["metadata"] = request.metadata.model_dump(exclude_unset=True)
            job = IntakeJob(
                kind="accept",
                root=request.root,
                prefix="",
                state="preview",
                options_json=json.dumps(options),
            )
            session.add(job)
            session.flush()
            grouped_id = identity() if request.group_audio else None
            facts = []
            for field in (
                "title",
                "authors",
                "description",
                "language",
                "publisher",
                "identifier",
                "narrator",
                "series_hint",
            ):
                facts.extend([field, func.json_extract(InboxCandidate.facts_json, f"$.{field}")])
            snapshot = func.json_object(
                "sha256",
                InboxCandidate.sha256,
                "facts",
                func.json_object(*facts),
                "edits",
                func.json(InboxCandidate.edits_json),
            )
            selected = query.with_only_columns(
                func.lower(func.hex(func.randomblob(16))),
                literal(job.id),
                InboxCandidate.id,
                literal("pending"),
                InboxCandidate.revision,
                literal(grouped_id) if grouped_id else InboxCandidate.id,
                snapshot,
            )
            session.execute(
                insert(IntakeItem).from_select(
                    [
                        "id",
                        "job_id",
                        "candidate_id",
                        "state",
                        "candidate_revision",
                        "group_id",
                        "snapshot_json",
                    ],
                    selected,
                )
            )
            session.flush()
            return self._job_out(session, job)

    @staticmethod
    def _accepted(snapshot, options):
        data = json.loads(snapshot)
        values = {
            key: value
            for key, value in data["facts"].items()
            if key != "series_hint" and value is not None
        }
        values.update(data["edits"])
        values.update(options.get("metadata", {}))
        overrides = data["edits"] | options.get("metadata", {})
        values["manual_fields"] = [
            field
            for field in ("title", "authors", "description")
            if field in overrides and overrides[field] is not None
        ]
        if values.get("series_id"):
            hint = data["facts"].get("series_hint") or {}
            if "designation" not in values:
                values["designation"] = str(hint.get("designation", ""))[:100]
            if "position" not in values:
                try:
                    number = values["designation"].lstrip("#").strip()
                    if not re.fullmatch(r"-?\d{1,12}(?:\.\d{1,6}|/\d{1,12})?", number):
                        raise ValueError("No bounded numeric designation")
                    values["position"] = AcceptedMetadata(position=float(Fraction(number))).position
                except (ValueError, ZeroDivisionError):
                    values["position"] = 0
        return AcceptedMetadata.model_validate(values)

    def acceptance(self, job_id, limit=24, offset=0):
        with self.library.sessions() as session:
            job = session.get(IntakeJob, job_id)
            if job is None or job.kind != "accept":
                raise KeyError(job_id)
            options = json.loads(job.options_json)
            query = (
                select(IntakeItem, InboxCandidate)
                .join(InboxCandidate)
                .where(IntakeItem.job_id == job_id)
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            if options["group_audio"]:
                # Explicit groups have at most 2000 tracks; this cannot load the whole archive.
                rows = session.execute(query.limit(2000)).all()
                rows.sort(key=lambda row: (natural_key(row[1].relative_path), row[1].relative_path))
                metadata = (
                    self._accepted(rows[0][0].snapshot_json, options)
                    if rows
                    else AcceptedMetadata()
                )
                rows = rows[offset : offset + limit]
            else:
                rows = session.execute(
                    query.order_by(InboxCandidate.root, InboxCandidate.relative_path, IntakeItem.id)
                    .limit(limit)
                    .offset(offset)
                ).all()
                metadata = None
            return AcceptancePage(
                confirmed=bool(options.get("confirmed")),
                job=self._job_out(session, job),
                mode=options["mode"],
                grouped_audio=options["group_audio"],
                items=[
                    self._acceptance_item(
                        session,
                        item,
                        candidate,
                        metadata or self._accepted(item.snapshot_json, options),
                    )
                    for item, candidate in rows
                ],
                total=total,
                limit=limit,
                offset=offset,
            )

    def _acceptance_item(self, session, item, candidate, metadata):
        current = self._candidate_out(session, candidate)
        snapshot = json.loads(item.snapshot_json)
        owner = session.scalar(
            select(Edition.work_id)
            .join(Representation)
            .join(Asset)
            .where(
                Representation.id == item.result_representation_id
                if item.result_representation_id
                else Asset.sha256 == snapshot["sha256"]
            )
            .order_by(Asset.id)
            .limit(1)
        )
        current = current.model_copy(
            update={
                "facts": snapshot["facts"],
                "edits": snapshot["edits"],
                "sha256": snapshot["sha256"],
                "work_id": owner,
            }
        )
        series = session.get(Series, metadata.series_id) if metadata.series_id else None
        return AcceptanceItemOut(
            id=item.id,
            group_id=item.group_id,
            candidate=current,
            metadata=metadata,
            series=series_out(series) if series else None,
            state=item.state,
            error=item.error,
            work_id=current.work_id if item.result_representation_id else None,
        )

    def _accept_next(self, job_id):
        with self.library.lock, self.library.sessions.begin() as session:
            item = session.scalar(
                select(IntakeItem)
                .where(IntakeItem.job_id == job_id, IntakeItem.state.in_(["pending", "running"]))
                .order_by(IntakeItem.id)
                .limit(1)
            )
            if item is None:
                return
            group_id = item.group_id
            rows = session.execute(
                select(IntakeItem, InboxCandidate)
                .join(InboxCandidate)
                .where(
                    IntakeItem.job_id == job_id,
                    IntakeItem.group_id == group_id,
                )
                .limit(2000)
            ).all()
            rows.sort(key=lambda row: (natural_key(row[1].relative_path), row[1].relative_path))
            job = session.get(IntakeJob, job_id)
            options = json.loads(job.options_json)
            stale = any(candidate.revision != entry.candidate_revision for entry, candidate in rows)
            for entry, _ in rows:
                entry.state = "running"
            touch(job)
        try:
            self._check(job_id)
            if stale:
                raise ValueError("Candidate metadata changed. Create a new acceptance preview.")
            candidates = [candidate for _, candidate in rows]
            metadata = self._accepted(rows[0][0].snapshot_json, options)
            result = self.library.accept_sources(
                candidates[0].root,
                [c.relative_path for c in candidates],
                {
                    candidate.relative_path: json.loads(entry.snapshot_json)["sha256"]
                    for entry, candidate in rows
                },
                metadata,
                options["mode"],
                lambda: self._check(job_id),
            )
            # Publication is now durable. Record it even if cancellation arrived during that commit.
            with self.library.lock, self.library.sessions.begin() as session:
                for entry, candidate in rows:
                    current_item = session.get(IntakeItem, entry.id)
                    current_item.state = "duplicate" if result.duplicate else "accepted"
                    current_item.result_representation_id = result.representation_id
                    current_item.error = None
                    current = session.get(InboxCandidate, candidate.id)
                    if current.revision == entry.candidate_revision:
                        current.state = "accepted"
                        current.error = None
                        current.revision += 1
                        current.updated_at = now()
                touch(session.get(IntakeJob, job_id))
        except Interrupted:
            with self.library.lock, self.library.sessions.begin() as session:
                session.execute(
                    update(IntakeItem)
                    .where(
                        IntakeItem.job_id == job_id,
                        IntakeItem.group_id == group_id,
                        IntakeItem.state == "running",
                    )
                    .values(state="pending")
                )
            raise
        except (OSError, ValueError) as exc:
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "Publication interrupted. Check storage and retry; staged files are retained."
            )
            with self.library.lock, self.library.sessions.begin() as session:
                session.execute(
                    update(IntakeItem)
                    .where(
                        IntakeItem.job_id == job_id,
                        IntakeItem.group_id == group_id,
                    )
                    .values(state="error", error=message)
                )
                touch(session.get(IntakeJob, job_id))
