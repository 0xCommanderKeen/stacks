"""Immutable chosen cover originals, independent of media representations."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cover_blob",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    # SQLite supports a nullable inline reference without rebuilding the Work table.
    # Avoid dropping a populated parent table during upgrade or test downgrades.
    op.execute(
        "ALTER TABLE work ADD COLUMN selected_cover_id VARCHAR(36) REFERENCES cover_blob(id)"
    )


def downgrade():
    op.execute("ALTER TABLE work DROP COLUMN selected_cover_id")
    op.drop_table("cover_blob")
