"""build manager secrets

Revision ID: 028
Revises: 027
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_secrets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("value_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="custom"),
        sa.Column("linked_service", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("rotated_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bm_secrets_category", "bm_secrets", ["category"])
    op.create_index("ix_bm_secrets_linked_service", "bm_secrets", ["linked_service"])


def downgrade() -> None:
    op.drop_index("ix_bm_secrets_linked_service", table_name="bm_secrets")
    op.drop_index("ix_bm_secrets_category", table_name="bm_secrets")
    op.drop_table("bm_secrets")
