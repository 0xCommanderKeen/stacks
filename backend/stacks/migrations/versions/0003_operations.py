"""Reversible catalog operations and superseded work redirects."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_redirect",
        sa.Column("source_id", sa.String(36), sa.ForeignKey("work.id"), primary_key=True),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
    )
    op.create_table(
        "catalog_operation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade():
    op.drop_table("catalog_operation")
    op.drop_table("work_redirect")
