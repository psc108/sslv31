"""add jar_endpoints.parsed_auth_json — found via a systematic model-vs-migrated-
schema comparison while validating MySQL reproducibility: this column is
declared on the JarEndpoint model and actively read/written by
app/services/jar_analyser/persistence.py and app/api/v1/jar_analyser.py, but
no prior migration ever created it. It silently existed on the long-lived dev
SQLite database (added out-of-band at some point), so the drift only surfaced
when building a schema fresh from migrations alone.

Revision ID: 047
Revises: 046
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '047'
down_revision = '046'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    # Defensive: some existing databases already have this column from before
    # it had a migration (see revision docstring) — skip if already present
    # rather than failing with "duplicate column".
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("jar_endpoints")}
    if "parsed_auth_json" not in existing:
        op.add_column('jar_endpoints', sa.Column('parsed_auth_json', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('jar_endpoints', 'parsed_auth_json')
