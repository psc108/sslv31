"""Docs feature — doc_libraries, doc_shelves, docs, doc_annotations tables.

Revision ID: 072
Revises: 071
Create Date: 2026-08-10

Stage 1 of the DocApp-in-LabTool plan (see Documentation/planning). Library
is a level added deliberately here beyond what DocApp's own source has (its
local-mode data model is flat Shelf -> Document only).
"""
from alembic import op
import sqlalchemy as sa

revision = '072'
down_revision = '071'
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    op.create_table(
        'doc_libraries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False,
                   server_default=DEFAULT_TENANT_ID),
        sa.Column('created_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_doc_libraries_tenant_id', 'doc_libraries', ['tenant_id'])

    op.create_table(
        'doc_shelves',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('library_id', sa.String(36), sa.ForeignKey('doc_libraries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False,
                   server_default=DEFAULT_TENANT_ID),
        sa.Column('created_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_doc_shelves_tenant_id', 'doc_shelves', ['tenant_id'])

    op.create_table(
        'docs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('shelf_id', sa.String(36), sa.ForeignKey('doc_shelves.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False,
                   server_default=DEFAULT_TENANT_ID),
        sa.Column('created_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('shelf_id', 'name', 'version', name='uq_doc_shelf_name_version'),
    )
    op.create_index('ix_docs_shelf_id', 'docs', ['shelf_id'])
    op.create_index('ix_docs_tenant_id', 'docs', ['tenant_id'])

    op.create_table(
        'doc_annotations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('doc_id', sa.String(36), sa.ForeignKey('docs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('color', sa.String(16), nullable=False, server_default='yellow'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('prefix', sa.String(64), nullable=True),
        sa.Column('suffix', sa.String(64), nullable=True),
        sa.Column('created_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_doc_annotations_doc_id', 'doc_annotations', ['doc_id'])


def downgrade():
    op.drop_table('doc_annotations')
    op.drop_index('ix_docs_tenant_id', table_name='docs')
    op.drop_index('ix_docs_shelf_id', table_name='docs')
    op.drop_table('docs')
    op.drop_index('ix_doc_shelves_tenant_id', table_name='doc_shelves')
    op.drop_table('doc_shelves')
    op.drop_index('ix_doc_libraries_tenant_id', table_name='doc_libraries')
    op.drop_table('doc_libraries')
