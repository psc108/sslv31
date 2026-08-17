"""add origin column to jar_kb_entries — distinguishes seeded built-in
articles from genuinely user-created ones now that both live in the DB

Revision ID: 043
Revises: 042
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = '043'
down_revision = '042'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'jar_kb_entries',
        sa.Column('origin', sa.String(16), nullable=False, server_default=sa.text('''('user')''')),
    )


def downgrade():
    op.drop_column('jar_kb_entries', 'origin')
