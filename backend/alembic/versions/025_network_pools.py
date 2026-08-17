"""Build Manager — Network pools

Revision ID: 025
Revises: 024
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_network_pools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("cidr", sa.String(45), nullable=False),
        sa.Column("gateway", sa.String(45), nullable=False, server_default=""),
        sa.Column("dns_servers", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("reserved", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bm_network_pools")
