"""Build Manager inventory tables

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_hosts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(64), nullable=False, server_default="root"),
        sa.Column("os_type", sa.String(32), nullable=False, server_default="ubuntu"),
        sa.Column("os_version", sa.String(32), nullable=False, server_default="24.04"),
        sa.Column("service_role", sa.String(32), nullable=False, server_default="generic"),
        sa.Column("tags", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_host_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("tenant_id", sa.String(36), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_host_group_members",
        sa.Column("host_id", sa.String(36), sa.ForeignKey("bm_hosts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_id", sa.String(36), sa.ForeignKey("bm_host_groups.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "bm_host_vars",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("host_id", sa.String(36), sa.ForeignKey("bm_hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("encrypted", sa.Boolean, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("bm_host_vars")
    op.drop_table("bm_host_group_members")
    op.drop_table("bm_host_groups")
    op.drop_table("bm_hosts")
