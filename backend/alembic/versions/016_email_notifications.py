"""Email notifications

Revision ID: 016
Revises: 015
"""
revision = "016"
down_revision = "015"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean, default=True),
        sa.Column("filter_ca_id", sa.String(36), nullable=True),
        sa.Column("filter_tag", sa.String(64), nullable=True),
        sa.Column("digest_mode", sa.Boolean, default=False),
        sa.Column("mandatory", sa.Boolean, default=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "notification_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("sent", sa.Boolean, default=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, server_default="00000000-0000-0000-0000-000000000001"),
    )


def downgrade() -> None:
    op.drop_table("notification_queue")
    op.drop_table("notification_preferences")
