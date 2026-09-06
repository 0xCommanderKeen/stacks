"""Recoverable work trash with per-original relocation checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work", sa.Column("trashed_at", sa.Text()))
    op.create_index("ix_work_trashed_at", "work", ["trashed_at"])
    op.create_table(
        "trash_operation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_trash_operation_work_id", "trash_operation", ["work_id"])
    op.create_index("ix_trash_operation_state", "trash_operation", ["state"])
    op.create_table(
        "trash_file",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "operation_id", sa.String(36), sa.ForeignKey("trash_operation.id"), nullable=False
        ),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("operation_id", "asset_id"),
    )
    op.create_index("ix_trash_file_pending", "trash_file", ["operation_id", "done", "id"])


def downgrade():
    op.drop_table("trash_file")
    op.drop_table("trash_operation")
    op.drop_index("ix_work_trashed_at", "work")
    op.drop_column("work", "trashed_at")
