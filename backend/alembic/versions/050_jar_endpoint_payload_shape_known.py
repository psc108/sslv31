"""add jar_endpoints.payload_shape_known — Stage 5 of the dissection accuracy
plan. False when the return/request type is a generic container whose element
type is erased at the bytecode level (JVMS generic erasure — the method
descriptor for ResponseEntity<CustomerDto> and ResponseEntity<?> is identical),
a raw Object, or an unresolvable external type. Makes the boundary of what
this tool can actually know visible instead of reporting every endpoint as
equally well-characterised.

Revision ID: 050
Revises: 049
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '050'
down_revision = '049'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('jar_endpoints', sa.Column('payload_shape_known', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('jar_endpoints', 'payload_shape_known')
