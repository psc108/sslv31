"""Add pagination detection columns to jar_endpoints.

Revision ID: 036
"""
from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jar_endpoints", sa.Column("is_paginated", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("jar_endpoints", sa.Column("page_param",   sa.String(64),  nullable=True))
    op.add_column("jar_endpoints", sa.Column("size_param",   sa.String(64),  nullable=True))
    op.add_column("jar_endpoints", sa.Column("sort_param",   sa.String(64),  nullable=True))
    op.add_column("jar_endpoints", sa.Column("default_page_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("jar_endpoints", "default_page_size")
    op.drop_column("jar_endpoints", "sort_param")
    op.drop_column("jar_endpoints", "size_param")
    op.drop_column("jar_endpoints", "page_param")
    op.drop_column("jar_endpoints", "is_paginated")
