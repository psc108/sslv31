"""Opt-in automatic bug creation on Ansible job failure — Improvements Plan
Stage 22. Two additions:

- New `bm_settings` table: a single global settings row (id='global'),
  fetched/created lazily by bug_pattern_scan.py rather than seeded here —
  a fresh install never needs a data migration just to have the row exist.
  No FK involved, so unlike migration 084 this is a plain create_table,
  no batch-mode dance required.
- `bugs.auto_created` boolean, default False — marks a bug as filed by the
  auto-filer rather than a human. Plain add_column with a server_default
  (needed because the column is NOT NULL and the table already has rows)
  works fine in SQLite without batch mode, same as any other non-FK column
  add in this codebase.

Revision ID: 086
Revises: 085
"""
from alembic import op
import sqlalchemy as sa

revision = '086'
down_revision = '085'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bm_settings',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('auto_file_bugs_on_failure', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_by', sa.String(128), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column('bugs', sa.Column('auto_created', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('bugs', 'auto_created')
    op.drop_table('bm_settings')
