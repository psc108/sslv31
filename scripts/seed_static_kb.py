"""Seed the 40 built-in JAR Analyser error-KB articles (error_kb.KB) into the
jar_kb_entries table as origin='builtin' rows, so they become DB-managed
(editable/deletable via the UI) instead of living only as Python source.

Idempotent — skips any id already present, so it's safe to re-run after a
partial run or to pick up newly added static entries later.

Run on the server (or via `docker exec ... python /opt/certmanager/scripts/seed_static_kb.py`):
    python3 scripts/seed_static_kb.py
"""
import json
import sys
sys.path.insert(0, "/opt/certmanager/backend")

import asyncio
from sqlalchemy import select
from app.core.database import async_session
from app.models.jar_analyser import JarKbEntry
from app.services.jar_analyser.error_kb import KB


async def main():
    async with async_session() as db:
        existing_ids = set(
            (await db.execute(select(JarKbEntry.id))).scalars().all()
        )

        inserted = 0
        for entry in KB:
            if entry["id"] in existing_ids:
                continue
            db.add(JarKbEntry(
                id=entry["id"],
                category=entry["category"],
                severity=entry["severity"],
                pattern=entry["pattern"],
                title=entry["title"],
                plain_english=entry["plain_english"],
                causes_json=json.dumps(entry["causes"]),
                fix_steps_json=json.dumps(entry["fix_steps"]),
                see_also_json=json.dumps(entry["see_also"]),
                origin="builtin",
                created_by=None,
            ))
            inserted += 1
            print(f"  seeded {entry['id']}: {entry['title']}")

        await db.commit()
        print(f"\nDone — seeded {inserted} new builtin entries "
              f"({len(existing_ids)} already present, {len(KB)} total in error_kb.KB).")


if __name__ == "__main__":
    asyncio.run(main())
