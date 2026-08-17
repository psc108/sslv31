"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Certificate Authorities
    op.create_table(
        "certificate_authorities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cn", sa.String(255), nullable=False),
        sa.Column("subject_json", sa.Text(), nullable=False),
        sa.Column("key_algo", sa.String(16), nullable=False),
        sa.Column("key_size", sa.Integer(), nullable=False),
        sa.Column("cert_pem", sa.Text(), nullable=False),
        sa.Column("key_blob", sa.LargeBinary(), nullable=False),
        sa.Column("path_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_root", sa.Boolean(), server_default="1"),
        sa.Column("source", sa.String(32), server_default="user"),
        sa.Column("parent_ca_id", sa.String(36), sa.ForeignKey("certificate_authorities.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Certificates
    op.create_table(
        "certificates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("serial", sa.String(64), unique=True, nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("subject_json", sa.Text(), nullable=False),
        sa.Column("san_json", sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("key_algo", sa.String(16), nullable=False),
        sa.Column("key_size", sa.Integer(), nullable=False),
        sa.Column("cert_pem", sa.Text(), nullable=False),
        sa.Column("key_blob", sa.LargeBinary(), nullable=False),
        sa.Column("chain_pem", sa.Text(), nullable=False, server_default=sa.text('''('')''')),
        sa.Column("signing_ca_id", sa.String(36), sa.ForeignKey("certificate_authorities.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="valid"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("expiry_warning", sa.Boolean(), server_default="0"),
        sa.Column("repeated_key_download", sa.Boolean(), server_default="0"),
        sa.Column("tags", sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_certificates_serial", "certificates", ["serial"])
    op.create_index("ix_certificates_status", "certificates", ["status"])
    op.create_index("ix_certificates_status_expires", "certificates", ["status", "expires_at"])

    # Trust Stores
    op.create_table(
        "truststores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("store_type", sa.String(8), nullable=False),
        sa.Column("ca_ids_json", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Audit Events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("operator", sa.String(255), nullable=True),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("api_key_hint", sa.String(8), nullable=True),
        sa.Column("subject_type", sa.String(32), nullable=True),
        sa.Column("subject_id", sa.String(64), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_subject_id", "audit_events", ["subject_id"])
    op.create_index("ix_audit_events_type_timestamp", "audit_events", ["event_type", "timestamp"])

    # Certificate Signing Requests
    op.create_table(
        "certificate_signing_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("subject_json", sa.Text(), nullable=False),
        sa.Column("san_json", sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("key_algo", sa.String(16), nullable=False),
        sa.Column("key_size", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(8), nullable=False, server_default="sha256"),
        sa.Column("csr_pem", sa.Text(), nullable=False),
        sa.Column("key_blob", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("signed_cert_id", sa.String(36), sa.ForeignKey("certificates.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_csr_status", "certificate_signing_requests", ["status"])


def downgrade() -> None:
    op.drop_table("certificate_signing_requests")
    op.drop_table("audit_events")
    op.drop_table("truststores")
    op.drop_table("certificates")
    op.drop_table("certificate_authorities")
