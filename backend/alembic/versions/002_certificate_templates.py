"""certificate templates

Revision ID: 002
Revises: 001
Create Date: 2025-07-09

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "certificate_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text('''('')''')),
        sa.Column("allowed_key_algos", sa.Text(), nullable=False, server_default=sa.text('''('["RSA","ECDSA","Ed25519"]')''')),
        sa.Column("min_key_size", sa.Integer(), nullable=False, server_default="2048"),
        sa.Column("max_validity_days", sa.Integer(), nullable=False, server_default="398"),
        sa.Column("allowed_san_types", sa.Text(), nullable=False, server_default=sa.text('''('["dns","ip","email","uri"]')''')),
        sa.Column("require_san", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("key_usage", sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("extended_key_usage", sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("allowed_cn_pattern", sa.String(255), nullable=False, server_default=""),
        sa.Column("require_org", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Insert default templates
    templates_table = sa.table(
        "certificate_templates",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("allowed_key_algos", sa.Text),
        sa.column("min_key_size", sa.Integer),
        sa.column("max_validity_days", sa.Integer),
        sa.column("allowed_san_types", sa.Text),
        sa.column("require_san", sa.Boolean),
        sa.column("key_usage", sa.Text),
        sa.column("extended_key_usage", sa.Text),
        sa.column("allowed_cn_pattern", sa.String),
        sa.column("require_org", sa.Boolean),
        sa.column("is_builtin", sa.Boolean),
    )

    op.bulk_insert(templates_table, [
        {
            "id": str(uuid.uuid4()),
            "name": "server-tls",
            "display_name": "Server TLS",
            "description": "HTTPS servers, APIs, load balancers. Requires DNS or IP SAN.",
            "allowed_key_algos": '["RSA","ECDSA"]',
            "min_key_size": 2048,
            "max_validity_days": 398,
            "allowed_san_types": '["dns","ip"]',
            "require_san": True,
            "key_usage": '["digital_signature","key_encipherment"]',
            "extended_key_usage": '["serverAuth"]',
            "allowed_cn_pattern": "",
            "require_org": False,
            "is_builtin": True,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "client-mtls",
            "display_name": "Client mTLS",
            "description": "Service accounts, mutual TLS authentication.",
            "allowed_key_algos": '["RSA","ECDSA","Ed25519"]',
            "min_key_size": 2048,
            "max_validity_days": 398,
            "allowed_san_types": '["dns","ip","email","uri"]',
            "require_san": False,
            "key_usage": '["digital_signature"]',
            "extended_key_usage": '["clientAuth"]',
            "allowed_cn_pattern": "",
            "require_org": False,
            "is_builtin": True,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "code-signing",
            "display_name": "Code Signing",
            "description": "Binary and package signing. No SAN required.",
            "allowed_key_algos": '["RSA","ECDSA"]',
            "min_key_size": 2048,
            "max_validity_days": 1095,
            "allowed_san_types": '[]',
            "require_san": False,
            "key_usage": '["digital_signature","content_commitment"]',
            "extended_key_usage": '["codeSigning"]',
            "allowed_cn_pattern": "",
            "require_org": True,
            "is_builtin": True,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "email-smime",
            "display_name": "Email (S/MIME)",
            "description": "Email encryption and signing. Requires email SAN.",
            "allowed_key_algos": '["RSA","ECDSA"]',
            "min_key_size": 2048,
            "max_validity_days": 825,
            "allowed_san_types": '["email"]',
            "require_san": True,
            "key_usage": '["digital_signature","key_encipherment"]',
            "extended_key_usage": '["emailProtection"]',
            "allowed_cn_pattern": "",
            "require_org": False,
            "is_builtin": True,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "internal-service",
            "display_name": "Internal Service",
            "description": "Internal microservices. Allows both server and client auth.",
            "allowed_key_algos": '["RSA","ECDSA","Ed25519"]',
            "min_key_size": 2048,
            "max_validity_days": 398,
            "allowed_san_types": '["dns","ip","uri"]',
            "require_san": False,
            "key_usage": '["digital_signature","key_encipherment"]',
            "extended_key_usage": '["serverAuth","clientAuth"]',
            "allowed_cn_pattern": "",
            "require_org": False,
            "is_builtin": True,
        },
    ])


def downgrade() -> None:
    op.drop_table("certificate_templates")
