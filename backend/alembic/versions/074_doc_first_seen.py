"""Docs "first seen" report link — first_seen_report_id/first_seen_sub_report_id on docs.

Revision ID: 074
Revises: 073

Stage 1 of the doc-first-seen plan (see
Documentation/planning/doc_first_seen_plan.md). A single, optional origin
link — where the issue behind a doc was first observed — not the Bug
Tracker's BugOccurrence-style multi-report pattern tracking. Both columns
nullable from the start: no backfill needed, unlike the tenant_id migrations.
"""
from alembic import op
import sqlalchemy as sa

revision = '074'
down_revision = '073'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = {r[1] for r in bind.execute(sa.text('PRAGMA table_info(docs)')).fetchall()}
    if 'first_seen_report_id' not in existing:
        op.add_column('docs', sa.Column(
            'first_seen_report_id', sa.String(36),
            sa.ForeignKey('analysis_reports.id', ondelete='SET NULL'), nullable=True,
        ))
        op.create_index('ix_docs_first_seen_report_id', 'docs', ['first_seen_report_id'])
    if 'first_seen_sub_report_id' not in existing:
        op.add_column('docs', sa.Column(
            'first_seen_sub_report_id', sa.String(36),
            sa.ForeignKey('sub_reports.id', ondelete='SET NULL'), nullable=True,
        ))
        op.create_index('ix_docs_first_seen_sub_report_id', 'docs', ['first_seen_sub_report_id'])


def downgrade():
    op.drop_index('ix_docs_first_seen_sub_report_id', table_name='docs')
    op.drop_index('ix_docs_first_seen_report_id', table_name='docs')
    op.drop_column('docs', 'first_seen_sub_report_id')
    op.drop_column('docs', 'first_seen_report_id')
