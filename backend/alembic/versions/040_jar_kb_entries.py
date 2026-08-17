"""add jar_kb_entries table

Revision ID: 040
Revises: 039
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = '040'
down_revision = '039'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jar_kb_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('pattern', sa.Text(), nullable=False),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('plain_english', sa.Text(), nullable=False),
        sa.Column('causes_json', sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column('fix_steps_json', sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column('see_also_json', sa.Text(), nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column('created_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('jar_kb_entries')
