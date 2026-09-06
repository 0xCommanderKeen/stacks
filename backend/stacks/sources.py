"""Read-only source visibility; original locations stay behind the library boundary."""

from sqlalchemy import func, select

from stacks.models import Asset, Edition, InboxCandidate, IntakeJob, Representation
from stacks.schemas import AssetAvailability, SourceOut


class Sources:
    def __init__(self, library):
        self.library = library

    def list(self):
        with self.library.sessions() as session:
            counts = dict(
                session.execute(
                    select(Asset.root, func.count())
                    .where(Asset.root != "managed")
                    .group_by(Asset.root)
                ).all()
            )
            discovered = set(session.scalars(select(InboxCandidate.root).distinct()))
            discovered.update(session.scalars(select(IntakeJob.root).distinct()))
        return [
            SourceOut(
                alias=alias,
                configured=alias in self.library.sources,
                available=alias in self.library.sources and self.library.sources[alias].is_dir(),
                registered_assets=counts.get(alias, 0),
            )
            for alias in sorted(set(counts) | self.library.sources.keys() | discovered)
        ]

    def availability(self, work_id):
        work = self.library.get(work_id)
        with self.library.sessions() as session:
            assets = session.scalars(
                select(Asset).join(Representation).join(Edition).where(Edition.work_id == work.id)
            )
            results = []
            for asset in assets:
                try:
                    self.library.resolve_asset(asset)
                    results.append(
                        AssetAvailability(
                            asset_id=asset.id,
                            available=True,
                            detail="Managed original"
                            if asset.root == "managed"
                            else f"Registered in {asset.root}",
                        )
                    )
                except OSError as error:
                    results.append(
                        AssetAvailability(
                            asset_id=asset.id,
                            available=False,
                            detail=str(error)
                            if isinstance(error, FileNotFoundError) and error.errno is None
                            else "The original is inaccessible. Check source permissions.",
                        )
                    )
            return results
