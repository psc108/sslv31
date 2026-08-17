"""
Data migration tool — copies all rows between any two SQLAlchemy-supported
databases (SQLite, PostgreSQL, MySQL).

Usage:
    python -m app.tools.migrate_db \
        --from sqlite+aiosqlite:///data/certmanager.db \
        --to postgresql+asyncpg://certmanager:secret@localhost:5432/certmanager

    python -m app.tools.migrate_db \
        --from sqlite+aiosqlite:///data/certmanager.db \
        --to mysql+aiomysql://certmanager:secret@localhost:3306/certmanager

This copies all rows from every table in the source database to the target.
The target must already have the schema (run alembic upgrade head first).
"""

import argparse
import asyncio
import sys

from sqlalchemy import MetaData, func, select
from sqlalchemy.ext.asyncio import create_async_engine


async def migrate(source_url: str, target_url: str, *, drop_target: bool = False) -> None:
    src_engine = create_async_engine(source_url, echo=False)
    tgt_engine = create_async_engine(target_url, echo=False)

    meta = MetaData()

    # Reflect source schema
    async with src_engine.connect() as conn:
        await conn.run_sync(meta.reflect)

    # sorted_tables is topologically ordered so parents come before children —
    # required for FK-enforcing targets (MySQL/PostgreSQL); SQLite doesn't
    # enforce FKs by default, so insertion order was never an issue there.
    skip = {"alembic_version"}
    ordered_tables = [t for t in meta.sorted_tables if t.name not in skip]
    table_names = [t.name for t in ordered_tables]

    print(f"Source tables: {table_names}")
    total_rows = 0

    async with tgt_engine.begin() as tgt_conn:
        if drop_target:
            # Delete target tables in reverse FK order (children before parents;
            # dialect-agnostic — avoids Postgres-only TRUNCATE ... CASCADE / quoting)
            for table in reversed(ordered_tables):
                await tgt_conn.execute(table.delete())
                print(f"  Cleared {table.name}")

        for table in ordered_tables:
            name = table.name
            # Read all rows from source
            async with src_engine.connect() as src_conn:
                result = await src_conn.execute(table.select())
                rows = result.mappings().all()

            if not rows:
                print(f"  {name}: 0 rows (skipped)")
                continue

            # Insert into target
            await tgt_conn.execute(table.insert(), [dict(r) for r in rows])
            total_rows += len(rows)
            print(f"  {name}: {len(rows)} rows migrated")

    # Verify counts
    print("\nVerifying...")
    errors = 0
    for name in table_names:
        table = meta.tables[name]
        count_stmt = select(func.count()).select_from(table)
        async with src_engine.connect() as src_conn:
            src_count = (await src_conn.execute(count_stmt)).scalar()
        async with tgt_engine.connect() as tgt_conn:
            tgt_count = (await tgt_conn.execute(count_stmt)).scalar()
        status = "✓" if src_count == tgt_count else "✗ MISMATCH"
        if src_count != tgt_count:
            errors += 1
        if src_count > 0:
            print(f"  {name}: source={src_count} target={tgt_count} {status}")

    await src_engine.dispose()
    await tgt_engine.dispose()

    print(f"\nMigration complete: {total_rows} total rows copied.")
    if errors:
        print(f"WARNING: {errors} table(s) have count mismatches!")
        sys.exit(1)
    else:
        print("All counts verified ✓")


def main():
    parser = argparse.ArgumentParser(description="Migrate CertManager data between databases")
    parser.add_argument("--from", dest="source", required=True, help="Source database URL")
    parser.add_argument("--to", dest="target", required=True, help="Target database URL")
    parser.add_argument("--truncate-target", action="store_true",
                        help="Truncate target tables before copying (DESTRUCTIVE)")
    args = parser.parse_args()

    print(f"Migrating from: {args.source}")
    print(f"Migrating to:   {args.target}")
    print()

    asyncio.run(migrate(args.source, args.target, drop_target=args.truncate_target))


if __name__ == "__main__":
    main()
