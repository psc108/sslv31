"""Config editor file registry."""

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_config_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("path", sa.String(512), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="system"),
        sa.Column("format", sa.String(16), nullable=False, server_default="yaml"),
        sa.Column("purpose", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("editable", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_modified_by", sa.String(128), nullable=False, server_default=""),
        sa.Column("last_modified_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bm_config_files")
