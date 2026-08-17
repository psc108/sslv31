"""Add notification_email to users table.

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("notification_email", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "notification_email")
