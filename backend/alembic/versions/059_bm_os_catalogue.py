"""Build Manager Enhancement Plan, Stage 6 — Operating System Catalogue.

Mirrors BMProduct/BMProductVersion's two-level shape. Right now OS handling
is hardcoded in three places (BMTemplateBuilderPage's 4-tile grid,
InventoryPage's OS_TYPES array, HostCreate.os_type's backend regex) with no
shared source of truth and no way for an admin to add their own OS. This adds
the real, seedable, CRUD-able catalogue backing all three.

Revision ID: 059
Revises: 058
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '059'
down_revision = '058'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bm_os_families',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False, unique=True),
        sa.Column('display_name', sa.String(128), nullable=False),
        sa.Column('icon', sa.String(8), nullable=False, server_default='🐧'),
        sa.Column('origin', sa.String(16), nullable=False, server_default='user'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        'bm_os_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('os_family_id', sa.String(36), sa.ForeignKey('bm_os_families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('display_name', sa.String(64), nullable=False),
        sa.Column('eol_date', sa.String(16), nullable=True),
        sa.Column('is_latest', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('bm_os_versions')
    op.drop_table('bm_os_families')
