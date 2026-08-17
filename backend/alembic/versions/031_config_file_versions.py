"""Config editor file versions."""

from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bm_config_file_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("bm_config_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("diff_patch", sa.Text, nullable=False, server_default=sa.text('''('')''')),
        sa.Column("edited_by", sa.String(128), nullable=False),
        sa.Column("edited_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("comment", sa.String(512), nullable=False, server_default=""),
    )
    op.create_index("ix_bm_cfv_file_version", "bm_config_file_versions", ["file_id", "version"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_bm_cfv_file_version", table_name="bm_config_file_versions")
    op.drop_table("bm_config_file_versions")
