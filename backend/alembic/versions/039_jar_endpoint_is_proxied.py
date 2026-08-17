"""add is_proxied to jar_endpoints

Revision ID: 039
Revises: 038
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = '039'
down_revision = '038'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('jar_endpoints', sa.Column('is_proxied', sa.Boolean(), nullable=True))
    op.execute("UPDATE jar_endpoints SET is_proxied = NULL")


def downgrade():
    op.drop_column('jar_endpoints', 'is_proxied')
