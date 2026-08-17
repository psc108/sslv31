"""add polymorphic columns to jar_dto_schemas + jar_config_examples table

Revision ID: 070
Revises: 069
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '070'
down_revision = '069'
branch_labels = None
depends_on = None

_long_text = sa.Text().with_variant(mysql.LONGTEXT(), 'mysql')


def upgrade():
    with op.batch_alter_table("jar_dto_schemas") as batch_op:
        batch_op.add_column(sa.Column("polymorphic_base", sa.String(512), nullable=True))
        batch_op.add_column(sa.Column("discriminator_value", sa.String(128), nullable=True))

    op.create_table(
        'jar_config_examples',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('root_class_name', sa.String(512), nullable=False),
        sa.Column('format', sa.String(16), nullable=False, server_default='yaml'),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('content', _long_text, nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('jar_config_examples')
    with op.batch_alter_table("jar_dto_schemas") as batch_op:
        batch_op.drop_column("discriminator_value")
        batch_op.drop_column("polymorphic_base")
