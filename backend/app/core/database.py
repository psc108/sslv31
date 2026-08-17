from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _build_engine():
    """Create async engine with appropriate settings for SQLite, PostgreSQL, or MySQL."""
    url = settings.db_url

    if settings.is_postgres:
        # PostgreSQL with connection pooling
        connect_args = {
            "statement_cache_size": 0,
        }
        if settings.DB_STATEMENT_TIMEOUT:
            connect_args["command_timeout"] = settings.DB_STATEMENT_TIMEOUT / 1000

        return create_async_engine(
            url,
            echo=False,
            future=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    elif settings.is_mysql:
        # MySQL/RDS — connection pooling, recycled below server wait_timeout to
        # avoid "MySQL server has gone away" on connections the server has dropped.
        return create_async_engine(
            url,
            echo=False,
            future=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"charset": "utf8mb4"},
        )
    else:
        # SQLite — no pooling needed, but WAL mode + a busy timeout are
        # essential for any real concurrency. Background jobs (analysis,
        # decompile — which commits incrementally, once per jar) write from a
        # different task than request handlers read from; without these,
        # SQLite's default rollback-journal mode locks the whole file on any
        # write, and a connection that hits that lock fails immediately with
        # "sqlite3.OperationalError: database is locked" instead of waiting
        # — confirmed live in the logs during concurrent decompile/analysis
        # activity. WAL mode lets readers keep working while a write is in
        # progress; the busy timeout makes a genuinely-contended connection
        # wait and retry instead of failing outright.
        sqlite_engine = create_async_engine(
            url,
            echo=False,
            future=True,
            connect_args={"timeout": 30},
        )

        @event.listens_for(sqlite_engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return sqlite_engine


engine = _build_engine()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Ensure DATA_DIR subdirectories exist."""
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.self_cert_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
