"""add jar_scheduled_jobs table — extracts @Scheduled/@Schedules annotated
methods from bytecode (any class, not just controllers). Reveals background/
batch work that nothing else in this tool surfaced before: what runs on a
timer, how often (cron/fixedRate/fixedDelay), and where. Config-driven
schedules (Spring placeholder values) are flagged rather than resolved, same
discipline as the rest of the JAR Analyser's config-key handling.

Revision ID: 053
Revises: 052
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '053'
down_revision = '052'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jar_scheduled_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('declaring_class', sa.String(512), nullable=False),
        sa.Column('declaring_class_simple', sa.String(256), nullable=False),
        sa.Column('method_name', sa.String(256), nullable=False),
        sa.Column('cron', sa.String(128), nullable=True),
        sa.Column('fixed_rate_ms', sa.BigInteger(), nullable=True),
        sa.Column('fixed_delay_ms', sa.BigInteger(), nullable=True),
        sa.Column('initial_delay_ms', sa.BigInteger(), nullable=True),
        sa.Column('zone', sa.String(64), nullable=True),
        sa.Column('is_config_driven', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('display', sa.String(512), nullable=False, server_default=''),
    )
    op.create_index('ix_jar_scheduled_jobs_sub_report_id', 'jar_scheduled_jobs', ['sub_report_id'])


def downgrade():
    op.drop_index('ix_jar_scheduled_jobs_sub_report_id', table_name='jar_scheduled_jobs')
    op.drop_table('jar_scheduled_jobs')
