"""Root-relative original locations and source observations."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "asset", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch:
        batch.drop_constraint("uq_asset_relative_path", type_="unique")
        batch.create_unique_constraint("uq_asset_root_relative_path", ["root", "relative_path"])
        batch.add_column(sa.Column("observed_mtime_ns", sa.BigInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table("asset") as batch:
        batch.drop_column("observed_mtime_ns")
        batch.drop_constraint("uq_asset_root_relative_path", type_="unique")
        batch.create_unique_constraint("uq_asset_relative_path", ["relative_path"])
