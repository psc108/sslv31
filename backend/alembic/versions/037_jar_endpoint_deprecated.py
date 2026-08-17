"""Add is_deprecated column to jar_endpoints.

Revision ID: 037
"""
from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jar_endpoints", sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("jar_endpoints", "is_deprecated")
