"""Bug assignee becomes a real user reference — assignee_id replaces assignee.

Revision ID: 075
Revises: 074

Stage 4 of the Docs & Bug Tracker Improvements Plan (see
Documentation/planning/docs_bugtracker_improvements_plan.md). assignee was
a free-text string with no link to a real account, so there was no way to
reliably filter "bugs assigned to me." Replaced with a real FK to users.id
(same precedent as notification.py's user_id columns) — a clean swap, not
a parallel column, since this is an actively-developed internal feature
with no external consumers depending on the old string shape. Best-effort
backfill matches any existing free-text value against a real username
before the old column is dropped; anything that doesn't match a real user
is simply left unassigned (assignee_id null) rather than lost silently —
it was never a real account reference to begin with.
"""
from alembic import op
import sqlalchemy as sa

revision = '075'
down_revision = '074'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bugs', sa.Column(
        'assignee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
    ))
    op.execute(
        "UPDATE bugs SET assignee_id = (SELECT users.id FROM users WHERE users.username = bugs.assignee) "
        "WHERE bugs.assignee IS NOT NULL"
    )
    op.create_index('ix_bugs_assignee_id', 'bugs', ['assignee_id'])
    op.drop_column('bugs', 'assignee')


def downgrade():
    op.add_column('bugs', sa.Column('assignee', sa.String(256), nullable=True))
    op.execute(
        "UPDATE bugs SET assignee = (SELECT users.username FROM users WHERE users.id = bugs.assignee_id) "
        "WHERE bugs.assignee_id IS NOT NULL"
    )
    op.drop_index('ix_bugs_assignee_id', table_name='bugs')
    op.drop_column('bugs', 'assignee_id')
