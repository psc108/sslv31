"""Error KB usage tracking — Improvements Plan Stage 16. One row per KB
entry (a Doc id) that's actually matched real pasted/scanned error text at
least once, via either the Docs Search tab's pattern mode or JAR Analyser's
report-context-aware Diagnose. A KB entry that's never matched simply has
no row — the usage endpoint treats that as count 0.

Revision ID: 082
Revises: 081
"""
from alembic import op
import sqlalchemy as sa

revision = '082'
down_revision = '081'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kb_match_counts',
        sa.Column('doc_id', sa.String(36), sa.ForeignKey('docs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('match_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_matched_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('kb_match_counts')
