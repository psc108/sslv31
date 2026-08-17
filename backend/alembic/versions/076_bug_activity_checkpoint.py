"""Bug activity checkpoint — backs the in-app "N bugs need your attention" badge.

Revision ID: 076
Revises: 075

Stage 5 of the Docs & Bug Tracker Improvements Plan (see
Documentation/planning/docs_bugtracker_improvements_plan.md). One row per
user recording the last time they checked their bugs; activity after that
timestamp on a bug they're assigned to or reported, not caused by
themselves, counts as unseen.
"""
from alembic import op
import sqlalchemy as sa

revision = '076'
down_revision = '075'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bug_activity_checkpoints',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('bug_activity_checkpoints')
