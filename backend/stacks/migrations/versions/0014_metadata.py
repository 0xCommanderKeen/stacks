"""Compact chosen-field provenance and bounded provider suggestions."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "work", sa.Column("metadata_origins_json", sa.Text(), nullable=False, server_default="{}")
    )
    op.create_table(
        "metadata_suggestion",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "work_id", sa.String(36), sa.ForeignKey("work.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.Column("detailed", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("work_id", "provider_key"),
    )
    op.create_index("ix_metadata_suggestion_work_id", "metadata_suggestion", ["work_id"])


def downgrade():
    op.drop_table("metadata_suggestion")
    op.drop_column("work", "metadata_origins_json")
