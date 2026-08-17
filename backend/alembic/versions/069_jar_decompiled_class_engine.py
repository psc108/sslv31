"""add engine column to jar_decompiled_classes

Revision ID: 069
Revises: 068
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = '069'
down_revision = '068'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jar_decompiled_classes") as batch_op:
        # server_default so existing rows (all produced by CFR, before
        # Vineflower was added as a second engine) are correctly attributed
        # with no separate backfill step needed.
        batch_op.add_column(sa.Column("engine", sa.String(16), nullable=False, server_default="cfr"))


def downgrade():
    with op.batch_alter_table("jar_decompiled_classes") as batch_op:
        batch_op.drop_column("engine")
