"""Personal choices and reading history, with revision-checked writes."""

import json

from sqlalchemy import func, select

from stacks.library import work_out
from stacks.models import Edition, PersonalState, ReadingRecord, Representation, Work, WorkRedirect
from stacks.schemas import PersonalEdit, RecordEdit, RecordOut, RecordPage


def record_out(record):
    return RecordOut(**{name: getattr(record, name) for name in RecordOut.model_fields})


class Curation:
    def __init__(self, library):
        self.library = library

    @staticmethod
    def active(session, work_id):
        work = session.get(Work, work_id)
        if work is None:
            raise KeyError(work_id)
        if session.get(WorkRedirect, work_id):
            raise ValueError("This work was regrouped. Open its current page before continuing.")
        return work

    def edit(self, work_id, edit: PersonalEdit):
        with self.library.lock, self.library.sessions.begin() as session:
            work = self.active(session, work_id)
            if work.revision != edit.revision:
                raise ValueError("This book changed in another tab. Reload before saving.")
            if work.personal is None:
                work.personal = PersonalState()
            work.personal.shelf_override = edit.shelf_override
            work.personal.notes, work.personal.rating = edit.notes, edit.rating
            work.personal.tags_json = json.dumps(edit.tags, ensure_ascii=False)
            work.revision += 1
            session.flush()
            return work_out(work)

    def records(self, work_id, limit=24, offset=0):
        with self.library.sessions() as session:
            self.active(session, work_id)
            query = select(ReadingRecord).where(ReadingRecord.work_id == work_id)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return RecordPage(
                items=[
                    record_out(r)
                    for r in session.scalars(
                        query.order_by(
                            ReadingRecord.started.desc(),
                            ReadingRecord.created_at.desc(),
                            ReadingRecord.id,
                        )
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=total,
                limit=limit,
                offset=offset,
            )

    def save_record(self, work_id, edit: RecordEdit, record_id=None):
        with self.library.lock, self.library.sessions.begin() as session:
            work = self.active(session, work_id)
            record = (
                session.get(ReadingRecord, record_id)
                if record_id
                else ReadingRecord(work_id=work_id)
            )
            if record is None or record.work_id != work_id:
                raise KeyError(record_id)
            if record_id and record.revision != edit.revision:
                raise ValueError("This reading record changed. Reload before saving.")
            if edit.representation_id:
                rep = session.get(Representation, edit.representation_id)
                edition = session.get(Edition, rep.edition_id) if rep else None
                if edition is None or edition.work_id != work_id:
                    raise ValueError("Choose a format belonging to this work.")
                if (edition.medium == "audio") != (edit.kind == "listen"):
                    raise ValueError(
                        "Choose an audio format for listening or a reading format for reading."
                    )
            record.representation_id, record.kind = edit.representation_id, edit.kind
            record.started = edit.started.isoformat()
            record.finished = edit.finished.isoformat() if edit.finished else None
            record.revision = record.revision + 1 if record_id else 1
            work.revision += 1
            session.add(record)
            session.flush()
            return record_out(record)

    def delete_record(self, work_id, record_id, revision):
        with self.library.lock, self.library.sessions.begin() as session:
            work = self.active(session, work_id)
            record = session.get(ReadingRecord, record_id)
            if record is None or record.work_id != work_id:
                raise KeyError(record_id)
            if record.revision != revision:
                raise ValueError("This reading record changed. Reload before removing it.")
            session.delete(record)
            work.revision += 1
