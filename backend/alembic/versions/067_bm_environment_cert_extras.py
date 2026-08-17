"""bm_environment_cert_extras

Revision ID: 067
Revises: 066
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("bm_environment_certs") as batch_op:
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("san_dns", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("san_ip", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("bm_environment_certs") as batch_op:
        batch_op.drop_column("san_ip")
        batch_op.drop_column("san_dns")
        batch_op.drop_column("expires_at")
