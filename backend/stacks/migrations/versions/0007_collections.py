"""Ordered personal collections."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collection",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("home", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state_id", sa.String(36), nullable=False),
    )
    op.create_table(
        "collection_entry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("collection.id"), nullable=False),
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("collection_id", "work_id"),
        sa.UniqueConstraint("collection_id", "position"),
    )
    op.create_index("ix_collection_entry_collection_id", "collection_entry", ["collection_id"])
    op.create_index("ix_collection_entry_work_id", "collection_entry", ["work_id"])


def downgrade():
    op.drop_table("collection_entry")
    op.drop_table("collection")
