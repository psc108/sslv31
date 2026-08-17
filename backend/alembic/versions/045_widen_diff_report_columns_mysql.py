"""widen jar_diff_reports large JSON blob columns for MySQL — plain TEXT caps
out at 64KB in MySQL, and full-schema diffs between two large JAR analysis
reports routinely exceed that (observed 300KB+ diff_json in real data).
SQLite/PostgreSQL TEXT has no such practical limit, so this is MySQL-only;
those dialects are unaffected by with_variant().

Revision ID: 045
Revises: 044
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '045'
down_revision = '044'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    with op.batch_alter_table('jar_diff_reports') as batch_op:
        batch_op.alter_column('summary_json', existing_type=sa.Text(), type_=_LONGTEXT_ON_MYSQL)
        batch_op.alter_column('diff_json', existing_type=sa.Text(), type_=_LONGTEXT_ON_MYSQL)
        batch_op.alter_column('warnings_json', existing_type=sa.Text(), type_=_LONGTEXT_ON_MYSQL)


def downgrade():
    with op.batch_alter_table('jar_diff_reports') as batch_op:
        batch_op.alter_column('summary_json', existing_type=_LONGTEXT_ON_MYSQL, type_=sa.Text())
        batch_op.alter_column('diff_json', existing_type=_LONGTEXT_ON_MYSQL, type_=sa.Text())
        batch_op.alter_column('warnings_json', existing_type=_LONGTEXT_ON_MYSQL, type_=sa.Text())
