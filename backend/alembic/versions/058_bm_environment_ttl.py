"""Build Manager Enhancement Plan, Stage 5 — environment TTL / scheduled auto-destroy.

Adds BMEnvironment.expires_at (nullable — opt-in, doesn't affect any existing
environment). A background loop (mirroring run_expiry_scanner's periodic-poll
pattern) destroys environments past their TTL via the existing
destroy_environment() service function.

Revision ID: 058
Revises: 057
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '058'
down_revision = '057'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_environments', sa.Column('expires_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('bm_environments', 'expires_at')
