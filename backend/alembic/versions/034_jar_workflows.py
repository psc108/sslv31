"""034 jar workflows

Revision ID: 034
Revises: 033
Create Date: 2025-01-01

"""
from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jar_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36),
                  sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),  # auto_detected | manual
        sa.Column("steps_json", sa.Text, nullable=False),
    )
    op.create_index("ix_jar_workflows_sub_report_id", "jar_workflows", ["sub_report_id"])


def downgrade() -> None:
    op.drop_index("ix_jar_workflows_sub_report_id", "jar_workflows")
    op.drop_table("jar_workflows")
