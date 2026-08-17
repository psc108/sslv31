"""Build Manager Stage 4 — Product Catalogue

Revision ID: 023
Revises: 022
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="utility"),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("icon", sa.String(8), nullable=False, server_default="📦"),
        sa.Column("default_ports", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("cert_requirements", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("dependencies", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_product_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("bm_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("ansible_role", sa.String(128), nullable=False, server_default=""),
        sa.Column("default_vars", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("supported_os", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("conflicts_with", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("requires", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("release_date", sa.String(16), nullable=True),
        sa.Column("eol_date", sa.String(16), nullable=True),
        sa.Column("is_latest", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_product_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("environment_id", sa.String(36), sa.ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_role", sa.String(128), nullable=False),
        sa.Column("product_version_id", sa.String(36), sa.ForeignKey("bm_product_versions.id"), nullable=False),
        sa.Column("config_vars", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("installed_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("bm_product_configs")
    op.drop_table("bm_product_versions")
    op.drop_table("bm_products")
