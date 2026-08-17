"""Build Manager Stage 2 — Templates, Environments, Jobs

Revision ID: 022
Revises: 021
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("tags", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("tenant_id", sa.String(36), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_template_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("bm_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("spec", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("change_note", sa.Text, nullable=False, server_default=sa.text('''('Initial version')''')),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_environments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("bm_templates.id"), nullable=False),
        sa.Column("template_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("ip_allocations", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("variables", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("tenant_id", sa.String(36), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("destroyed_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "bm_environment_certs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("environment_id", sa.String(36), sa.ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cert_serial", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("cert_type", sa.String(16), nullable=False, server_default="server"),
        sa.Column("issued_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "bm_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False, server_default="ansible"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("playbook", sa.String(512), nullable=False, server_default=""),
        sa.Column("environment_id", sa.String(36), sa.ForeignKey("bm_environments.id"), nullable=True),
        sa.Column("inventory_filter", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("extra_vars", sa.Text, nullable=False, server_default=sa.text('''('{}')''')),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("tenant_id", sa.String(36), nullable=False,
                  server_default="00000000-0000-0000-0000-000000000001"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bm_job_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("bm_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("stream", sa.String(8), nullable=False, server_default="stdout"),
        sa.Column("line", sa.Text, nullable=False, server_default=sa.text('''('')''')),
    )


def downgrade() -> None:
    op.drop_table("bm_job_logs")
    op.drop_table("bm_jobs")
    op.drop_table("bm_environment_certs")
    op.drop_table("bm_environments")
    op.drop_table("bm_template_versions")
    op.drop_table("bm_templates")
