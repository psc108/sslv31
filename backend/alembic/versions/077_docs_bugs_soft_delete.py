"""Soft-delete for Docs and Bugs — Trash/restore/purge (Improvements Plan Stage 7).

Revision ID: 077
Revises: 076

Adds a nullable deleted_at column to docs and bugs. NULL means live;
set means "in Trash" until restored or purged (by hand via
DELETE /trash/{id} or by the background retention sweep in
app/services/trash_sweep.py). Two independent add_column calls, no
backfill/drop-column combo — deliberately kept to the low-risk shape that
migration 076 used, after the crash-loop hit twice on multi-step
migrations (074, 075).
"""
from alembic import op
import sqlalchemy as sa

revision = '077'
down_revision = '076'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('docs', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('ix_docs_deleted_at', 'docs', ['deleted_at'])
    op.add_column('bugs', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('ix_bugs_deleted_at', 'bugs', ['deleted_at'])


def downgrade():
    op.drop_index('ix_bugs_deleted_at', table_name='bugs')
    op.drop_column('bugs', 'deleted_at')
    op.drop_index('ix_docs_deleted_at', table_name='docs')
    op.drop_column('docs', 'deleted_at')
