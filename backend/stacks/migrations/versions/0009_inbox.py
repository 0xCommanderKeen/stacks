"""Durable source discovery and review candidates."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intake_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root", sa.String(64), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "scan_directory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("intake_job.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.UniqueConstraint("job_id", "path"),
    )
    op.create_table(
        "inbox_candidate",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("observation_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("edits_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("root", "relative_path"),
    )
    op.create_table(
        "intake_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("intake_job.id"), nullable=False),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("inbox_candidate.id"), nullable=False
        ),
        sa.Column("state", sa.String(), nullable=False),
        sa.UniqueConstraint("job_id", "candidate_id"),
    )
    for table, columns in {
        "intake_job": ["state", "created_at"],
        "scan_directory": ["job_id", "done"],
        "inbox_candidate": ["root", "state", "sha256"],
        "intake_item": ["job_id", "candidate_id", "state"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])

    op.create_index("ix_scan_directory_pending", "scan_directory", ["job_id", "done", "id"])
    op.create_index("ix_intake_item_pending", "intake_item", ["job_id", "state", "id"])


def downgrade():
    for table in ("intake_item", "inbox_candidate", "scan_directory", "intake_job"):
        op.drop_table(table)
