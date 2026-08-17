"""Tenant scoping for jar_uploads and analysis_reports.

Revision ID: 071
Revises: 070

Mirrors 014_multi_tenancy.py's own pattern exactly (tenant_id added nullable,
backfilled to the default tenant, then a best-effort NOT NULL that's a no-op
on SQLite — enforcement lives at the model layer via default=DEFAULT_TENANT_ID).
Scoped to jar_uploads and analysis_reports only: every other jar_analyser
table (sub_reports, jar_endpoints, jar_decompile_runs, jar_config_examples,
...) cascades from one of these two via FK, so scoping the two root entities
is sufficient — see Documentation/jar_analyser_production_readiness_plan.md.
"""

from alembic import op
import sqlalchemy as sa

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

_TABLES = ["jar_uploads", "analysis_reports"]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.execute(f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT_ID}'")
        try:
            op.alter_column(table, "tenant_id", nullable=False)
        except Exception:
            pass  # SQLite limitation — column stays nullable but always populated
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in _TABLES:
        try:
            op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        except Exception:
            pass
        op.drop_column(table, "tenant_id")
