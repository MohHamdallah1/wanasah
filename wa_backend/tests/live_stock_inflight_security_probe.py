"""Read-only, tenant-scoped before/after digest for the disposable auth gate."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.live_stock_real_browser_support import _engines, _runtime_session


async def main():
    assert os.environ.get("WANASAH_INFLIGHT_AUTH_GATE") == "1"
    tenants = [int(value) for value in sys.argv[1:]]
    assert len(tenants) == 2 and all(value > 0 for value in tenants)
    runtime, admin = await _engines()
    try:
        result = {}
        for company in tenants:
            async with _runtime_session(runtime, company) as db:
                role = (await db.execute(text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ))).one()
                assert tuple(role) == (False, False)
                tables = {}
                for name in ("inventory_balances", "inventory_movements",
                             "inventory_cost_states", "inventory_cost_events"):
                    # Names are fixed above. No writes or external identifiers enter SQL.
                    rows = (await db.execute(text(
                        f"SELECT row_to_json(t)::text FROM {name} t "
                        "WHERE company_id=:tenant ORDER BY id"
                    ), {"tenant": company})).scalars().all()
                    assert rows, (company, name)
                    tables[name] = {"rows": len(rows), "sha256": hashlib.sha256(
                        "\n".join(rows).encode("utf8")).hexdigest()}
                result[str(company)] = tables
        print(json.dumps(result, sort_keys=True))
    finally:
        await runtime.dispose()
        await admin.dispose()


if __name__ == "__main__":
    asyncio.run(main())
