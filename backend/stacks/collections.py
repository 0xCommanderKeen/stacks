"""Ordered curation, with SQL pagination and transactional revision guards."""

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from stacks.library import work_out
from stacks.models import (
    Collection,
    CollectionEntry,
    Credit,
    Edition,
    PersonalState,
    ReadingRecord,
    Representation,
    Series,
    SeriesMembership,
    Work,
    WorkRedirect,
    identity,
)
from stacks.schemas import (
    CollectionChange,
    CollectionEdit,
    CollectionEntryOut,
    CollectionNextOut,
    CollectionNextPage,
    CollectionOut,
    CollectionPage,
    CollectionWorksPage,
)


def touch(collection):
    collection.revision += 1
    collection.state_id = identity()


def append_work(session, collection_id, work_id):
    position = (
        session.scalar(
            select(func.coalesce(func.max(CollectionEntry.position), 0)).where(
                CollectionEntry.collection_id == collection_id
            )
        )
        + 1
    )
    entry = CollectionEntry(collection_id=collection_id, work_id=work_id, position=position)
    session.add(entry)
    session.flush()
    return entry


def collection_out(session, collection):
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        home=collection.home,
        revision=collection.revision,
        count=session.scalar(
            select(func.count())
            .select_from(CollectionEntry)
            .where(CollectionEntry.collection_id == collection.id)
        ),
    )


def _loaded(query):
    return query.options(
        selectinload(Work.personal),
        selectinload(Work.memberships).selectinload(SeriesMembership.series),
        selectinload(Work.credits).selectinload(Credit.contributor),
        selectinload(Work.editions)
        .selectinload(Edition.representations)
        .selectinload(Representation.assets),
    )


def _finished():
    return (
        select(ReadingRecord.id)
        .where(ReadingRecord.work_id == Work.id, ReadingRecord.finished.is_not(None))
        .exists()
    )


