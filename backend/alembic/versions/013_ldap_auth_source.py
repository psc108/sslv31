"""Add auth_source to users for LDAP support

Revision ID: 013
Revises: 012
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("auth_source", sa.String(16), nullable=False, server_default="local"))
        batch_op.add_column(sa.Column("ldap_dn", sa.String(512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("ldap_dn")
        batch_op.drop_column("auth_source")
