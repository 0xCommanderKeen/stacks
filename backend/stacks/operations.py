"""Previewed catalog regrouping. File and representation identities never change."""

import json

from sqlalchemy import delete, func, insert, or_, select, update

from stacks.collections import append_work, touch
from stacks.library import work_out
from stacks.models import (
    CatalogOperation,
    Collection,
    CollectionEntry,
    Contributor,
    Credit,
    Edition,
    PersonalState,
    ReadingRecord,
    Representation,
    SeriesMembership,
    Work,
    WorkRedirect,
    identity,
)
from stacks.schemas import ConflictOut, GroupPreview, GroupRequest, OperationOut, OperationPage


def _rows(session, model, condition):
    table = model.__table__
    return [
        dict(row)
        for row in session.execute(
            select(table).where(condition).order_by(*table.primary_key.columns)
        ).mappings()
    ]


def _snapshot(session, work_ids):
    editions = select(Edition.id).where(Edition.work_id.in_(work_ids))
    contributors = select(Credit.contributor_id).where(Credit.work_id.in_(work_ids))
    collections = select(CollectionEntry.collection_id).where(CollectionEntry.work_id.in_(work_ids))
    return {
        "collection": _rows(session, Collection, Collection.id.in_(collections)),
        "collection_entry": _rows(session, CollectionEntry, CollectionEntry.work_id.in_(work_ids)),
        "work": _rows(session, Work, Work.id.in_(work_ids)),
        "contributor": _rows(session, Contributor, Contributor.id.in_(contributors)),
        "credit": _rows(session, Credit, Credit.work_id.in_(work_ids)),
        "edition": _rows(session, Edition, Edition.work_id.in_(work_ids)),
        "representation": _rows(session, Representation, Representation.edition_id.in_(editions)),
        "series_membership": _rows(
            session, SeriesMembership, SeriesMembership.work_id.in_(work_ids)
        ),
        "personal_state": _rows(session, PersonalState, PersonalState.work_id.in_(work_ids)),
        "reading_record": _rows(session, ReadingRecord, ReadingRecord.work_id.in_(work_ids)),
        "work_redirect": _rows(session, WorkRedirect, WorkRedirect.source_id.in_(work_ids)),
    }


def _personal_values(work):
    values = work.personal.model_dump(include={"notes", "rating", "tags"})
    values["shelf"] = [work.personal.default_shelf, work.personal.shelf_override]
    return values


def _personal_label(field, value):
    if field == "shelf":
        default, override = value
        return f"{override or default} ({'your choice' if override else 'default'})"
    if field == "rating":
        return f"{value} / 5" if value else "Unrated"
    if field == "tags":
        return ", ".join(value) or "No tags"
    return value or "No notes"


def _saved_snapshot(raw):
    snapshot = json.loads(raw)
    # Earlier operations predate personal state. Empty new tables preserve their meaning.
    snapshot.setdefault("personal_state", [])
    snapshot.setdefault("reading_record", [])
    snapshot.setdefault("collection", [])
    snapshot.setdefault("collection_entry", [])
    return snapshot


def _conflicts(source, target):
    if target is None:
        return []
    conflicts = []
    for name in ("title", "authors", "description"):
        left, right = getattr(source, name), getattr(target, name)
        if left != right and left:
            conflicts.append(
                ConflictOut(
                    field=name,
                    source=json.dumps(left, ensure_ascii=False),
                    target=json.dumps(right, ensure_ascii=False),
                )
            )
    left_values, right_values = _personal_values(source), _personal_values(target)
    for field, left in left_values.items():
        right = right_values[field]
        if left != right and left not in (None, "", []):
            conflicts.append(
                ConflictOut(
                    field=f"personal:{field}",
                    source=_personal_label(field, left),
                    target=_personal_label(field, right),
                )
            )
    existing = {m.series_id: m for m in target.memberships}
    for member in source.memberships:
        old = existing.get(member.series_id)
        if old and (old.designation, old.position) != (member.designation, member.position):
            conflicts.append(
                ConflictOut(
                    field=f"series:{member.series_id}",
                    source=f"{member.designation} (order {member.position})",
                    target=f"{old.designation} (order {old.position})",
                )
            )
    return conflicts


