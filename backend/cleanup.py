import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        r = await conn.execute(text("DELETE FROM bm_environments WHERE status='destroyed'"))
        print(f"Deleted {r.rowcount} destroyed environments")

asyncio.run(main())
