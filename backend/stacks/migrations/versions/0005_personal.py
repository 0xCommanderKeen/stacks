"""Personal shelves and repeat reading records."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_state",
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), primary_key=True),
        sa.Column("default_shelf", sa.String(), nullable=False),
        sa.Column("shelf_override", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "reading_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
        sa.Column("representation_id", sa.String(36), sa.ForeignKey("representation.id")),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("started", sa.String(), nullable=False),
        sa.Column("finished", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_reading_record_work_id", "reading_record", ["work_id"])
    op.create_index("ix_reading_record_representation_id", "reading_record", ["representation_id"])


def downgrade():
    op.drop_table("reading_record")
    op.drop_table("personal_state")
