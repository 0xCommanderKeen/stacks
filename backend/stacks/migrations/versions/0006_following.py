"""Series following and deliberate next-up browsing."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "series", sa.Column("following", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade():
    op.drop_column("series", "following")
