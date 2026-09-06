"""Owner-issued read-only device credentials, excluded from portable recovery."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work", sa.Column("updated_at", sa.String(), nullable=False, server_default=""))
    op.execute("UPDATE work SET updated_at = created_at")
    op.create_table(
        "device_credential",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_used_at", sa.String()),
    )


def downgrade():
    op.drop_table("device_credential")
    op.drop_column("work", "updated_at")
