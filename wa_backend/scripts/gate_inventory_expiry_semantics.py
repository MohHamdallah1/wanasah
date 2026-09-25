
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from api.warehouse.live_stock import get_warehouse_inventory_batches
from context import tenant_context
from scripts import gate_stage821_live_stock_projector_runtime as fixture


RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def run() -> None:
    ids: dict[str, int] | None = None
    try:
        await fixture.cleanup_test_companies()
        ids = await fixture.seed()
        as_of = date.fromordinal(int(ids["as_of_ordinal"]))

        async with fixture.SessionSU() as su:
            await su.begin()
            await su.execute(
                text(
                    """
                    UPDATE product_batches
                    SET expiry_date=:expired_date,
                        disposition='RELEASED',
                        is_active=true,
                        updated_at=NOW()
                    WHERE company_id=:company_id
                      AND id=:batch_id
                    """
                ),
                {
                    "expired_date": as_of - timedelta(days=1),
                    "company_id": ids["a"],
                    "batch_id": ids["a_batch1"],
                },
            )
            await su.execute(
                text(
                    """
                    UPDATE inventory_stock_policies
                    SET minimum_remaining_shelf_life_days=0,
                        updated_at=NOW()
                    WHERE company_id=:company_id
                      AND location_id=:location_id
                      AND product_variant_id=:variant_id
                      AND is_active=true
                    """
                ),
                {
                    "company_id": ids["a"],
                    "location_id": ids["a_wh"],
                    "variant_id": ids["a_variant"],
                },
            )
            await su.commit()

        actor = SimpleNamespace(
            id=2_147_483_647,
            company_id=ids["a"],
            is_admin=True,
        )
        token = tenant_context.set(ids["a"])
        try:
            async with fixture.SessionApp() as app:
                await app.begin()
                await fixture.set_tenant(app, ids["a"])
                payload = await get_warehouse_inventory_batches(
                    product_variant_id=ids["a_variant"],
                    location_id=ids["a_wh"],
                    cursor=None,
                    limit=100,
                    db=app,
                    current_admin=actor,
                )
                await app.rollback()
        finally:
            tenant_context.reset(token)

        expired = next(
            row
            for row in payload["batches"]
            if int(row["batch_id"]) == ids["a_batch1"]
        )

        record(
            "expired batch keeps operational disposition RELEASED",
            expired["disposition"] == "RELEASED",
            f"disposition={expired['disposition']}",
        )
        record(
            "expired released batch is not sellable",
            expired["days_to_expiry"] == -1
            and expired["available_for_sale_quantity"] == "0",
            (
                f"days_to_expiry={expired['days_to_expiry']} "
                f"available={expired['available_for_sale_quantity']}"
            ),
        )
        record(
            "expiry reason is isolated inside the restricted partition",
            expired["restricted_quantity"] == "8"
            and expired["expiry_unavailable_quantity"] == "8"
            and expired["unavailable_quantity"] == "12",
            (
                f"restricted={expired['restricted_quantity']} "
                f"expiry={expired['expiry_unavailable_quantity']} "
                f"unavailable={expired['unavailable_quantity']}"
            ),
        )
        record(
            "expiry does not absorb blocked or damaged stock reasons",
            expired["blocked_quantity"] == "3"
            and expired["damaged_quantity"] == "1"
            and expired["expiry_unavailable_quantity"] == "8",
            (
                f"blocked={expired['blocked_quantity']} "
                f"damaged={expired['damaged_quantity']} "
                f"expiry={expired['expiry_unavailable_quantity']}"
            ),
        )

        fresh = next(
            row
            for row in payload["batches"]
            if int(row["batch_id"]) != ids["a_batch1"]
            and row["days_to_expiry"] is not None
            and row["days_to_expiry"] > 0
        )
        record(
            "fresh sellable batch has no expiry-unavailable quantity",
            fresh["expiry_unavailable_quantity"] == "0",
            (
                f"batch_id={fresh['batch_id']} "
                f"expiry={fresh['expiry_unavailable_quantity']}"
            ),
        )
    finally:
        await fixture.cleanup_test_companies()
        await fixture.engine_app.dispose()
        await fixture.engine_su.dispose()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failed)}")
    for name in failed:
        print(f"FAILED_CHECK={name}")
    if failed:
        print("INVENTORY_EXPIRY_SEMANTICS_GATE=FAIL")
        raise SystemExit(1)
    print("INVENTORY_EXPIRY_SEMANTICS_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(run())
