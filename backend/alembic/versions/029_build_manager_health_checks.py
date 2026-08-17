"""build manager health checks

Revision ID: 029
Revises: 028
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_health_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("environment_id", sa.String(36), sa.ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_role", sa.String(128), nullable=False),
        sa.Column("service_type", sa.String(64), nullable=False, server_default="generic"),
        sa.Column("check_type", sa.String(32), nullable=False, server_default="health"),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("details", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("last_checked", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bm_health_checks_env", "bm_health_checks", ["environment_id"])
    op.create_index("ix_bm_health_checks_status", "bm_health_checks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bm_health_checks_status", table_name="bm_health_checks")
    op.drop_index("ix_bm_health_checks_env", table_name="bm_health_checks")
    op.drop_table("bm_health_checks")
