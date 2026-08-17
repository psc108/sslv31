"""Per-template configurable Ansible job timeout.

Adds BMJob.timeout_seconds (default 1800 — matches the previous single
global settings.BM_ANSIBLE_TIMEOUT constant every existing job effectively
ran under). Resolved from a template's spec["ansible_timeout_minutes"] at
submit_job() time (see ansible_runner.py) instead of a single fixed value
for every template.

Revision ID: 065
Revises: 064
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = '065'
down_revision = '064'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_jobs', sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='1800'))


def downgrade():
    op.drop_column('bm_jobs', 'timeout_seconds')
