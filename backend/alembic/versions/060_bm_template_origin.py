"""Build Manager Enhancement Plan, Stage 7 — golden-path reference templates.

Adds BMTemplate.origin ('builtin' | 'user'), mirroring the JAR Analyser
error-KB's origin column. Every existing template becomes 'user' (the
default) — no behaviour change for anything already in the database. A
seed script populates a handful of curated multi-service templates as
origin='builtin', fully editable/deletable like any other template once
seeded (delete is a genuine, permanent delete, recoverable only by
re-running the seed for that name).

Revision ID: 060
Revises: 059
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '060'
down_revision = '059'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bm_templates', sa.Column('origin', sa.String(16), nullable=False, server_default='user'))


def downgrade():
    op.drop_column('bm_templates', 'origin')
