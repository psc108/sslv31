"""Automated cross-job bug pattern scan — Improvements Plan Stage 21. Adds
bm_jobs.related_bug_ids_json, the same shape as AnalysisReport's own
related_bug_ids_json column (migration 079) — null means "not yet
scanned," "[]" means "scanned, nothing found."

Revision ID: 085
Revises: 084
"""
from alembic import op
import sqlalchemy as sa

revision = '085'
down_revision = '084'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_jobs', sa.Column('related_bug_ids_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('bm_jobs', 'related_bug_ids_json')
