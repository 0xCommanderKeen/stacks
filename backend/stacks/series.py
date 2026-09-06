"""Followed publication sequences and SQL-paginated reading choices."""

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.orm import selectinload

from stacks.library import series_out, work_out
from stacks.models import (
    Credit,
    Edition,
    PersonalState,
    ReadingRecord,
    Representation,
    Series,
    SeriesMembership,
    Work,
    WorkRedirect,
)
from stacks.schemas import FollowEdit, NextOut, NextPage, RunOut, RunPage, RunWorksPage


def _members(scope="all", medium=None):
    finished = (
        select(ReadingRecord.id)
        .where(ReadingRecord.work_id == Work.id, ReadingRecord.finished.is_not(None))
        .exists()
    )
    query = (
        select(
            SeriesMembership.id.label("membership_id"),
            SeriesMembership.series_id,
            Work.id.label("work_id"),
            SeriesMembership.designation,
            SeriesMembership.position,
            finished.label("finished"),
        )
        .join(Work, Work.id == SeriesMembership.work_id)
        .where(~select(WorkRedirect.source_id).where(WorkRedirect.source_id == Work.id).exists())
    )
    if scope != "all":
        query = query.outerjoin(PersonalState).where(
            func.coalesce(PersonalState.shelf_override, PersonalState.default_shelf, "library")
            == scope
        )
    if medium:
        query = query.where(
            Work.editions.any((Edition.medium == medium) & Edition.representations.any())
        )
    return query


class SeriesCatalog:
    def __init__(self, library):
        self.library = library

    def get(self, series_id):
        with self.library.sessions() as session:
            series = session.get(Series, series_id)
            if series is None:
                raise KeyError(series_id)
            return series_out(series)

    def follow(self, series_id, edit: FollowEdit):
        with self.library.lock, self.library.sessions.begin() as session:
            series = session.get(Series, series_id)
            if series is None:
                raise KeyError(series_id)
            if series.revision != edit.revision:
                raise ValueError("This series changed. Reload before changing following.")
            series.following = edit.following
            series.revision += 1
            if edit.following:
                members = select(SeriesMembership.work_id).where(
                    SeriesMembership.series_id == series_id,
                    ~select(WorkRedirect.source_id)
                    .where(WorkRedirect.source_id == SeriesMembership.work_id)
                    .exists(),
                )
                eligible = select(PersonalState.work_id).where(
                    PersonalState.work_id.in_(members), PersonalState.default_shelf == "archive"
                )
                session.execute(
                    update(Work).where(Work.id.in_(eligible)).values(revision=Work.revision + 1)
                )
                session.execute(
                    update(PersonalState)
                    .where(
                        PersonalState.work_id.in_(members), PersonalState.default_shelf == "archive"
                    )
                    .values(default_shelf="library")
                )
            session.flush()
            return series_out(series)

    def browse(self, q="", scope="all", medium=None, following=False, limit=24, offset=0):
        with self.library.sessions() as session:
            members = _members(scope, medium).subquery()
            counts = (
                select(
                    members.c.series_id,
                    func.count().label("owned"),
                    func.sum(cast(members.c.finished, Integer)).label("finished"),
                )
                .group_by(members.c.series_id)
                .subquery()
            )
            query = select(Series, counts.c.owned, counts.c.finished).join(
                counts, counts.c.series_id == Series.id
            )
            if q.strip():
                query = query.where(
                    Series.name.contains(q.strip(), autoescape=True)
                    | Series.run.contains(q.strip(), autoescape=True)
                )
            if following:
                query = query.where(Series.following.is_(True))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return RunPage(
                items=[
                    RunOut(series=series_out(series), owned=owned, finished=finished)
                    for series, owned, finished in session.execute(
                        query.order_by(Series.name, Series.run, Series.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=total,
                limit=limit,
                offset=offset,
            )

    def works(self, series_id, limit=24, offset=0, scope="all", medium=None):
        page = self.library.list(
            limit=limit, offset=offset, series_id=series_id, scope=scope, medium=medium
        )
        with self.library.sessions() as session:
            finished = session.scalars(
                select(ReadingRecord.work_id)
                .where(
                    ReadingRecord.work_id.in_([work.id for work in page.items]),
                    ReadingRecord.finished.is_not(None),
                )
                .distinct()
            ).all()
            return RunWorksPage(**page.model_dump(), finished_work_ids=list(finished))

    def next(self, limit=12, offset=0):
        with self.library.sessions() as session:
            members = (
                _members("library")
                .where(
                    SeriesMembership.series_id.in_(
                        select(Series.id).where(Series.following.is_(True))
                    )
                )
                .subquery()
            )
            ranked = (
                select(
                    members.c.work_id,
                    members.c.series_id,
                    members.c.designation,
                    func.row_number()
                    .over(
                        partition_by=members.c.series_id,
                        order_by=(members.c.position, members.c.work_id),
                    )
                    .label("rank"),
                )
                .where(members.c.finished.is_(False))
                .subquery()
            )
            query = (
                select(Series, Work, ranked.c.designation)
                .join(ranked, ranked.c.series_id == Series.id)
                .join(Work, Work.id == ranked.c.work_id)
                .where(ranked.c.rank == 1)
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            query = query.options(
                selectinload(Work.personal),
                selectinload(Work.memberships).selectinload(SeriesMembership.series),
                selectinload(Work.credits).selectinload(Credit.contributor),
                selectinload(Work.editions)
                .selectinload(Edition.representations)
                .selectinload(Representation.assets),
            )
            return NextPage(
                items=[
                    NextOut(series=series_out(series), work=work_out(work), designation=designation)
                    for series, work, designation in session.execute(
                        query.order_by(Series.name, Series.run, Series.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=total,
                limit=limit,
                offset=offset,
            )
