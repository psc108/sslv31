"""Key escrow and recovery

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "key_escrow",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("certificate_serial", sa.String(64), nullable=False, index=True),
        sa.Column("certificate_cn", sa.String(255), nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("key_blob", sa.LargeBinary, nullable=False),
        sa.Column("escrowed_at", sa.DateTime, nullable=False),
        sa.Column("escrowed_by", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "key_recovery_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("escrow_id", sa.String(36), sa.ForeignKey("key_escrow.id"), nullable=False),
        sa.Column("certificate_serial", sa.String(64), nullable=False),
        sa.Column("justification", sa.Text, nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("requested_at", sa.DateTime, nullable=False),
        sa.Column("approvals_json", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("approvals_required", sa.Integer, nullable=False, server_default="2"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("download_expires_at", sa.DateTime, nullable=True),
        sa.Column("download_token", sa.String(64), nullable=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    # Add escrow_key flag to certificate_templates
    op.add_column("certificate_templates",
                  sa.Column("escrow_key", sa.Boolean, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("certificate_templates", "escrow_key")
    op.drop_table("key_recovery_requests")
    op.drop_table("key_escrow")
