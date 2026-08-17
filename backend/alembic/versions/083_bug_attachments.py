"""Bug attachments — Improvements Plan Stage 18. Metadata for files
(screenshots, logs) attached directly to a bug; the actual bytes live on
disk under settings.DATA_DIR / "bug_attachments", not in the database.

Revision ID: 083
Revises: 082
"""
from alembic import op
import sqlalchemy as sa

revision = '083'
down_revision = '082'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bug_attachments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('bug_id', sa.String(36), sa.ForeignKey('bugs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('stored_path', sa.String(1024), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('content_type', sa.String(128), nullable=True),
        sa.Column('uploaded_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_bug_attachments_bug_id', 'bug_attachments', ['bug_id'])


def downgrade():
    op.drop_index('ix_bug_attachments_bug_id', table_name='bug_attachments')
    op.drop_table('bug_attachments')
