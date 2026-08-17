"""widen audit_events.api_key_hint — it stores 'jwt:<username>' for JWT-authenticated
requests (app/core/security.py), not just an 8-char API key hint, and username can be
up to 64 chars (users.username). SQLite never enforced the old String(8) limit, so
this went unnoticed until a strict target (MySQL) rejected the data on migration.

Revision ID: 044
Revises: 043
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = '044'
down_revision = '043'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('audit_events') as batch_op:
        batch_op.alter_column('api_key_hint', existing_type=sa.String(8), type_=sa.String(72))


def downgrade():
    with op.batch_alter_table('audit_events') as batch_op:
        batch_op.alter_column('api_key_hint', existing_type=sa.String(72), type_=sa.String(8))
