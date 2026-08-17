"""038_jar_endpoint_linked_tables

Revision ID: 038
Revises: 037
"""
from alembic import op
import sqlalchemy as sa

revision = '038'
down_revision = '037'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('jar_endpoints', sa.Column('linked_tables_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('jar_endpoints', 'linked_tables_json')
