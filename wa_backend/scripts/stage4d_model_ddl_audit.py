"""Read-only comparison point for PostgreSQL constraints used by model DDL."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from database import engine


async def main():
    async with engine.connect() as connection:
        rows = (await connection.execute(text("""
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'shops'::regclass
              AND conname IN ('fk_shop_tenant_zone', 'fk_shop_tenant_added_by')
            ORDER BY conname
        """))).all()
        for name, definition in rows:
            print(f'{name}={definition}')
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
