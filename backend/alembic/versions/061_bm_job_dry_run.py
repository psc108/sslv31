"""Build Manager Enhancement Plan, Stage 8 — Ansible check-mode / dry-run.

Adds BMJob.dry_run (default False — every existing job keeps its real
meaning). Persisted rather than request-only, so a dry-run job is never
mistaken for a real one in the job history.

Revision ID: 061
Revises: 060
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '061'
down_revision = '060'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_jobs', sa.Column('dry_run', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('bm_jobs', 'dry_run')
