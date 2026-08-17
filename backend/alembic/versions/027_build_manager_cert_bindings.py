"""build manager cert bindings

Revision ID: 027
Revises: 026
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_cert_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("environment_id", sa.String(36), sa.ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cert_serial", sa.String(64), nullable=False),
        sa.Column("role", sa.String(128), nullable=False),
        sa.Column("cert_type", sa.String(16), nullable=False, server_default="server"),
        sa.Column("host_id", sa.String(36), nullable=True),
        sa.Column("cert_path", sa.String(512), nullable=False, server_default="/etc/ssl/certs/server.pem"),
        sa.Column("key_path", sa.String(512), nullable=False, server_default="/etc/ssl/private/server-key.pem"),
        sa.Column("ca_path", sa.String(512), nullable=False, server_default="/etc/ssl/certs/ca-chain.pem"),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("auto_renew", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_renewed_at", sa.DateTime, nullable=True),
        sa.Column("renewal_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bm_cert_bindings_env", "bm_cert_bindings", ["environment_id"])
    op.create_index("ix_bm_cert_bindings_expires", "bm_cert_bindings", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_bm_cert_bindings_expires", table_name="bm_cert_bindings")
    op.drop_index("ix_bm_cert_bindings_env", table_name="bm_cert_bindings")
    op.drop_table("bm_cert_bindings")
