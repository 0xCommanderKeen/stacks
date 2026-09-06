"""Previewed acceptance groups share the durable intake queue."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "intake_job", sa.Column("kind", sa.String(), nullable=False, server_default="scan")
    )
    op.add_column(
        "intake_job", sa.Column("options_json", sa.Text(), nullable=False, server_default="{}")
    )
    op.create_index("ix_intake_job_kind", "intake_job", ["kind"])
    op.add_column("intake_item", sa.Column("snapshot_json", sa.Text()))
    op.add_column("intake_item", sa.Column("candidate_revision", sa.Integer()))
    op.add_column("intake_item", sa.Column("group_id", sa.String(36)))
    op.add_column("intake_item", sa.Column("result_work_id", sa.String(36)))
    op.add_column("intake_item", sa.Column("error", sa.Text()))
    op.create_index("ix_intake_item_group", "intake_item", ["job_id", "group_id", "state"])


def downgrade():
    op.drop_index("ix_intake_item_group", "intake_item")
    for column in ("error", "result_work_id", "group_id", "candidate_revision", "snapshot_json"):
        op.drop_column("intake_item", column)
    op.drop_index("ix_intake_job_kind", "intake_job")
    op.drop_column("intake_job", "options_json")
    op.drop_column("intake_job", "kind")
