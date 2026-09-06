"""Durable backup state and completion history."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backup_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String()),
        sa.Column("error", sa.Text()),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_backup_record_state", "backup_record", ["state"])


def downgrade():
    op.drop_table("backup_record")
