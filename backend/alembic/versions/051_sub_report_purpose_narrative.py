"""add sub_reports.purpose_narrative_json — Stage 6 of the dissection accuracy
plan. The "Perceived Purpose" narrative: a rule-based synthesis of domain
vocabulary, event topology role, DB ownership, dependency fingerprint, part.yml
categorisation, auth posture, and Stage 4's authored @Operation/@Schema text,
computed once per sub-report. Every inferred statement is explicitly framed
("based on the following static evidence, this service appears to...") —
never asserted as fact.

Revision ID: 051
Revises: 050
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '051'
down_revision = '050'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    op.add_column('sub_reports', sa.Column('purpose_narrative_json', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('sub_reports', 'purpose_narrative_json')
