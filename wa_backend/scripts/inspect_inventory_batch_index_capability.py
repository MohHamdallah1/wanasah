from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (
            (candidate / "main.py").is_file()
            and (candidate / "database.py").is_file()
        ):
            return candidate.resolve()
    raise RuntimeError("wa_backend not found.")


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import engine  # noqa: E402


async def main() -> None:
    async with engine.connect() as conn:
        identity = (
            await conn.execute(
                text(
                    """
                    SELECT
                        current_user AS current_user,
                        current_setting('is_superuser') = 'on'
                            AS is_superuser,
                        owner.rolname AS product_batches_owner,
                        has_schema_privilege(
                            current_user,
                            current_schema(),
                            'CREATE'
                        ) AS can_create_in_schema
                    FROM pg_class AS rel
                    JOIN pg_namespace AS ns
                      ON ns.oid = rel.relnamespace
                    JOIN pg_roles AS owner
                      ON owner.oid = rel.relowner
                    WHERE ns.nspname = current_schema()
                      AND rel.relname = 'product_batches'
                      AND rel.relkind = 'r'
                    """
                )
            )
        ).mappings().one()

        hypopg = (
            await conn.execute(
                text(
                    """
                    SELECT
                        EXISTS (
                            SELECT 1
                            FROM pg_extension
                            WHERE extname = 'hypopg'
                        ) AS installed,
                        EXISTS (
                            SELECT 1
                            FROM pg_available_extensions
                            WHERE name = 'hypopg'
                        ) AS available
                    """
                )
            )
        ).mappings().one()

    print("=== DB IDENTITY ===")
    print(
        f"current_user={identity['current_user']} "
        f"product_batches_owner={identity['product_batches_owner']} "
        f"is_superuser={identity['is_superuser']} "
        f"can_create_in_schema={identity['can_create_in_schema']}"
    )
    print("=== HYPOPG ===")
    print(
        f"installed={hypopg['installed']} "
        f"available={hypopg['available']}"
    )
    print("INVENTORY_BATCH_INDEX_CAPABILITY=PASS read_only=true")


if __name__ == "__main__":
    asyncio.run(main())
