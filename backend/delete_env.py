import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM bm_environments WHERE name='test6'"))
    print("deleted test6")

asyncio.run(main())
