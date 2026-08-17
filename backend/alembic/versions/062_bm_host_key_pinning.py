"""Build Manager Enhancement Plan, Stage 9 — host-key verification (TOFU pinning).

Adds BMHost.pinned_host_key (the raw ssh-keyscan line, not just a display
fingerprint — needed to write a real known_hosts file) and
host_key_pinned_at. Both nullable so every existing host is simply
"not yet pinned" and gets pinned on its next successful connection.

Revision ID: 062
Revises: 061
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '062'
down_revision = '061'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_hosts', sa.Column('pinned_host_key', sa.Text(), nullable=True))
    op.add_column('bm_hosts', sa.Column('host_key_pinned_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('bm_hosts', 'host_key_pinned_at')
    op.drop_column('bm_hosts', 'pinned_host_key')
