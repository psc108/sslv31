"""Build Manager Enhancement Plan, Stage 4 — job retry-on-partial-failure.

Adds BMJob.failed_hosts (nullable JSON list of hostnames), populated by
parsing the job's own captured output for Ansible's fatal/unreachable lines
as it streams in. Backs POST /jobs/{id}/retry's --limit filter.

Revision ID: 057
Revises: 056
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '057'
down_revision = '056'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_jobs', sa.Column('failed_hosts', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('bm_jobs', 'failed_hosts')
