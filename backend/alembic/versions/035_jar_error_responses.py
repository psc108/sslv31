"""jar_error_responses

Revision ID: 035
Revises: 034
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '035'
down_revision = '034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jar_error_responses',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36),
                  sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('exception_class', sa.String(512), nullable=True),
        sa.Column('response_schema_class', sa.String(512), nullable=True),
        sa.Column('scope', sa.String(32), nullable=False, server_default='global'),
        sa.Column('controller_class', sa.String(512), nullable=True),
        sa.Column('fields_json', sa.Text(), nullable=True),
    )
    op.create_index('ix_jar_error_responses_sub_report_id',
                    'jar_error_responses', ['sub_report_id'])


def downgrade() -> None:
    op.drop_index('ix_jar_error_responses_sub_report_id', 'jar_error_responses')
    op.drop_table('jar_error_responses')
