"""Initial library identities and durable import journal.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
    )
    op.create_index("ix_work_created_at", "work", ["created_at"])
    op.create_table(
        "contributor",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_table(
        "credit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
        sa.Column("contributor_id", sa.String(36), sa.ForeignKey("contributor.id"), nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_index("ix_credit_work_id", "credit", ["work_id"])
    op.create_table(
        "edition",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_id", sa.String(36), sa.ForeignKey("work.id"), nullable=False),
        sa.Column("medium", sa.String, nullable=False),
        sa.Column("language", sa.String, nullable=False),
        sa.Column("publisher", sa.Text, nullable=False),
        sa.Column("identifier", sa.Text, nullable=False),
    )
    op.create_index("ix_edition_work_id", "edition", ["work_id"])
    op.create_table(
        "representation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("edition_id", sa.String(36), sa.ForeignKey("edition.id"), nullable=False),
        sa.Column("format", sa.String, nullable=False),
        sa.Column("cover_path", sa.Text),
        sa.Column("extracted_json", sa.Text, nullable=False),
    )
    op.create_index("ix_representation_edition_id", "representation", ["edition_id"])
    op.create_table(
        "asset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "representation_id", sa.String(36), sa.ForeignKey("representation.id"), nullable=False
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("root", sa.String, nullable=False),
        sa.Column("relative_path", sa.Text, nullable=False, unique=True),
        sa.Column("original_name", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.UniqueConstraint("representation_id", "position"),
    )
    op.create_index("ix_asset_representation_id", "asset", ["representation_id"])
    op.create_index("ix_asset_sha256", "asset", ["sha256"])
    op.create_table(
        "import_operation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("original_name", sa.Text, nullable=False),
        sa.Column("extracted_json", sa.Text, nullable=False),
        sa.Column("work_id", sa.String(36)),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.String, nullable=False),
    )
    op.create_index("ix_import_operation_state", "import_operation", ["state"])
    op.create_table(
        "login_session",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.Integer, nullable=False),
    )


def downgrade():
    for table in (
        "login_session",
        "import_operation",
        "asset",
        "representation",
        "edition",
        "credit",
        "contributor",
        "work",
    ):
        op.drop_table(table)