class Collections:
    def __init__(self, library):
        self.library = library

    @staticmethod
    def _get(session, collection_id, revision=None):
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise KeyError(collection_id)
        if revision is not None and collection.revision != revision:
            raise ValueError("This collection changed. Reload before editing.")
        return collection

    def list(self, q="", limit=24, offset=0):
        with self.library.sessions() as session:
            query = select(Collection)
            if q.strip():
                query = query.where(Collection.name.contains(q.strip(), autoescape=True))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return CollectionPage(
                items=[
                    collection_out(session, c)
                    for c in session.scalars(
                        query.order_by(Collection.name, Collection.id).limit(limit).offset(offset)
                    )
                ],
                total=total,
                limit=limit,
                offset=offset,
            )

    def save(self, edit: CollectionEdit, collection_id=None):
        with self.library.lock, self.library.sessions.begin() as session:
            if collection_id:
                collection = self._get(session, collection_id, edit.revision)
                touch(collection)
            else:
                collection = Collection()
                session.add(collection)
            collection.name, collection.home = edit.name, edit.home
            session.flush()
            return collection_out(session, collection)

    def change(self, collection_id, edit: CollectionChange):
        with self.library.lock, self.library.sessions.begin() as session:
            collection = self._get(session, collection_id, edit.revision)
            if edit.action == "add_series":
                if not edit.series_id or session.get(Series, edit.series_id) is None:
                    raise ValueError("Choose an available series.")
                query = (
                    select(SeriesMembership.work_id)
                    .where(
                        SeriesMembership.series_id == edit.series_id,
                        ~select(WorkRedirect.source_id)
                        .where(WorkRedirect.source_id == SeriesMembership.work_id)
                        .exists(),
                        ~select(CollectionEntry.id)
                        .where(
                            CollectionEntry.collection_id == collection_id,
                            CollectionEntry.work_id == SeriesMembership.work_id,
                        )
                        .exists(),
                    )
                    .order_by(SeriesMembership.position, SeriesMembership.work_id)
                )
                # Stream the current owned run; later imports remain a deliberate addition.
                for work_id in session.scalars(query):
                    append_work(session, collection_id, work_id)
            else:
                work = session.get(Work, edit.work_id) if edit.work_id else None
                if work is None or session.get(WorkRedirect, work.id):
                    raise ValueError("Choose an available work from its current page.")
                entry = session.scalar(
                    select(CollectionEntry).where(
                        CollectionEntry.collection_id == collection_id,
                        CollectionEntry.work_id == work.id,
                    )
                )
                if edit.action == "add":
                    if entry is None:
                        append_work(session, collection_id, work.id)
                else:
                    if entry is None:
                        raise ValueError("This work is no longer in the collection.")
                    if edit.action == "remove":
                        session.delete(entry)
                    else:
                        previous = edit.action == "up"
                        adjacent = session.scalar(
                            select(CollectionEntry)
                            .where(
                                CollectionEntry.collection_id == collection_id,
                                CollectionEntry.position < entry.position
                                if previous
                                else CollectionEntry.position > entry.position,
                            )
                            .order_by(
                                CollectionEntry.position.desc()
                                if previous
                                else CollectionEntry.position
                            )
                            .limit(1)
                        )
                        if adjacent:
                            old, new = entry.position, adjacent.position
                            entry.position = (
                                session.scalar(
                                    select(func.max(CollectionEntry.position)).where(
                                        CollectionEntry.collection_id == collection_id
                                    )
                                )
                                + 1
                            )
                            session.flush()
                            adjacent.position = old
                            session.flush()
                            entry.position = new
            touch(collection)
            session.flush()
            return collection_out(session, collection)

    def works(self, collection_id, limit=24, offset=0):
        with self.library.sessions() as session:
            collection = collection_out(session, self._get(session, collection_id))
            query = _loaded(
                select(CollectionEntry, Work, _finished())
                .join(Work, Work.id == CollectionEntry.work_id)
                .where(CollectionEntry.collection_id == collection_id)
                .order_by(CollectionEntry.position)
                .limit(limit)
                .offset(offset)
            )
            return CollectionWorksPage(
                collection=collection,
                items=[
                    CollectionEntryOut(id=e.id, position=e.position, work=work_out(w), finished=f)
                    for e, w, f in session.execute(query)
                ],
                total=collection.count,
                limit=limit,
                offset=offset,
            )

    def next(self, limit=12, offset=0):
        with self.library.sessions() as session:
            ranked = (
                select(
                    CollectionEntry.collection_id,
                    Work.id.label("work_id"),
                    func.row_number()
                    .over(
                        partition_by=CollectionEntry.collection_id,
                        order_by=CollectionEntry.position,
                    )
                    .label("rank"),
                )
                .join(Work, Work.id == CollectionEntry.work_id)
                .join(Collection, Collection.id == CollectionEntry.collection_id)
                .outerjoin(PersonalState, PersonalState.work_id == Work.id)
                .where(
                    Collection.home.is_(True),
                    ~_finished(),
                    func.coalesce(
                        PersonalState.shelf_override, PersonalState.default_shelf, "library"
                    )
                    == "library",
                    ~select(WorkRedirect.source_id)
                    .where(WorkRedirect.source_id == Work.id)
                    .exists(),
                )
                .subquery()
            )
            query = (
                select(Collection, Work)
                .join(ranked, ranked.c.collection_id == Collection.id)
                .join(Work, Work.id == ranked.c.work_id)
                .where(ranked.c.rank == 1)
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return CollectionNextPage(
                items=[
                    CollectionNextOut(collection=collection_out(session, c), work=work_out(w))
                    for c, w in session.execute(
                        _loaded(
                            query.order_by(Collection.name, Collection.id)
                            .limit(limit)
                            .offset(offset)
                        )
                    )
                ],
                total=total,
                limit=limit,
                offset=offset,
            )
