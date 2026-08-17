"""Snapshot a job's build environment onto the job itself.

`bm_jobs.environment_id` alone isn't a durable record of what a job was
built against: destroy_environment() nulls it out and hard-deletes the
BMEnvironment row (and its product-config/cert rows), so once an
environment is torn down — routine for test/build workflows — a job's OS,
per-host product versions, IP allocations, and issued certs are gone with
it. `build_snapshot_json` captures that context at submit_job() time
(environment_service.build_environment_snapshot), so it survives.

Plain add_column, nullable, no server_default needed (existing jobs simply
have no snapshot, same as any other pre-feature row).

Revision ID: 087
Revises: 086
"""
from alembic import op
import sqlalchemy as sa

revision = '087'
down_revision = '086'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_jobs', sa.Column('build_snapshot_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('bm_jobs', 'build_snapshot_json')
