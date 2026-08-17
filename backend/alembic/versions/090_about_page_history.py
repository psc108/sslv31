"""About page history - backup snapshots + structured version changelog.

Two additions on top of migration 089's single about_page row:

- `about_page.last_versions_json`: a flat {package_key: version} JSON
  snapshot from the most recent Regenerate, used to diff against on the
  *next* Regenerate to compute what changed. Plain nullable add_column, no
  FK, no batch mode needed.
- `about_page_versions`: a full-content snapshot archived immediately
  before every overwrite (manual edit or regenerate) - the "backup before
  it changes" safety net.
- `about_version_changes`: one row per detected package version change,
  populated only by Regenerate - "package X: 1.2.3 -> 1.3.0" style
  structured history, the same from/to shape jar_diff_reports already
  uses for JAR Analyser's own dependency diffs.

Neither new table has a foreign key back to about_page (it's a single
fixed row keyed by a literal "global" id, not worth a formal FK for), so
both are plain create_table calls - no batch mode dance required, same
reasoning migration 086's own docstring gives for bm_settings.

Revision ID: 090
Revises: 089
"""
from alembic import op
import sqlalchemy as sa

revision = '090'
down_revision = '089'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('about_page', sa.Column('last_versions_json', sa.Text(), nullable=True))

    op.create_table(
        'about_page_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('updated_by', sa.String(128), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
    )

    op.create_table(
        'about_version_changes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('package_key', sa.String(64), nullable=False),
        sa.Column('display_name', sa.String(128), nullable=False),
        sa.Column('old_version', sa.String(64), nullable=True),
        sa.Column('new_version', sa.String(64), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_about_version_changes_package_key', 'about_version_changes', ['package_key'])
    op.create_index('ix_about_version_changes_detected_at', 'about_version_changes', ['detected_at'])


def downgrade():
    op.drop_index('ix_about_version_changes_detected_at', table_name='about_version_changes')
    op.drop_index('ix_about_version_changes_package_key', table_name='about_version_changes')
    op.drop_table('about_version_changes')
    op.drop_table('about_page_versions')
    op.drop_column('about_page', 'last_versions_json')
