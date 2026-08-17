"""add revocation_reason to certificates

Revision ID: 007
Revises: 006
Create Date: 2025-07-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("certificates", sa.Column("revocation_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("certificates", "revocation_reason")
