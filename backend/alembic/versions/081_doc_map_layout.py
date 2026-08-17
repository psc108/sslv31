"""add doc_libraries.map_layout_json — Improvements Plan Stage 14 (Map View
manual-layout persistence). Nullable Text/JSON column, {doc_id: {x, y}} of
manually-dragged node positions; null means "no manual layout, auto-arrange."

Revision ID: 081
Revises: 080
"""
from alembic import op
import sqlalchemy as sa

revision = '081'
down_revision = '080'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('doc_libraries', sa.Column('map_layout_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('doc_libraries', 'map_layout_json')
