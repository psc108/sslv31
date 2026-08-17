"""Build Manager — AWS catalogue fields: deployment_targets on BMProduct, aws_defaults on BMProductVersion

Revision ID: 066
Revises: 065
"""
from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bm_products",
        sa.Column("deployment_targets", sa.Text, nullable=False, server_default='["ec2"]'))
    op.add_column("bm_product_versions",
        sa.Column("aws_defaults", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("bm_products", "deployment_targets")
    op.drop_column("bm_product_versions", "aws_defaults")
