"""Series identity and edition details.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("edition", sa.Column("narrator", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "edition", sa.Column("abridgement", sa.String(), nullable=False, server_default="unknown")
    )
    op.create_table(
        "series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("run", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "series_membership",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("series_id", sa.String(36), sa.ForeignKey("series.id"), nullable=False),
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("position", sa.Float(), nullable=False),
        sa.UniqueConstraint("series_id", "work_id"),
    )
    op.create_index("ix_series_membership_series_id", "series_membership", ["series_id"])
    op.create_index("ix_series_membership_work_id", "series_membership", ["work_id"])


def downgrade():
    op.drop_table("series_membership")
    op.drop_table("series")
    op.drop_column("edition", "abridgement")
    op.drop_column("edition", "narrator")
