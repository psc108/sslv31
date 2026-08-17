"""Stage 3 of the Build Manager hardening plan — FK integrity fixes
(migration 055). Runs a real `alembic upgrade head` against a fresh SQLite
file (same technique as scripts/check_schema_drift.py) since these are DDL
constraint details that Base.metadata.create_all()-based test fixtures don't
exercise — only a real migration run proves the fix.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = str(Path(__file__).resolve().parent.parent)


def _alembic_bin() -> str:
    if found := shutil.which("alembic"):
        return found
    candidate = Path(BACKEND_DIR) / "venv" / "bin" / "alembic"
    return str(candidate) if candidate.exists() else "alembic"


@pytest.fixture(scope="module")
def migrated_db_path():
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    env.setdefault("CERT_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    env.setdefault("API_KEY", "fk-migration-test-placeholder-key")
    result = subprocess.run(
        [_alembic_bin(), "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
    yield db_path
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_bm_jobs_has_exactly_one_fk_on_environment_id_with_set_null(migrated_db_path):
    con = sqlite3.connect(migrated_db_path)
    try:
        rows = con.execute("PRAGMA foreign_key_list(bm_jobs)").fetchall()
    finally:
        con.close()
    env_fks = [r for r in rows if r[2] == "bm_environments"]
    assert len(env_fks) == 1, f"expected exactly one FK on bm_jobs.environment_id, got {env_fks}"
    # PRAGMA foreign_key_list columns: (id, seq, table, from, to, on_update, on_delete, match)
    assert env_fks[0][6] == "SET NULL"


def test_bm_cert_bindings_host_id_has_real_fk_with_set_null(migrated_db_path):
    con = sqlite3.connect(migrated_db_path)
    try:
        rows = con.execute("PRAGMA foreign_key_list(bm_cert_bindings)").fetchall()
    finally:
        con.close()
    host_fks = [r for r in rows if r[2] == "bm_hosts"]
    assert len(host_fks) == 1, f"expected exactly one FK on bm_cert_bindings.host_id, got {host_fks}"
    assert host_fks[0][3] == "host_id"
    assert host_fks[0][6] == "SET NULL"


def test_bm_cert_bindings_environment_id_fk_unaffected(migrated_db_path):
    """The recreate must not disturb the pre-existing, already-correct FK."""
    con = sqlite3.connect(migrated_db_path)
    try:
        rows = con.execute("PRAGMA foreign_key_list(bm_cert_bindings)").fetchall()
    finally:
        con.close()
    env_fks = [r for r in rows if r[2] == "bm_environments"]
    assert len(env_fks) == 1
    assert env_fks[0][6] == "CASCADE"


def test_downgrade_and_reupgrade_is_idempotent(migrated_db_path):
    """Confirm the migration can be reversed and reapplied cleanly."""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{migrated_db_path}"
    env.setdefault("CERT_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    env.setdefault("API_KEY", "fk-migration-test-placeholder-key")

    down = subprocess.run(
        [_alembic_bin(), "downgrade", "-1"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert down.returncode == 0, down.stdout[-3000:] + down.stderr[-3000:]

    up = subprocess.run(
        [_alembic_bin(), "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert up.returncode == 0, up.stdout[-3000:] + up.stderr[-3000:]

    con = sqlite3.connect(migrated_db_path)
    try:
        rows = con.execute("PRAGMA foreign_key_list(bm_jobs)").fetchall()
    finally:
        con.close()
    env_fks = [r for r in rows if r[2] == "bm_environments"]
    assert len(env_fks) == 1
    assert env_fks[0][6] == "SET NULL"
