"""add analysis_reports.related_bug_ids_json — Improvements Plan Stage 12
(automated cross-report bug pattern scan). JSON list of open Bug ids
(best-first), computed once right after analysis completes by
app/services/jar_analyser/bug_pattern_scan.py. Null means "not yet
scanned"; an empty list "[]" means "scanned, nothing related found" — kept
distinguishable rather than defaulting to "[]" so a report analysed before
this column existed doesn't look identical to one that was actually
scanned and came up empty.

Revision ID: 079
Revises: 078
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '079'
down_revision = '078'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    op.add_column('analysis_reports', sa.Column('related_bug_ids_json', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('analysis_reports', 'related_bug_ids_json')