class CatalogOperations:
    def __init__(self, library):
        self.library = library

    def preview(self, request: GroupRequest) -> GroupPreview:
        with self.library.lock, self.library.sessions.begin() as session:
            source = self._active(session, request.source_work_id)
            target = (
                self._active(session, request.target_work_id) if request.target_work_id else None
            )
            if target and target.id == source.id:
                raise ValueError("Choose two different works.")
            if request.mode != "split" and target is None:
                raise ValueError("Choose the work to group with.")
            if request.mode == "split" and target is not None:
                raise ValueError("Splitting creates a new work.")
            if request.mode in {"representation", "split"}:
                representation = session.get(Representation, request.representation_id)
                if representation is None:
                    raise ValueError("Choose an available format.")
                edition = session.get(Edition, representation.edition_id)
                if edition.work_id != source.id:
                    raise ValueError("The format does not belong to the source work.")
                if request.mode == "split":
                    if sum(len(e.representations) for e in source.editions) < 2:
                        raise ValueError(
                            "This work has only one format. There is nothing to split."
                        )
                else:
                    destination = session.get(Edition, request.target_edition_id)
                    if destination is None or destination.work_id != target.id:
                        raise ValueError("Choose an edition belonging to the target work.")
                    for field in (
                        "medium",
                        "language",
                        "narrator",
                        "abridgement",
                        "publisher",
                        "identifier",
                    ):
                        left, right = getattr(edition, field), getattr(destination, field)
                        if (
                            left not in {"", "unknown"}
                            and right not in {"", "unknown"}
                            and left != right
                        ):
                            raise ValueError(
                                f"Edition {field} differs. Keep separate editions instead."
                            )
            source_out = work_out(source)
            target_out = work_out(target) if target else None
            data = request.model_dump()
            if request.mode == "split":
                data["new_work_id"], data["new_edition_id"] = identity(), identity()
            work_ids = [source.id, target.id if target else data["new_work_id"]]
            data["work_ids"] = work_ids
            conflicts = _conflicts(source_out, target_out)
            full_merge = target is not None and (
                request.mode == "editions"
                or sum(len(e.representations) for e in source.editions) == 1
            )
            if full_merge:
                entries = session.scalars(
                    select(CollectionEntry).where(CollectionEntry.work_id.in_(work_ids))
                ).all()
                targets = {e.collection_id: e for e in entries if e.work_id == target.id}
                for entry in entries:
                    other = targets.get(entry.collection_id)
                    if entry.work_id == source.id and other:
                        collection = session.get(Collection, entry.collection_id)
                        conflicts.append(
                            ConflictOut(
                                field=f"collection:{collection.id}",
                                source=f"{collection.name}: source position {entry.position}",
                                target=f"{collection.name}: target position {other.position}",
                            )
                        )
            data["conflicts"] = [c.model_dump() for c in conflicts]
            operation = CatalogOperation(
                request_json=json.dumps(data), before_json=json.dumps(_snapshot(session, work_ids))
            )
            session.add(operation)
            session.flush()
            return GroupPreview(
                id=operation.id,
                mode=request.mode,
                source=source_out,
                target=target_out,
                conflicts=conflicts,
                explanation=(
                    "Separate this format into a new work with copied details and series."
                    if request.mode == "split"
                    else "Keep files and format IDs. Resolve differences before grouping."
                ),
            )

    @staticmethod
    def _active(session, work_id):
        work = session.get(Work, work_id)
        if work is None:
            raise KeyError(work_id)
        if session.get(WorkRedirect, work_id):
            raise ValueError("This work was regrouped. Open its current page before continuing.")
        return work

    def commit(self, operation_id, resolutions):
        with self.library.lock, self.library.sessions.begin() as session:
            operation = session.get(CatalogOperation, operation_id)
            if operation is None:
                raise KeyError(operation_id)
            data = json.loads(operation.request_json)
            if operation.state == "applied":
                return self._out(operation)
            if operation.state != "preview":
                raise ValueError("This operation is no longer a pending preview.")
            if _snapshot(session, data["work_ids"]) != _saved_snapshot(operation.before_json):
                raise ValueError("The catalog changed after this preview. Preview again.")
            required = {c["field"] for c in data["conflicts"]}
            if set(resolutions) != required:
                raise ValueError("Choose a resolution for every displayed difference.")
            if data["mode"] == "split":
                self._split(session, data)
            else:
                self._group(session, data, resolutions)
            session.execute(
                update(Work).where(Work.id.in_(data["work_ids"])).values(revision=Work.revision + 1)
            )
            session.flush()
            session.expire_all()
            operation = session.get(CatalogOperation, operation_id)
            operation.after_json = json.dumps(_snapshot(session, data["work_ids"]))
            operation.state = "applied"
            return self._out(operation)

    def _group(self, session, data, resolutions):
        source = session.get(Work, data["source_work_id"])
        target = session.get(Work, data["target_work_id"])
        for name in ("title", "description"):
            if resolutions.get(name) == "source":
                setattr(target, name, getattr(source, name))
        if resolutions.get("authors") == "source":
            target.credits = [
                Credit(
                    position=c.position,
                    role=c.role,
                    contributor=Contributor(name=c.contributor.name),
                )
                for c in source.credits
            ]
        existing = {m.series_id: m for m in target.memberships}
        for member in source.memberships:
            if member.series_id not in existing:
                target.memberships.append(
                    SeriesMembership(
                        series_id=member.series_id,
                        designation=member.designation,
                        position=member.position,
                    )
                )
            elif resolutions.get(f"series:{member.series_id}") == "source":
                existing[member.series_id].designation = member.designation
                existing[member.series_id].position = member.position
        session.flush()
        if data["mode"] == "editions":
            session.execute(
                update(Edition).where(Edition.work_id == source.id).values(work_id=target.id)
            )
        else:
            representation = session.get(Representation, data["representation_id"])
            origin = session.get(Edition, representation.edition_id)
            destination = session.get(Edition, data["target_edition_id"])
            for field in ("language", "publisher", "identifier", "narrator", "abridgement"):
                if getattr(destination, field) in {"", "unknown"}:
                    setattr(destination, field, getattr(origin, field))
            session.flush()
            session.execute(
                update(Representation)
                .where(Representation.id == data["representation_id"])
                .values(edition_id=data["target_edition_id"])
            )
        chosen = {
            key.removeprefix("personal:")
            for key, side in resolutions.items()
            if key.startswith("personal:") and side == "source"
        }
        if chosen:
            values = _personal_values(work_out(source))
            if target.personal is None:
                target.personal = PersonalState()
            for field in chosen:
                if field == "shelf":
                    target.personal.default_shelf, target.personal.shelf_override = values[field]
                elif field == "tags":
                    target.personal.tags_json = json.dumps(values[field], ensure_ascii=False)
                else:
                    setattr(target.personal, field, values[field])
            session.flush()
        # A chosen shelf conflict is an explicit decision. Otherwise a newly combined
        # followed membership promotes the default while retaining any override.
        if (
            target.personal is not None
            and "personal:shelf" not in resolutions
            and any(member.series.following for member in target.memberships)
        ):
            target.personal.default_shelf = "library"
            session.flush()
        remains = session.scalar(
            select(Representation.id).join(Edition).where(Edition.work_id == source.id).limit(1)
        )
        records = update(ReadingRecord).where(ReadingRecord.work_id == source.id)
        if remains:
            records = records.where(ReadingRecord.representation_id == data["representation_id"])
        session.execute(records.values(work_id=target.id, revision=ReadingRecord.revision + 1))
        self._collections(session, source.id, target.id, bool(remains), resolutions)
        if not remains:
            session.add(WorkRedirect(source_id=source.id, target_id=target.id))

    @staticmethod
    def _collections(session, source_id, target_id, copy, resolutions):
        for entry in session.scalars(
            select(CollectionEntry).where(CollectionEntry.work_id == source_id)
        ).all():
            other = session.scalar(
                select(CollectionEntry).where(
                    CollectionEntry.collection_id == entry.collection_id,
                    CollectionEntry.work_id == target_id,
                )
            )
            if copy:
                if other:
                    continue
                append_work(session, entry.collection_id, target_id)
            else:
                if other:
                    if resolutions[f"collection:{entry.collection_id}"] == "target":
                        session.delete(entry)
                    else:
                        session.delete(other)
                        session.flush()
                        entry.work_id = target_id
                else:
                    entry.work_id = target_id
            touch(session.get(Collection, entry.collection_id))
            session.flush()

    @staticmethod
    def _split(session, data):
        source = session.get(Work, data["source_work_id"])
        representation = session.get(Representation, data["representation_id"])
        edition = session.get(Edition, representation.edition_id)
        new = Work(
            id=data["new_work_id"],
            title=source.title,
            description=source.description,
            credits=[
                Credit(
                    position=c.position,
                    role=c.role,
                    contributor=Contributor(name=c.contributor.name),
                )
                for c in source.credits
            ],
            memberships=[
                SeriesMembership(
                    series_id=m.series_id, designation=m.designation, position=m.position
                )
                for m in source.memberships
            ],
        )
        if source.personal is not None:
            new.personal = PersonalState(
                **{
                    column.name: getattr(source.personal, column.name)
                    for column in PersonalState.__table__.columns
                    if column.name != "work_id"
                }
            )
        session.add(new)
        session.flush()
        session.add(
            Edition(
                id=data["new_edition_id"],
                work_id=new.id,
                **{
                    name: getattr(edition, name)
                    for name in (
                        "medium",
                        "language",
                        "publisher",
                        "identifier",
                        "narrator",
                        "abridgement",
                    )
                },
            )
        )
        session.flush()
        session.execute(
            update(Representation)
            .where(Representation.id == representation.id)
            .values(edition_id=data["new_edition_id"])
        )

        session.execute(
            update(ReadingRecord)
            .where(
                ReadingRecord.work_id == source.id,
                ReadingRecord.representation_id == representation.id,
            )
            .values(work_id=new.id, revision=ReadingRecord.revision + 1)
        )

        CatalogOperations._collections(session, source.id, new.id, True, {})

    def undo(self, operation_id):
        with self.library.lock, self.library.sessions.begin() as session:
            operation = session.get(CatalogOperation, operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.state == "undone":
                return self._out(operation)
            if operation.state != "applied":
                raise ValueError("Only an applied operation can be undone.")
            data = json.loads(operation.request_json)
            before, after = (
                _saved_snapshot(operation.before_json),
                _saved_snapshot(operation.after_json),
            )
            current = _snapshot(session, data["work_ids"])
            comparable = json.loads(json.dumps(current))
            expected = json.loads(json.dumps(after))
            for snapshot in (comparable, expected):
                for work in snapshot["work"]:
                    work.pop("revision")
                for record in snapshot["reading_record"]:
                    record.pop("revision")
                for collection in snapshot["collection"]:
                    collection.pop("revision")
            if comparable != expected:
                raise ValueError(
                    "These works changed since grouping. Undo would overwrite newer edits."
                )
            self._restore(session, data["work_ids"], before, after, current)
            operation.state = "undone"
            return self._out(operation)

    @staticmethod
    def _restore(session, work_ids, before, after, current):
        # Restore catalog ownership only. No asset/file operations occur here.
        for model in (Work, Contributor, Edition, Representation):
            table = model.__table__
            for row in before[table.name]:
                if session.scalar(select(table.c.id).where(table.c.id == row["id"])):
                    session.execute(update(table).where(table.c.id == row["id"]).values(**row))
                else:
                    session.execute(insert(table).values(**row))
        for model, column in (
            (Credit, Credit.work_id),
            (SeriesMembership, SeriesMembership.work_id),
            (WorkRedirect, WorkRedirect.source_id),
            (PersonalState, PersonalState.work_id),
            (ReadingRecord, ReadingRecord.work_id),
            (CollectionEntry, CollectionEntry.work_id),
        ):
            session.execute(delete(model).where(column.in_(work_ids)))
            for row in before[model.__tablename__]:
                session.execute(insert(model).values(**row))
        revisions = {c["id"]: c["revision"] for c in current["collection"]}
        for row in before["collection"]:
            session.execute(
                update(Collection)
                .where(Collection.id == row["id"])
                .values(**{**row, "revision": revisions[row["id"]] + 1})
            )
        for model in (Edition, Work):
            old_ids = {r["id"] for r in before[model.__tablename__]}
            new_ids = {r["id"] for r in after[model.__tablename__]} - old_ids
            if new_ids:
                session.execute(delete(model).where(model.id.in_(new_ids)))
        for record in current["reading_record"]:
            session.execute(
                update(ReadingRecord)
                .where(ReadingRecord.id == record["id"])
                .values(revision=record["revision"] + 1)
            )
        # Never reuse a revision observed before grouping or undo.
        for work in current["work"]:
            session.execute(
                update(Work).where(Work.id == work["id"]).values(revision=work["revision"] + 1)
            )

    def list(self, limit=60, offset=0, work_id=None):
        with self.library.sessions() as session:
            query = select(CatalogOperation).where(CatalogOperation.state != "preview")
            if work_id:
                query = query.where(
                    or_(
                        func.json_extract(CatalogOperation.request_json, "$.work_ids[0]")
                        == work_id,
                        func.json_extract(CatalogOperation.request_json, "$.work_ids[1]")
                        == work_id,
                    )
                )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return OperationPage(
                items=[
                    self._out(o)
                    for o in session.scalars(
                        query.order_by(CatalogOperation.created_at.desc(), CatalogOperation.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=total,
                limit=limit,
                offset=offset,
            )

    @staticmethod
    def _out(operation):
        return OperationOut(
            id=operation.id,
            state=operation.state,
            work_ids=json.loads(operation.request_json)["work_ids"],
            created_at=operation.created_at,
        )
