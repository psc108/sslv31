"""Multi-tenancy: tenants table, memberships, and tenant_id on all models.

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

# Default tenant ID (deterministic for all environments)
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # 1. Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # 2. Create user-tenant membership table
    op.create_table(
        "user_tenant_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_role", sa.String(16), nullable=True),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    # 3. Insert default tenant
    op.execute(
        f"INSERT INTO tenants (id, name, slug, description) "
        f"VALUES ('{DEFAULT_TENANT_ID}', 'Default', 'default', 'Default tenant for backward compatibility')"
    )

    # 4. Add tenant_id to all existing tables (nullable first, then backfill, then set NOT NULL)
    tables_to_update = [
        "certificate_authorities",
        "certificates",
        "certificate_signing_requests",
        "truststores",
        "audit_events",
        "api_keys",
        "pending_requests",
    ]

    for table in tables_to_update:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.execute(f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT_ID}'")

        # SQLite doesn't support ALTER COLUMN, so we leave nullable=True
        # The application enforces NOT NULL via defaults
        try:
            op.alter_column(table, "tenant_id", nullable=False)
        except Exception:
            pass  # SQLite limitation — column stays nullable but always populated

    # 5. Add tenant_id index on key tables
    for table in ["certificate_authorities", "certificates", "audit_events"]:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # 6. Assign all existing users to default tenant
    # (built with Python-generated UUIDs rather than SQLite-only randomblob()/hex()
    # so this backfill is portable across SQLite/PostgreSQL/MySQL)
    import uuid

    conn = op.get_bind()
    user_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM users")).fetchall()]
    if user_ids:
        conn.execute(
            sa.text(
                "INSERT INTO user_tenant_memberships (id, user_id, tenant_id) "
                "VALUES (:id, :user_id, :tenant_id)"
            ),
            [
                {"id": str(uuid.uuid4()), "user_id": uid, "tenant_id": DEFAULT_TENANT_ID}
                for uid in user_ids
            ],
        )


def downgrade() -> None:
    tables_to_update = [
        "certificate_authorities",
        "certificates",
        "certificate_signing_requests",
        "truststores",
        "audit_events",
        "api_keys",
        "pending_requests",
    ]

    for table in tables_to_update:
        try:
            op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        except Exception:
            pass
        op.drop_column(table, "tenant_id")

    op.drop_table("user_tenant_memberships")
    op.drop_table("tenants")
