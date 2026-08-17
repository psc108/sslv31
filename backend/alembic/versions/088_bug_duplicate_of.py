"""Bug-to-bug duplicate linking.

Adds bugs.duplicate_of_bug_id — a self-referential nullable FK, set when a
bug is explicitly marked as a duplicate of another already-independently-
filed bug (see bug_tracker.py's mark_duplicate endpoint). Distinct from the
existing BugOccurrence mechanism, which links one bug to an *additional
report/job* it was also seen on, not to another Bug row.

Uses the same batch_alter_table + named create_foreign_key shape migration
084 established as the working pattern for adding an FK column on SQLite
(a plain add_column() with an inline sa.ForeignKey() fails there).

Revision ID: 088
Revises: 087
"""
from alembic import op
import sqlalchemy as sa

revision = '088'
down_revision = '087'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bugs', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('duplicate_of_bug_id', sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            'fk_bugs_duplicate_of_bug_id', 'bugs', ['duplicate_of_bug_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index('ix_bugs_duplicate_of_bug_id', 'bugs', ['duplicate_of_bug_id'])


def downgrade():
    op.drop_index('ix_bugs_duplicate_of_bug_id', table_name='bugs')
    with op.batch_alter_table('bugs', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_bugs_duplicate_of_bug_id', type_='foreignkey')
        batch_op.drop_column('duplicate_of_bug_id')
