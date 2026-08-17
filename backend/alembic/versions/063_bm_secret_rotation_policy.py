"""Build Manager Enhancement Plan, Stage 10 — policy-driven secret rotation.

Adds BMSecret.rotate_every_days (nullable — every existing secret has no
policy and behaves exactly as before) and rotation_notified (default False,
tracks whether the one-shot overdue notification has already fired so the
periodic scanner doesn't re-notify every tick).

Revision ID: 063
Revises: 062
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '063'
down_revision = '062'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_secrets', sa.Column('rotate_every_days', sa.Integer(), nullable=True))
    op.add_column('bm_secrets', sa.Column('rotation_notified', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('bm_secrets', 'rotation_notified')
    op.drop_column('bm_secrets', 'rotate_every_days')
