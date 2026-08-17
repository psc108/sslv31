"""add analysis_reports.consistency_findings_json — Stage 3 of the dissection
accuracy plan: static cross-validation findings (DTO-vs-schema type
mismatches, event payload resolution gaps, service wiring inconsistencies,
cross-service DTO resolution gaps), computed once per analysis and surfaced
as a first-class report section.

Revision ID: 048
Revises: 047
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '048'
down_revision = '047'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    op.add_column('analysis_reports', sa.Column('consistency_findings_json', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('analysis_reports', 'consistency_findings_json')
