"""JAR Analyser outbound call site analysis — response type / status-code
handling / caught+thrown exceptions found by text-scanning already-
decompiled source for outbound HTTP call sites (JAX-RS Client, RestTemplate,
WebClient). The response-shape/error-handling follow-up to migration 092's
outbound integration discovery. See outbound_call_analysis.py's module
docstring for the full rationale.

Populated only when a class is decompiled (Section 36's on-demand feature),
never automatically — no backfill for classes decompiled before this
migration, same as migration 091/092's own "no retroactive backfill" note.

Revision ID: 093
Revises: 092
"""
from alembic import op
import sqlalchemy as sa

revision = '093'
down_revision = '092'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jar_outbound_call_sites',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('jar_decompile_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('engine', sa.String(16), nullable=False),
        sa.Column('class_name', sa.String(512), nullable=False),
        sa.Column('method_name', sa.String(256), nullable=True),
        sa.Column('call_type', sa.String(16), nullable=False),
        sa.Column('call_snippet', sa.Text(), nullable=False),
        sa.Column('response_type', sa.String(256), nullable=True),
        sa.Column('caught_exceptions_json', sa.Text(), nullable=True),
        sa.Column('thrown_exceptions_json', sa.Text(), nullable=True),
        sa.Column('status_checks_json', sa.Text(), nullable=True),
    )
    op.create_index('ix_jar_outbound_call_sites_sub_report_id', 'jar_outbound_call_sites', ['sub_report_id'])
    op.create_index('ix_jar_outbound_call_sites_class_name', 'jar_outbound_call_sites', ['class_name'])


def downgrade():
    op.drop_index('ix_jar_outbound_call_sites_class_name', table_name='jar_outbound_call_sites')
    op.drop_index('ix_jar_outbound_call_sites_sub_report_id', table_name='jar_outbound_call_sites')
    op.drop_table('jar_outbound_call_sites')
