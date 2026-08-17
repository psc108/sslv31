"""add jar_diagnostic_runs table

Revision ID: 041
Revises: 040
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa

revision = '041'
down_revision = '040'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jar_diagnostic_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('report_id', sa.String(36), sa.ForeignKey('analysis_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uploaded_by', sa.String(256), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('bundle_filename', sa.String(512), nullable=True),
        sa.Column('bundle_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('hostname', sa.String(256), nullable=True),
        sa.Column('os_id', sa.String(64), nullable=True),
        sa.Column('platform_version', sa.String(64), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('summary_json', sa.Text(), nullable=True),
        sa.Column('findings_json', sa.Text(), nullable=True),
        sa.Column('cert_results_json', sa.Text(), nullable=True),
        sa.Column('port_results_json', sa.Text(), nullable=True),
        sa.Column('rmq_summary_json', sa.Text(), nullable=True),
        sa.Column('config_issues_json', sa.Text(), nullable=True),
        sa.Column('log_findings_json', sa.Text(), nullable=True),
        sa.Column('os_info', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('jar_diagnostic_runs')
