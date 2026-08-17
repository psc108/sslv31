"""add jar_decompile_runs and jar_decompiled_classes tables

Revision ID: 068
Revises: 067
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '068'
down_revision = '067'
branch_labels = None
depends_on = None

# Plain TEXT caps at 64KB in MySQL — decompiled Java source and multi-jar
# run summaries can exceed that, so these tables use LONGTEXT on MySQL from
# creation rather than needing a follow-up widening migration.
_long_text = sa.Text().with_variant(mysql.LONGTEXT(), 'mysql')


def upgrade():
    op.create_table(
        'jar_decompile_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('report_id', sa.String(36), sa.ForeignKey('analysis_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='120'),
        sa.Column('jars_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('jars_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('jars_failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('results_json', _long_text, nullable=True),
        sa.Column('error', _long_text, nullable=True),
    )

    op.create_table(
        'jar_decompiled_classes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('jar_decompile_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('class_name', sa.String(512), nullable=False),
        sa.Column('package_name', sa.String(512), nullable=False, server_default=''),
        sa.Column('simple_name', sa.String(256), nullable=False),
        sa.Column('source', _long_text, nullable=True),
        sa.Column('decompiled_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_jar_decompiled_classes_class_name', 'jar_decompiled_classes', ['class_name'])


def downgrade():
    op.drop_index('ix_jar_decompiled_classes_class_name', table_name='jar_decompiled_classes')
    op.drop_table('jar_decompiled_classes')
    op.drop_table('jar_decompile_runs')
