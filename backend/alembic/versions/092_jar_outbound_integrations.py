"""JAR Analyser outbound integration discovery — statically finds which
external systems a service calls out to (Feign clients, @Value-injected
URL/host config keys), so "which service talks to system X, at what URL"
is answerable without runtime tracing. See outbound_integrations.py's
module docstring for the full rationale.

No FTS table here (unlike migration 091's jar_strings_fts) — this data set
is small per service and browsed/filtered structurally (by kind, by
config_key), not searched as free text.

Revision ID: 092
Revises: 091
"""
from alembic import op
import sqlalchemy as sa

revision = '092'
down_revision = '091'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jar_outbound_integrations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('class_name', sa.String(512), nullable=False),
        sa.Column('target', sa.String(256), nullable=False),
        sa.Column('config_key', sa.String(256), nullable=True),
        sa.Column('raw_value', sa.String(1024), nullable=True),
        sa.Column('resolved_value', sa.String(1024), nullable=True),
    )
    op.create_index('ix_jar_outbound_integrations_sub_report_id', 'jar_outbound_integrations', ['sub_report_id'])
    op.create_index('ix_jar_outbound_integrations_class_name', 'jar_outbound_integrations', ['class_name'])
    op.create_index('ix_jar_outbound_integrations_config_key', 'jar_outbound_integrations', ['config_key'])


def downgrade():
    op.drop_index('ix_jar_outbound_integrations_config_key', table_name='jar_outbound_integrations')
    op.drop_index('ix_jar_outbound_integrations_class_name', table_name='jar_outbound_integrations')
    op.drop_index('ix_jar_outbound_integrations_sub_report_id', table_name='jar_outbound_integrations')
    op.drop_table('jar_outbound_integrations')
