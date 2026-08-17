"""015 — Certificate Transparency log tables.

Revision ID: 015
Revises: 014
"""

revision = "015"
down_revision = "014"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "ct_log_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("log_index", sa.Integer, nullable=False, unique=True),
        sa.Column("cert_serial", sa.String(64), nullable=False),
        sa.Column("cert_der_hash", sa.String(64), nullable=False),
        sa.Column("issuer_ca_id", sa.String(36), nullable=True),
        sa.Column("subject_cn", sa.String(256), nullable=False, server_default=""),
        sa.Column("san_json", sa.Text, nullable=False, server_default=sa.text('''('[]')''')),
        sa.Column("leaf_hash", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("sct_json", sa.Text, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ct_log_entries_cert_serial", "ct_log_entries", ["cert_serial"])
    op.create_index("ix_ct_log_subject_cn", "ct_log_entries", ["subject_cn"])
    op.create_index("ix_ct_log_timestamp", "ct_log_entries", ["timestamp"])
    op.create_index("ix_ct_log_tenant", "ct_log_entries", ["tenant_id"])

    op.create_table(
        "ct_tree_heads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tree_size", sa.Integer, nullable=False),
        sa.Column("root_hash", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("signature", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ct_tree_heads")
    op.drop_index("ix_ct_log_tenant", table_name="ct_log_entries")
    op.drop_index("ix_ct_log_timestamp", table_name="ct_log_entries")
    op.drop_index("ix_ct_log_subject_cn", table_name="ct_log_entries")
    op.drop_index("ix_ct_log_entries_cert_serial", table_name="ct_log_entries")
    op.drop_table("ct_log_entries")
