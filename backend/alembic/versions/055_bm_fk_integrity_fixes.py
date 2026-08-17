"""Build Manager Hardening Plan, Stage 3 — data integrity fixes.

Two real gaps found by comparing every FK in app/models/build_manager.py
against the migration that actually created it (021-031 build-manager
migrations) — this comparison found these two as the only genuine drift;
every other FK in the module already matches its model exactly:

1. bm_jobs.environment_id — the model declares ondelete="SET NULL"
   (models/build_manager.py) but migration 022_build_manager_stage2.py
   created the FK with no ondelete clause at all, so the live database does
   not actually behave the way the ORM promises (jobs would fail to delete
   their parent environment, or leave a dangling reference, depending on
   dialect defaults, instead of the intended "job survives, nulled out, for
   audit trail purposes").

2. bm_cert_bindings.host_id — not a real foreign key at all in either the
   model or the migration, just a bare nullable String(36) column. No
   referential integrity is enforced between a cert binding and the host
   it's supposedly bound to. Added as ondelete="SET NULL", matching the
   column's existing nullable design (a binding should survive its host
   being removed, just lose the specific host reference).

SQLite note: the original bm_jobs FK (from migration 022) was created
inline via sa.ForeignKey() with no explicit name, and SQLite's own schema
storage has no concept of a named FK constraint to reflect back — a first
attempt at this migration that looked up the "existing constraint name" via
sa.inspect() and dropped it by that name silently found nothing (name was
None) and produced a *second*, duplicate FK on the recreated table instead
of replacing the first — caught by testing against a fresh database before
this ever reached a real deployment. The fix is a `naming_convention` passed
to `batch_alter_table`, Alembic's documented mechanism for referencing an
otherwise-unnamed reflected constraint deterministically.

Revision ID: 055
Revises: 054
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = '055'
down_revision = '054'
branch_labels = None
depends_on = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade():
    with op.batch_alter_table("bm_jobs", recreate="always", naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_bm_jobs_environment_id_bm_environments"), type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_bm_jobs_environment_id", "bm_environments", ["environment_id"], ["id"], ondelete="SET NULL",
        )

    with op.batch_alter_table("bm_cert_bindings", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            "fk_bm_cert_bindings_host_id", "bm_hosts", ["host_id"], ["id"], ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("bm_cert_bindings", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_bm_cert_bindings_host_id", type_="foreignkey")

    with op.batch_alter_table("bm_jobs", recreate="always", naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_bm_jobs_environment_id", type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f("fk_bm_jobs_environment_id_bm_environments"),
            "bm_environments", ["environment_id"], ["id"],
        )
