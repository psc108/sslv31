"""infra diagnostic runs — make report_id nullable, add run_label and report_data

Revision ID: 042
Revises: 041
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '042'
down_revision = '041'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jar_diagnostic_runs') as batch_op:
        # Make report_id nullable so infra runs don't require a parent JAR report
        batch_op.alter_column('report_id', existing_type=sa.String(36), nullable=True)
        batch_op.add_column(sa.Column('run_label', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('report_data', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('jar_diagnostic_runs') as batch_op:
        batch_op.drop_column('report_data')
        batch_op.drop_column('run_label')
        batch_op.alter_column('report_id', existing_type=sa.String(36), nullable=False)
