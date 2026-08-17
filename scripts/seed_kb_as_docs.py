"""Seed error_kb.KB entries into the Docs table as proper KB docs.

Idempotent — skips any doc whose title already exists in the same shelf.
Runs automatically from entrypoint.sh after migrations on every container start.
"""
import asyncio
import json
import sys
import uuid

sys.path.insert(0, "/opt/certmanager")

from sqlalchemy import select
from app.core.database import async_session
from app.models.docs import Doc, DocLibrary, DocShelf
from app.services.docs_error_kb import render_kb_doc_content
from app.services.jar_analyser.error_kb import KB

TENANT_ID = "global"


async def main() -> None:
    async with async_session() as db:
        # Build title → doc lookup for idempotency check
        existing_titles: set[str] = set(
            (await db.execute(select(Doc.name).where(Doc.deleted_at.is_(None)))).scalars().all()
        )

        # Cache library and shelf objects by name
        lib_cache: dict[str, DocLibrary] = {}
        shelf_cache: dict[str, DocShelf] = {}

        async def get_or_create_library(name: str) -> DocLibrary:
            if name in lib_cache:
                return lib_cache[name]
            row = (await db.execute(
                select(DocLibrary).where(DocLibrary.name == name)
            )).scalar_one_or_none()
            if row is None:
                row = DocLibrary(id=str(uuid.uuid4()), name=name, tenant_id=TENANT_ID)
                db.add(row)
                await db.flush()
            lib_cache[name] = row
            return row

        async def get_or_create_shelf(lib: DocLibrary, name: str) -> DocShelf:
            key = f"{lib.id}:{name}"
            if key in shelf_cache:
                return shelf_cache[key]
            row = (await db.execute(
                select(DocShelf).where(DocShelf.library_id == lib.id, DocShelf.name == name)
            )).scalar_one_or_none()
            if row is None:
                row = DocShelf(id=str(uuid.uuid4()), name=name, library_id=lib.id, tenant_id=TENANT_ID)
                db.add(row)
                await db.flush()
            shelf_cache[key] = row
            return row

        inserted = skipped = 0

        for entry in KB:
            title = entry["title"]
            if title in existing_titles:
                skipped += 1
                continue

            lib = await get_or_create_library(entry["category"])
            shelf = await get_or_create_shelf(lib, entry["category"])

            # Resolve see_also IDs to titles for wiki-links
            id_to_title = {e["id"]: e["title"] for e in KB}
            see_also_titles = [id_to_title[sid] for sid in entry.get("see_also", []) if sid in id_to_title]

            content = render_kb_doc_content(
                severity=entry["severity"],
                pattern=entry["pattern"],
                plain_english=entry["plain_english"],
                causes=entry["causes"],
                fix_steps=entry["fix_steps"],
                see_also_titles=see_also_titles,
            )

            doc = Doc(
                id=str(uuid.uuid4()),
                name=title,
                content=content,
                shelf_id=shelf.id,
                tenant_id=TENANT_ID,
                version=1,
            )
            db.add(doc)
            existing_titles.add(title)
            inserted += 1
            print(f"  seeded [{entry['id']}] {title}")

        await db.commit()
        print(f"\nDone — seeded {inserted} docs, skipped {skipped} already present.")


if __name__ == "__main__":
    asyncio.run(main())
