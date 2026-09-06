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
    with op.batch_alter_table("work") as batch:
        batch.add_column(sa.Column("selected_cover_id", sa.String(36)))
        batch.create_foreign_key(
            "fk_work_selected_cover", "cover_blob", ["selected_cover_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("work") as batch:
        batch.drop_constraint("fk_work_selected_cover", type_="foreignkey")
        batch.drop_column("selected_cover_id")
    op.drop_table("cover_blob")
