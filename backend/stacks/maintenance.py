"""One bounded backup executor with durable history and operator-visible health."""

import logging
import re
import shutil
import threading
import time

from sqlalchemy import func, select

from stacks.backup import backup, sync_dir
from stacks.models import BackupRecord, IntakeItem, IntakeJob, TrashOperation, now
from stacks.schemas import BackupOut, BackupPage, MaintenanceOut
from stacks.sources import Sources

logger = logging.getLogger(__name__)


class Backups:
    def __init__(self, library):
        self.library = library
        self.directory = library.data_dir / "backups"
        if self.directory.is_symlink():
            raise ValueError("Backup storage must not be a symlink.")
        self.directory.mkdir(exist_ok=True)
        # The library owner lock excludes another process. Remove only our own
        # interrupted scratch names; publication originals never live here.
        for path in self.directory.iterdir():
            if path.is_symlink():
                continue
            if path.is_dir() and path.name.startswith(".stacks-backup-"):
                shutil.rmtree(path)
            elif path.is_file() and re.fullmatch(
                r"[0-9a-f-]{36}\.zip\.[0-9a-f]{32}\.partial", path.name
            ):
                path.unlink()
        sync_dir(self.directory)
        self.stopped = threading.Event()
        self.thread = None
        with library.lock, library.sessions.begin() as session:
            for record in session.scalars(
                select(BackupRecord).where(BackupRecord.state.in_(["queued", "running"]))
            ):
                record.state = "error"
                record.error = "Interrupted by restart. Create a new backup."
                record.finished_at = now()

    def _path(self, backup_id):
        from uuid import UUID

        try:
            if str(UUID(backup_id)) != backup_id:
                raise ValueError
        except ValueError:
            raise KeyError(backup_id) from None
        return self.directory / f"{backup_id}.zip"

    def _out(self, record):
        path = self._path(record.id)
        return BackupOut(
            **{
                name: getattr(record, name)
                for name in BackupOut.model_fields
                if name != "available"
            },
            available=record.state == "complete" and path.is_file() and not path.is_symlink(),
        )

    def create(self, request):
        with self.library.lock, self.library.sessions.begin() as session:
            if session.scalar(
                select(BackupRecord.id).where(BackupRecord.state.in_(["queued", "running"]))
            ):
                raise ValueError("A backup is already queued or running.")
            if sum(1 for _ in self.directory.glob("*.zip")) >= 3:
                raise ValueError(
                    "Remove a saved server copy before creating another backup "
                    "(three retained copies maximum)."
                )
            record = BackupRecord(mode=request.mode)
            session.add(record)
            session.flush()
            return self._out(record)

    def list(self, limit=12, offset=0):
        with self.library.sessions() as session:
            return BackupPage(
                items=[
                    self._out(record)
                    for record in session.scalars(
                        select(BackupRecord)
                        .order_by(BackupRecord.created_at.desc(), BackupRecord.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=session.scalar(select(func.count()).select_from(BackupRecord)),
                limit=limit,
                offset=offset,
            )

    def download(self, backup_id):
        with self.library.sessions() as session:
            record = session.get(BackupRecord, backup_id)
            if record is None or not self._out(record).available:
                raise KeyError(backup_id)
            return self._path(backup_id), f"stacks.{record.mode}.backup.zip"

    def remove_copy(self, backup_id):
        with self.library.lock, self.library.sessions() as session:
            record = session.get(BackupRecord, backup_id)
            if record is None:
                raise KeyError(backup_id)
            if record.state in {"queued", "running"}:
                raise ValueError("Wait for this backup to finish before removing its server copy.")
            self._path(backup_id).unlink(missing_ok=True)
            sync_dir(self.directory)

    def health(self):
        with self.library.sessions() as session:
            latest = session.scalar(
                select(BackupRecord)
                .where(BackupRecord.state == "complete")
                .order_by(BackupRecord.finished_at.desc())
                .limit(1)
            )
            return MaintenanceOut(
                disk_free_bytes=shutil.disk_usage(self.library.data_dir).free,
                pending_intake=session.scalar(
                    select(func.count())
                    .select_from(IntakeJob)
                    .where(IntakeJob.state.in_(["queued", "running"]))
                ),
                failed_intake=session.scalar(
                    select(func.count())
                    .select_from(IntakeJob)
                    .where(
                        (IntakeJob.state == "error")
                        | select(IntakeItem.id)
                        .where(IntakeItem.job_id == IntakeJob.id, IntakeItem.state == "error")
                        .exists()
                    )
                ),
                pending_trash=session.scalar(
                    select(func.count())
                    .select_from(TrashOperation)
                    .where(TrashOperation.state != "complete")
                ),
                last_backup=self._out(latest) if latest else None,
                sources=Sources(self.library).list(),
            )

    def start(self):
        self.thread = threading.Thread(target=self._run, name="stacks-backup", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join()

    def _run(self):
        while not self.stopped.is_set():
            try:
                if not self.step():
                    self.stopped.wait(0.5)
            except Exception:
                logger.exception("Backup worker could not advance; retrying shortly.")
                self.stopped.wait(1)

    def step(self):
        with self.library.lock, self.library.sessions.begin() as session:
            record = session.scalar(
                select(BackupRecord)
                .where(BackupRecord.state == "queued")
                .order_by(BackupRecord.created_at)
                .limit(1)
            )
            if record is None:
                return False
            record.state = "running"
            backup_id, mode = record.id, record.mode
        last_progress = 0.0

        def checkpoint(size):
            nonlocal last_progress
            if self.stopped.is_set():
                raise ValueError("Backup stopped during shutdown. Create a new backup.")
            if time.monotonic() - last_progress >= 1:
                with self.library.lock, self.library.sessions.begin() as session:
                    session.get(BackupRecord, backup_id).bytes = size
                last_progress = time.monotonic()

        try:
            path = self._path(backup_id)
            backup(self.library, path, mode, checkpoint)
            with self.library.lock, self.library.sessions.begin() as session:
                record = session.get(BackupRecord, backup_id)
                record.state, record.finished_at, record.bytes = (
                    "complete",
                    now(),
                    path.stat().st_size,
                )
        except Exception as exc:
            try:
                self._path(backup_id).unlink(missing_ok=True)
                sync_dir(self.directory)
            except OSError:
                logger.warning("Unable to remove failed backup copy %s.", backup_id)
            with self.library.lock, self.library.sessions.begin() as session:
                record = session.get(BackupRecord, backup_id)
                record.state, record.finished_at = "error", now()
                record.error = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Backup failed. Check available storage and permissions, then retry."
                )
            logger.warning("Backup %s failed (%s).", backup_id, type(exc).__name__)
        return True
