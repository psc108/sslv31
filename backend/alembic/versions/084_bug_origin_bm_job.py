"""Generalize a bug's origin beyond JAR Analyser — Improvements Plan
Stage 19. Adds a second, independent origin (bugs.bm_job_id, a Build
Manager job) alongside the existing report_id/sub_report_id, and the same
on bug_occurrences. bug_occurrences.report_id becomes nullable so an
occurrence can point at a job instead of a report — every occurrence still
points at exactly one of the two, enforced at the API layer, not by a DB
constraint (SQLite has no portable CHECK-across-nullable-FKs story that's
worth the complexity here).

SQLite note: a first attempt at this migration used a plain op.add_column()
with an inline sa.ForeignKey() for bugs.bm_job_id — this raised
"NotImplementedError: No support for ALTER of constraints in SQLite
dialect" partway through (the bare column add auto-committed since SQLite
DDL here is non-transactional, but the FK-constraint half of the same
add_column() call failed and aborted the migration before alembic_version
was bumped), leaving a real, orphaned, unconstrained bm_job_id column on a
live database whose alembic_version still read 083. Recovered by manually
dropping that column (SQLite 3.35+ supports plain DROP COLUMN) before
re-running this corrected version, which uses batch_alter_table
consistently for both tables — the same documented workaround migration
055 already established for adding an SQLite FK constraint. A second
attempt using batch mode with an inline sa.ForeignKey() on the new column
then hit "ValueError: Constraint must have a name" — batch mode's
recreate-the-table strategy needs every constraint named, unlike a plain
add_column(); fixed by adding the column bare and following it with an
explicit, named batch_op.create_foreign_key() call, matching migration
055's exact working shape.

Revision ID: 084
Revises: 083
"""
from alembic import op
import sqlalchemy as sa

revision = '084'
down_revision = '083'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bugs', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('bm_job_id', sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            'fk_bugs_bm_job_id', 'bm_jobs', ['bm_job_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index('ix_bugs_bm_job_id', 'bugs', ['bm_job_id'])

    with op.batch_alter_table('bug_occurrences', recreate='always') as batch_op:
        batch_op.alter_column('report_id', existing_type=sa.String(36), nullable=True)
        batch_op.add_column(sa.Column('bm_job_id', sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            'fk_bug_occurrences_bm_job_id', 'bm_jobs', ['bm_job_id'], ['id'], ondelete='CASCADE',
        )
    op.create_index('ix_bug_occurrences_bm_job_id', 'bug_occurrences', ['bm_job_id'])


def downgrade():
    op.drop_index('ix_bug_occurrences_bm_job_id', table_name='bug_occurrences')
    with op.batch_alter_table('bug_occurrences', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_bug_occurrences_bm_job_id', type_='foreignkey')
        batch_op.drop_column('bm_job_id')
        batch_op.alter_column('report_id', existing_type=sa.String(36), nullable=False)

    op.drop_index('ix_bugs_bm_job_id', table_name='bugs')
    with op.batch_alter_table('bugs', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_bugs_bm_job_id', type_='foreignkey')
        batch_op.drop_column('bm_job_id')
