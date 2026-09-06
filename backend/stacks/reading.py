"""Representation-specific listening state, independent of catalog regrouping."""

import json
import math

from sqlalchemy import func, select

from stacks.library import work_out
from stacks.models import Asset, Edition, Progress, Representation, Work, now
from stacks.schemas import (
    AudioTrackOut,
    ContinueOut,
    ContinuePage,
    PlaybackOut,
    ProgressEdit,
    ProgressOut,
)

AUDIO_FORMATS = {"mp3", "m4a", "m4b", "audio-set"}


def progress_out(progress):
    return ProgressOut(**{name: getattr(progress, name) for name in ProgressOut.model_fields})


def _tracks(representation):
    metadata = json.loads(representation.extracted_json)
    entries = metadata.get("assets", [])
    tracks = []
    for index, asset in enumerate(representation.assets):
        facts = entries[index].get("facts", {}) if index < len(entries) else metadata
        duration = float(facts.get("duration_seconds", 0))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(
                "This audio file has no usable duration. Download the original instead."
            )
        chapters = []
        for chapter in facts.get("chapters", [])[:10000]:
            start = float(chapter["start"])
            if math.isfinite(start) and 0 <= start < duration:
                chapters.append(dict(title=str(chapter.get("title", "Chapter"))[:512], start=start))
        chapters.sort(key=lambda c: c["start"])
        tracks.append(
            AudioTrackOut(
                asset_id=asset.id,
                title=facts.get("track_title") or asset.original_name,
                original_name=asset.original_name,
                duration=duration,
                chapters=chapters,
            )
        )
    if not tracks:
        raise ValueError("This audiobook has no available tracks.")
    return tracks


class Reading:
    def __init__(self, library):
        self.library = library

    @staticmethod
    def _representation(session, representation_id):
        representation = session.get(Representation, representation_id)
        if representation is None:
            raise KeyError(representation_id)
        if representation.format not in AUDIO_FORMATS:
            raise ValueError("Choose an audio representation.")
        return representation

    def playback(self, representation_id):
        with self.library.sessions() as session:
            representation = self._representation(session, representation_id)
            edition = session.get(Edition, representation.edition_id)
            work = session.get(Work, edition.work_id)
            if work.trashed_at:
                raise ValueError("Restore this audiobook from Trash before listening.")
            tracks = _tracks(representation)
            progress = session.get(Progress, representation_id)
            return PlaybackOut(
                representation_id=representation_id,
                work_id=work.id,
                title=work.title,
                tracks=tracks,
                progress=progress_out(progress)
                if progress
                else ProgressOut(
                    representation_id=representation_id,
                    asset_id=tracks[0].asset_id,
                    position=0,
                    speed=1,
                    completed=False,
                    revision=0,
                    updated_at=None,
                ),
            )

    def update(self, representation_id, edit: ProgressEdit):
        with self.library.lock, self.library.sessions.begin() as session:
            representation = self._representation(session, representation_id)
            tracks = _tracks(representation)
            track = next((t for t in tracks if t.asset_id == edit.asset_id), None)
            if track is None:
                raise ValueError("The saved track must belong to this audiobook format.")
            if edit.position > track.duration + 1:
                raise ValueError("The saved position is beyond this track.")
            if edit.completed and (track != tracks[-1] or edit.position < track.duration - 0.25):
                raise ValueError("Only the end of the last track can complete an audiobook.")
            progress = session.get(Progress, representation_id)
            revision = progress.revision if progress else 0
            if revision != edit.revision:
                raise ValueError(
                    "Listening position changed on another device. Reload saved position."
                )
            if progress is None:
                progress = Progress(representation_id=representation_id)
                session.add(progress)
            progress.asset_id = edit.asset_id
            progress.position = min(edit.position, track.duration)
            progress.speed, progress.completed = edit.speed, edit.completed
            progress.revision, progress.updated_at = revision + 1, now()
            session.flush()
            return progress_out(progress)

    def continue_list(self, limit=24, offset=0):
        with self.library.sessions() as session:
            query = (
                select(Progress)
                .join(Representation)
                .join(Edition)
                .join(Work)
                .where(Progress.completed.is_(False), Work.trashed_at.is_(None))
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(
                query.order_by(Progress.updated_at.desc(), Progress.representation_id)
                .limit(limit)
                .offset(offset)
            )
            items = []
            for progress in rows:
                representation = session.get(Representation, progress.representation_id)
                edition = session.get(Edition, representation.edition_id)
                work = session.get(Work, edition.work_id)
                items.append(
                    ContinueOut(
                        work=work_out(work),
                        representation_id=representation.id,
                        progress=progress_out(progress),
                    )
                )
            return ContinuePage(items=items, total=total, limit=limit, offset=offset)

    def stream(self, asset_id):
        with self.library.sessions() as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                raise KeyError(asset_id)
            representation = self._representation(session, asset.representation_id)
            edition = session.get(Edition, representation.edition_id)
            if session.get(Work, edition.work_id).trashed_at:
                raise ValueError("Restore this audiobook from Trash before listening.")
            return self.library.resolve_asset(asset), asset.original_name
