"""033 jar dto schemas

Revision ID: 033
Revises: 032
Create Date: 2025-01-01

"""
from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jar_dto_schemas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sub_report_id", sa.String(36),
                  sa.ForeignKey("sub_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_name", sa.String(512), nullable=False),
        sa.Column("simple_name", sa.String(256), nullable=False),
        sa.Column("is_enum", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_lombok", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("source_note", sa.String(512), nullable=True),
        sa.Column("enum_values_json", sa.Text, nullable=True),
        sa.Column("fields_json", sa.Text, nullable=True),
    )
    op.create_index("ix_jar_dto_schemas_class_name", "jar_dto_schemas", ["class_name"])
    op.create_index("ix_jar_dto_schemas_sub_report_id", "jar_dto_schemas", ["sub_report_id"])


def downgrade() -> None:
    op.drop_index("ix_jar_dto_schemas_sub_report_id", "jar_dto_schemas")
    op.drop_index("ix_jar_dto_schemas_class_name", "jar_dto_schemas")
    op.drop_table("jar_dto_schemas")
