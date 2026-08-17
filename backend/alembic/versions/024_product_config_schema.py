"""Build Manager — Product config_schema

Revision ID: 024
Revises: 023
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bm_product_versions", sa.Column("config_schema", sa.Text, nullable=False, server_default=sa.text('''('[]')''')))


def downgrade() -> None:
    op.drop_column("bm_product_versions", "config_schema")
