"""#838 disposable-only real PG16/browser seed and inspection; never production.

Existing accepted dispatch_p0_wire_fixture supplies canonical product/custody,
real Owner Bearer login, a commercial-ready waiting route and tenant isolation.
This additive fixture seeds an alternate FIELD representative, without changing
any application authority or production code. Runtime probes use restricted RLS.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.field_provisioning import assign_new_representative_default
from models import Company, DispatchRoute, InventoryBalance, InventoryMovement, Shop, Zone
from domains.identity.models import CompanyPrincipal
from tests.canonical_actor_fixtures import seed_field_fixture
from tests.dispatch_p0_wire_fixture import test_seed_dispatch_browser
from tests.live_stock_real_browser_support import _engines, _runtime_session
from tests.test_inbound_no_lot_frozen_postgres import checked_urls, pg  # noqa: F401

STATE = Path(os.environ.get("WANASAH_DISPATCH_P0_WIRE_STATE", "/tmp/dispatch-v1-deep-state.json"))
pytestmark = [
    pytest.mark.asyncio(loop_scope="function"),
    pytest.mark.skipif(os.environ.get("WANASAH_DISPATCH_V1_DEEP_GATE") != "1",
                       reason="Explicit disposable PG16 browser audit gate only"),
]


def gate() -> None:
    assert os.environ.get("WANASAH_DISPATCH_V1_DEEP_GATE") == "1"
    assert os.environ.get("WANASAH_DISPATCH_P0_WIRE_GATE") == "1"
    assert os.environ.get("WANASAH_NO_LOT_PG_GATE") == "1"
    assert "wanasah_no_lot_contract_test" in str(STATE) or str(STATE).startswith("/tmp/")
    checked_urls()  # explicit localhost, restricted runtime and dedicated admin roles


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_seed_real_dispatch_v1_dashboard(pg):
    gate()
    assert not STATE.exists(), "Refuse to reuse stale fixture state"
    await test_seed_dispatch_browser(pg)
    state = json.loads(STATE.read_text(encoding="utf8"))
    a, b = pg.tenants[0], pg.tenants[1]
    async with pg.session() as db:
        second = await seed_field_fixture(db, a.company_id)
        await assign_new_representative_default(
            db, a.company_id, second.context.representative_id
        )
        await db.commit()
        state["secondDriverId"] = str(second.driver.id)
        rows = (await db.scalars(select(Shop).where(
            Shop.company_id == a.company_id, Shop.is_active.is_(True)
        ).order_by(Shop.id))).all()
        assert rows, "Commercial fixture must provide real active Shop"
        state["initialShopId"] = str(rows[0].id)
        state["initialShopName"] = rows[0].name
    async with AsyncSession(pg.admin_engine) as db:
        code_b = await db.scalar(select(Company.company_code).where(Company.id == b.company_id))
        username_b = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == b.owner.context.principal_id))
    state["companyB"] = {
        "companyId": b.company_id, "principalId": b.owner.context.principal_id,
        "credentials": {"code": code_b, "username": username_b,
                        "password": "NoLotSyntheticFixture123"}
    }
    STATE.write_text(json.dumps(state, default=str, indent=2), encoding="utf8")
    print("DISPATCH_V1_DEEP_SEED=PASS extra_field_and_company_B", flush=True)


async def probe(kind: str, shop_id: int | None) -> None:
    gate()
    state = json.loads(STATE.read_text(encoding="utf8"))
    runtime, admin = await _engines()
    try:
        async with _runtime_session(runtime, int(state["companyId"])) as db:
            if kind == "balance80":
                assert shop_id is not None
                shop = await db.scalar(select(Shop).where(
                    Shop.id == shop_id, Shop.company_id == state["companyId"]
                ).with_for_update())
                assert shop is not None
                assert Decimal(str(shop.current_balance)) == Decimal("100"), str(shop.current_balance)
                # Inject *only* a concurrent authorized-looking balance state into
                # disposable PG16. This is NOT proof of field collection workflow.
                shop.current_balance = Decimal("80")
                await db.commit()
                print("DISPATCH_V1_DEEP_CONCURRENT_BALANCE=80")
                return
            if kind != "snapshot":
                raise ValueError(kind)
            routes = (await db.scalars(select(DispatchRoute).where(
                DispatchRoute.company_id == state["companyId"]
            ).order_by(DispatchRoute.id))).all()
            shops = (await db.scalars(select(Shop).where(
                Shop.company_id == state["companyId"]
            ).order_by(Shop.id))).all()
            locations = (await db.scalars(select(InventoryBalance).where(
                InventoryBalance.company_id == state["companyId"]
            ))).all()
            movements = int(await db.scalar(select(func.count()).select_from(InventoryMovement)
                .where(InventoryMovement.company_id == state["companyId"])) or 0)
            output = {
                "routes": [{"id": str(x.id), "driverId": str(x.driver_id),
                            "status": x.status} for x in routes],
                "shops": [{"id": str(x.id), "zoneId": str(x.zone_id),
                           "sequence": x.sequence, "archived": bool(x.is_archived),
                           "currentBalance": str(x.current_balance), "name": x.name} for x in shops],
                "stock": [{"productId": str(x.product_variant_id),
                           "locationId": str(x.location_id),
                           "quantity": str(x.on_hand_quantity)} for x in locations],
                "movementCount": movements,
            }
            print("DISPATCH_V1_DEEP_SNAPSHOT=" + json.dumps(output, default=str))
    finally:
        await runtime.dispose()
        await admin.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("snapshot", "balance80"):
        raise SystemExit("Only snapshot or balance80 in isolated #838 gate")
    asyncio.run(probe(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None))
