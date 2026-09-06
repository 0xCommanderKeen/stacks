"""Chosen cover originals are immutable owned data, separate from media and thumbnails."""

import hashlib
import os
import tempfile
from pathlib import Path

from stacks.inspection import inspect_file
from stacks.library import sync_dir, work_out, write_durable
from stacks.models import CoverBlob, Work, WorkRedirect, identity


class Covers:
    def __init__(self, library):
        self.library = library

    def _editable(self, session, work_id, revision):
        work = session.get(Work, work_id)
        if work is None:
            raise KeyError(work_id)
        if session.get(WorkRedirect, work_id):
            raise ValueError("This work was regrouped. Open its current page before saving.")
        if work.trashed_at:
            raise ValueError("Restore this work before choosing its cover.")
        if work.revision != revision:
            raise ValueError("This work changed. Reload before choosing its cover.")
        return work

    def choose(self, work_id, revision, path):
        lib = self.library
        with lib.ingest_lock:
            inspection = inspect_file(path, "__custom_cover__")
            content = path.read_bytes()
            cover_id = identity()
            # File preparation stays outside the catalog lock. An interrupted preparation
            # leaves only an unselected upload directory, never a partial selected cover.
            with tempfile.TemporaryDirectory(prefix="cover-", dir=lib.uploads) as scratch:
                stage = Path(scratch) / cover_id
                stage.mkdir()
                write_durable(stage / "original", content)
                write_durable(stage / "thumbnail.jpg", inspection.cover)
                sync_dir(stage)
                with lib.lock, lib.sessions.begin() as session:
                    work = self._editable(session, work_id, revision)
                    root = lib.managed / ".covers"
                    if root.is_symlink():
                        raise ValueError("Cover storage must not be a symlink.")
                    root.mkdir(exist_ok=True)
                    destination = root / cover_id
                    if destination.exists():
                        raise ValueError("Cover storage collision; choose the cover again.")
                    os.rename(stage, destination)
                    sync_dir(root)
                    sync_dir(lib.managed)
                    session.add(
                        CoverBlob(
                            id=cover_id,
                            sha256=hashlib.sha256(content).hexdigest(),
                            media_type=inspection.facts["media_type"],
                            size=len(content),
                            origin="manual",
                        )
                    )
                    session.flush()
                    work.selected_cover_id = cover_id
                    work.revision += 1
                    session.flush()
                    return work_out(work)

    def reset(self, work_id, revision):
        with self.library.lock, self.library.sessions.begin() as session:
            work = self._editable(session, work_id, revision)
            work.selected_cover_id = None
            work.revision += 1
            session.flush()
            return work_out(work)

    def original(self, work_id):
        with self.library.sessions() as session:
            work = session.get(Work, work_id)
            if work is None or not work.selected_cover_id or session.get(WorkRedirect, work_id):
                raise KeyError(work_id)
            blob = session.get(CoverBlob, work.selected_cover_id)
            extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
                blob.media_type
            ]
            return (
                self.library.resolve(f".covers/{blob.id}/original"),
                f"cover.{extension}",
                blob.media_type,
            )

    def thumbnail(self, work_id):
        with self.library.sessions() as session:
            work = session.get(Work, work_id)
            if work is None or session.get(WorkRedirect, work_id):
                raise KeyError(work_id)
            if work.selected_cover_id:
                return self.library.resolve(f".covers/{work.selected_cover_id}/thumbnail.jpg")
            for edition in work.editions:
                for representation in edition.representations:
                    if representation.cover_path:
                        return self.library.resolve(representation.cover_path)
            raise KeyError(work_id)
