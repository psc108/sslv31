"""name constraints and approval workflow

Revision ID: 006
Revises: 005
Create Date: 2025-01-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Name constraints on CAs
    op.add_column("certificate_authorities", sa.Column("name_constraints_json", sa.Text(), nullable=True))

    # Certificate policy settings on CAs
    op.add_column("certificate_authorities", sa.Column("policy_oid", sa.String(64), nullable=True))
    op.add_column("certificate_authorities", sa.Column("cps_url", sa.String(512), nullable=True))

    # Approval workflow
    op.create_table(
        "pending_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_type", sa.String(16), nullable=False),  # cert, csr_sign
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),  # pending, approved, rejected
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("template_name", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_pending_requests_status", "pending_requests", ["status"])

    # Add require_approval to templates
    op.add_column("certificate_templates", sa.Column("require_approval", sa.Boolean(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("certificate_templates", "require_approval")
    op.drop_index("ix_pending_requests_status", table_name="pending_requests")
    op.drop_table("pending_requests")
    op.drop_column("certificate_authorities", "cps_url")
    op.drop_column("certificate_authorities", "policy_oid")
    op.drop_column("certificate_authorities", "name_constraints_json")
