"""add developer-authored doc fields from @Operation/@Schema — Stage 4 of the
dissection accuracy plan. These are extracted annotation element values
(survive compilation, unlike Javadoc/comments), kept explicitly distinct from
any inferred content: jar_endpoints.doc_summary/doc_description from
@Operation(summary=..., description=...), jar_dto_schemas.description from
@Schema(description=...) on the class (field-level descriptions live inside
the existing fields_json blob).

Revision ID: 049
Revises: 048
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '049'
down_revision = '048'
branch_labels = None
depends_on = None

_LONGTEXT_ON_MYSQL = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade():
    op.add_column('jar_endpoints', sa.Column('doc_summary', _LONGTEXT_ON_MYSQL, nullable=True))
    op.add_column('jar_endpoints', sa.Column('doc_description', _LONGTEXT_ON_MYSQL, nullable=True))
    op.add_column('jar_dto_schemas', sa.Column('description', _LONGTEXT_ON_MYSQL, nullable=True))


def downgrade():
    op.drop_column('jar_dto_schemas', 'description')
    op.drop_column('jar_endpoints', 'doc_description')
    op.drop_column('jar_endpoints', 'doc_summary')
