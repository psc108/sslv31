"""add analysis_reports.infra_requirements_json — Infra Requirements plan:
a report-level synthesis of what needs provisioning on the IAM/auth service,
MySQL, and RabbitMQ, derived purely from already-extracted static evidence
(roles/authorities from security annotations, Flyway table ownership,
messaging/DB/IAM connection facts from config keys, event topology). Every
requirement cites its evidence; explicit "known_gaps" entries state what this
tool cannot determine (domain/project placement, grant scoping, vhost
policy) rather than guessing.

Revision ID: 052
Revises: 051
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '052'
down_revision = '051'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    op.add_column('analysis_reports', sa.Column('infra_requirements_json', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('analysis_reports', 'infra_requirements_json')
