import asyncio
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment before importing app
os.environ["CERT_MASTER_KEY"] = Fernet.generate_key().decode()
os.environ["API_KEY"] = "test-api-key-for-smoke-tests-12345"
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = os.path.join(os.environ["DATA_DIR"], "backups")
os.environ["LOG_FILE"] = "/dev/null"

from app.main import app
from app.core.database import engine, get_db
from app.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def setup_db():
    """Create all tables for testing.

    docs_fts/bugs_fts (migration 078) are SQLite FTS5 virtual tables, not
    declarative models — Base.metadata.create_all() doesn't know about them
    since they were never mapped as an app.models class. Any test that hits
    a docs.py/bug_tracker.py write path (create/save/delete/restore — they
    all call _fts_index_*/_fts_unindex_*) crashes with "no such table" on a
    fresh test DB without these, so create them here the same way the
    migration does rather than requiring every such test to know about it."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(id UNINDEXED, name, content)")
            await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS bugs_fts USING fts5(id UNINDEXED, title, description, tags)")
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(setup_db) -> AsyncClient:
    """HTTP test client with API key auth header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers["X-API-Key"] = os.environ["API_KEY"]
        yield ac


@pytest_asyncio.fixture
async def client_no_auth(setup_db) -> AsyncClient:
    """HTTP test client without auth."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
