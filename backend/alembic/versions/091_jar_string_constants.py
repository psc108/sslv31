"""JAR Analyser string-constant search — free-text search for log
messages/literals across every analysed jar, so "which service logs this
message" is answerable without having already decompiled every class by
hand (bug tracker triage request: analysing a JAR with only structured
facts today, no way to grep the actual strings a class embeds).

`jar_string_constants` — one row per string literal resolved from a
class's own bytecode constant pool (see classfile.py's new
`_string_constants()`), populated automatically during analysis
(job.py/persistence.py), not opt-in like decompilation.

`jar_strings_fts` — SQLite FTS5 virtual table over `value` only, same
"plain (non external-content) table keyed by an UNINDEXED id" shape as
migration 078's docs_fts/bugs_fts, for the same reason (TEXT UUID primary
key, no stable rowid to map external-content mode against). No backfill
needed here (unlike 078) since there's no pre-existing data — string
constants didn't exist before this feature.

Revision ID: 091
Revises: 090
"""
from alembic import op
import sqlalchemy as sa

revision = '091'
down_revision = '090'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jar_string_constants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sub_report_id', sa.String(36), sa.ForeignKey('sub_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('class_name', sa.String(512), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
    )
    op.create_index('ix_jar_string_constants_sub_report_id', 'jar_string_constants', ['sub_report_id'])
    op.create_index('ix_jar_string_constants_class_name', 'jar_string_constants', ['class_name'])

    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        return
    op.execute("CREATE VIRTUAL TABLE IF NOT EXISTS jar_strings_fts USING fts5(id UNINDEXED, value)")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.execute("DROP TABLE IF EXISTS jar_strings_fts")
    op.drop_index('ix_jar_string_constants_class_name', table_name='jar_string_constants')
    op.drop_index('ix_jar_string_constants_sub_report_id', table_name='jar_string_constants')
    op.drop_table('jar_string_constants')
