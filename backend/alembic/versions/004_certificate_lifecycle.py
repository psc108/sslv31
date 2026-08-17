"""certificate lifecycle

Revision ID: 004
Revises: 003
Create Date: 2025-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("certificates", sa.Column("held_at", sa.DateTime(), nullable=True))
    op.add_column("certificates", sa.Column("renewed_from", sa.String(64), nullable=True))
    op.add_column("certificates", sa.Column("renewed_to", sa.String(64), nullable=True))
    op.add_column("certificates", sa.Column("auto_renew", sa.Boolean(), nullable=True, server_default="0"))


def downgrade() -> None:
    op.drop_column("certificates", "auto_renew")
    op.drop_column("certificates", "renewed_to")
    op.drop_column("certificates", "renewed_from")
    op.drop_column("certificates", "held_at")
