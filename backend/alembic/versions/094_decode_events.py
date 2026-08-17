"""Decode events — persists each stack trace decode for ML training corpus.

Stores a fingerprint of the stack trace, which KB entries matched, the full
ML analysis blob, and a nullable root_cause_label for future supervised
training. No FK to docs/tenants beyond tenant_id — this is an append-only
event log, not a managed entity.

Revision ID: 094
Revises: 093
"""
from alembic import op
import sqlalchemy as sa

revision = '094'
down_revision = '093'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'decode_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stack_fingerprint', sa.String(64), nullable=False, index=True),
        sa.Column('exception_classes_json', sa.Text(), nullable=False),
        sa.Column('matched_kb_ids_json', sa.Text(), nullable=False),
        sa.Column('ml_analysis_json', sa.Text(), nullable=True),
        sa.Column('root_cause_label', sa.String(256), nullable=True, index=True),
    )


def downgrade():
    op.drop_table('decode_events')
