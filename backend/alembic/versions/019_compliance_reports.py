"""019 — Compliance scans table for historical reporting."""

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("total_checked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_violations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_warnings", sa.Integer, nullable=False, server_default="0"),
        sa.Column("results_json", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("summary_json", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("scanned_at", sa.DateTime, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("compliance_scans")
