"""Automatic job retry on transient host failures.

Adds BMJob.auto_retry_count (default 0 — every existing job is an original
submission). Tracks how many times a job chain has already been
automatically retried (see ansible_runner.py's _execute_job), capped at
settings.BM_MAX_AUTO_RETRIES, separate from the existing manual
POST /jobs/{id}/retry endpoint.

Revision ID: 064
Revises: 063
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = '064'
down_revision = '063'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_jobs', sa.Column('auto_retry_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('bm_jobs', 'auto_retry_count')
