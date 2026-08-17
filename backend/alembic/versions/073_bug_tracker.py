"""Bug Tracker feature — bugs, bug_comments, bug_history_entries, bug_occurrences tables.

Revision ID: 073
Revises: 072
Create Date: 2026-08-11

Stage 1 of the bug tracker plan (see Documentation/planning/bug_tracker_plan.md).
Real relational columns for anything queried/filtered/joined/transitioned
(status, severity, report/sub-report links, assignee) — markdown text only
for the actual prose (description, resolution). bug_occurrences is the
mechanism for tracking the same bug across multiple reports.
"""
from alembic import op
import sqlalchemy as sa

revision = '073'
down_revision = '072'
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    op.create_table(
        'bugs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False,
                   server_default=DEFAULT_TENANT_ID),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('severity', sa.String(16), nullable=False, server_default='medium'),
        sa.Column('frequency', sa.String(16), nullable=True),
        sa.Column('tags_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('report_id', sa.String(36), sa.ForeignKey('analysis_reports.id', ondelete='SET NULL'), nullable=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reporter', sa.String(256), nullable=True),
        sa.Column('assignee', sa.String(256), nullable=True),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_bugs_tenant_id', 'bugs', ['tenant_id'])
    op.create_index('ix_bugs_report_id', 'bugs', ['report_id'])
    op.create_index('ix_bugs_sub_report_id', 'bugs', ['sub_report_id'])

    op.create_table(
        'bug_comments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('bug_id', sa.String(36), sa.ForeignKey('bugs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author', sa.String(256), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_bug_comments_bug_id', 'bug_comments', ['bug_id'])

    op.create_table(
        'bug_history_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('bug_id', sa.String(36), sa.ForeignKey('bugs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('from_status', sa.String(16), nullable=True),
        sa.Column('to_status', sa.String(16), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('actor', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_bug_history_entries_bug_id', 'bug_history_entries', ['bug_id'])

    op.create_table(
        'bug_occurrences',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('bug_id', sa.String(36), sa.ForeignKey('bugs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('report_id', sa.String(36), sa.ForeignKey('analysis_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('noted_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_bug_occurrences_bug_id', 'bug_occurrences', ['bug_id'])
    op.create_index('ix_bug_occurrences_report_id', 'bug_occurrences', ['report_id'])


def downgrade():
    op.drop_index('ix_bug_occurrences_report_id', table_name='bug_occurrences')
    op.drop_index('ix_bug_occurrences_bug_id', table_name='bug_occurrences')
    op.drop_table('bug_occurrences')
    op.drop_index('ix_bug_history_entries_bug_id', table_name='bug_history_entries')
    op.drop_table('bug_history_entries')
    op.drop_index('ix_bug_comments_bug_id', table_name='bug_comments')
    op.drop_table('bug_comments')
    op.drop_index('ix_bugs_sub_report_id', table_name='bugs')
    op.drop_index('ix_bugs_report_id', table_name='bugs')
    op.drop_index('ix_bugs_tenant_id', table_name='bugs')
    op.drop_table('bugs')
