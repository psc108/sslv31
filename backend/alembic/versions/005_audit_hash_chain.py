"""audit hash chain

Revision ID: 005
Revises: 004
Create Date: 2025-01-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("prev_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_events", "prev_hash")
