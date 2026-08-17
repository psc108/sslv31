"""FTS5 full-text search for Docs and Bugs (Improvements Plan Stage 11).

Revision ID: 078
Revises: 077

Creates docs_fts / bugs_fts as plain (non external-content) FTS5 virtual
tables, keyed by the real table's `id` (an UNINDEXED column) rather than
relying on FTS5's rowid-mapping external-content mode — Doc/Bug primary
keys are TEXT UUIDs, not INTEGER PRIMARY KEY, so there's no stable rowid
to map external content against. The application maintains these tables
directly (insert/delete alongside every relevant write), and only for the
*current, live* version of each document — mirroring exactly what the old
ILIKE search matched against.

SQLite-only: FTS5 is a SQLite extension with no equivalent on the
Postgres/MySQL backends this app also supports, so every step here is
skipped entirely on those dialects (search falls back to ILIKE there,
same as before this migration).
"""
from alembic import op

revision = '078'
down_revision = '077'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        return

    op.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(id UNINDEXED, name, content)")
    op.execute("CREATE VIRTUAL TABLE IF NOT EXISTS bugs_fts USING fts5(id UNINDEXED, title, description, tags)")

    # Backfill from whatever's already live — only the current (highest
    # version, non-deleted) row per shelf_id+name, matching search_docs'
    # own "latest version only" semantics.
    op.execute("""
        INSERT INTO docs_fts (id, name, content)
        SELECT d.id, d.name, d.content
        FROM docs d
        INNER JOIN (
            SELECT shelf_id, name, MAX(version) AS max_version
            FROM docs
            WHERE deleted_at IS NULL
            GROUP BY shelf_id, name
        ) latest ON d.shelf_id = latest.shelf_id AND d.name = latest.name AND d.version = latest.max_version
        WHERE d.deleted_at IS NULL
    """)
    op.execute("""
        INSERT INTO bugs_fts (id, title, description, tags)
        SELECT id, title, description, tags_json FROM bugs WHERE deleted_at IS NULL
    """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        return
    op.execute("DROP TABLE IF EXISTS bugs_fts")
    op.execute("DROP TABLE IF EXISTS docs_fts")
