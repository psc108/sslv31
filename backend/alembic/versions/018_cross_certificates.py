"""Cross-certificates table for trust bridge management.

Revision ID: 018
Revises: 017
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cross_certificates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuing_ca_id", sa.String(36), sa.ForeignKey("certificate_authorities.id"), nullable=False),
        sa.Column("external_ca_cn", sa.String(255), nullable=False),
        sa.Column("external_ca_subject_json", sa.Text, nullable=False),
        sa.Column("external_ca_cert_pem", sa.Text, nullable=False),
        sa.Column("cross_cert_pem", sa.Text, nullable=False),
        sa.Column("serial", sa.String(64), unique=True, nullable=False),
        sa.Column("path_length", sa.Integer, nullable=False, server_default="0"),
        sa.Column("name_constraints_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("direction", sa.String(16), nullable=False, server_default="outbound"),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cross_certificates")
