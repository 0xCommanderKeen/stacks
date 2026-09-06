"""Representation-specific audio resume."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "progress",
        sa.Column(
            "representation_id", sa.String(36), sa.ForeignKey("representation.id"), primary_key=True
        ),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_progress_updated_at", "progress", ["updated_at"])


def downgrade():
    op.drop_table("progress")
