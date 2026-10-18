"""Independent final-closure acceptance; tests only, never a release sign-off.

Uses the accepted CP8 disposable PostgreSQL gate, then provisions isolated
one-Warehouse tenants of its own. Stock enters only through movement authority.
Missing closure behavior is an ordinary failure, never xfail/continue-on-error.
See docs/verification/INVENTORY_V1_FINAL_CLOSURE_ACCEPTANCE.md for unwired contracts.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from importlib import import_module
import os
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import dispatch, reconciliation
from api.authentication.dependencies import get_current_backoffice_context
from api.warehouse import ledger, transfer_policy, transfers
from database import get_db
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement, InventoryMovementImpact,
    InventoryTransferHeader, Permission, Product, ProductBatch, ProductLocation, ProductVariant,
    SessionInventorySnapshot, StocktakeCountAttemptLine, StocktakeLine, StocktakeSession, SystemAuditLog,
    UOM, UserLocationAccess, Vehicle, WorkSession, Zone, role_permissions, utc_now,
)
from schemas import (
    InventoryStatusChangeRequest, SpecialTransferDispatchRequest,
    TransferDestinationPolicyPublishRequest, TransferDestinationPolicySaveRequest,
)
from services import apply_inventory_movement, SPECIAL_TRANSFER_PERMISSION
from tests.canonical_actor_fixtures import (
    seed_field_fixture, seed_ordinary_backoffice_fixture,
)
from tests.test_cp8_transfers_postgres import pg  # noqa: F401 -- pytest fixture
from tests.test_cp14c_stocktake_lifecycle_postgres import (
    _ensure_permissions, _grant_company, _grant_location, _runtime_session,
)

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_CP8_PG_GATE") != "1",
                       reason="Explicit disposable CP8 PostgreSQL gate only"),
    pytest.mark.asyncio(loop_scope="function"),
]


@pytest_asyncio.fixture(loop_scope="function")
async def closure(pg):
    """No Owner, exactly one Warehouse per tenant, distinct canonical identities."""
    gate = NS(runtime_engine=pg.runtime_engine, admin_engine=pg.admin_engine)
    gate.session = lambda tenant: _runtime_session(pg.runtime_engine, tenant.company_id)
    async with pg.runtime_engine.connect() as connection:
        for table in ("inventory_balances", "inventory_movements", "stocktake_sessions"):
            flags = (await connection.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:table)"), {"table": table})).one()
            assert tuple(flags) == (True, True), table
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        codes = {"inventory.read", "inventory.status_change", "ledger.read",
                 "location.read", "transfer.send", "transfer.destination",
                 "inventory.transfer_policy.manage", "settlement.read", "settlement.execute",
                 "stocktake.start", "stocktake.count",
                 *SPECIAL_TRANSFER_PERMISSION.values()}
        await _ensure_permissions(db, codes)
        uom = await db.scalar(select(UOM).where(UOM.code == "EACH"))
        assert uom is not None
        tenants = []
        for label in ("A", "B"):
            company = Company(name="Closure overlap", company_code="CLOSE-" + uuid4().hex,
                              timezone="Asia/Amman", currency_code="JOD")
            db.add(company)
            await db.flush()
            await db.execute(text("SELECT set_config('app.current_tenant', :tenant, true)"),
                             {"tenant": str(company.id)})
            actor = await seed_ordinary_backoffice_fixture(db, company.id)
            denied = await seed_ordinary_backoffice_fixture(db, company.id)
            field = await seed_field_fixture(db, company.id)
            warehouse = InventoryLocation(company_id=company.id, code="ONLY-WH",
                name="Closure overlap", location_type="WAREHOUSE", is_active=True)
            # CP8 deliberately seeds explicit Vehicle IDs without advancing its sequence.
            # Give this independent fixture a disjoint, company-unique synthetic ID.
            vehicle = Vehicle(id=1_500_000_000 + company.id,
                              company_id=company.id, plate_number="CLOSE-" + label,
                              is_active=True, maintenance_status="Active")
            product = Product(company_id=company.id, code="CLOSE-P", name="Closure product")
            zone = Zone(company_id=company.id, name="Closure zone", is_active=True)
            db.add_all([warehouse, vehicle, product, zone])
            await db.flush()
            vehicle_location = InventoryLocation(company_id=company.id, code="VEH",
                name="Closure overlap", location_type="VEHICLE", vehicle_id=vehicle.id,
                is_active=True)
            variant = ProductVariant(company_id=company.id, product_id=product.id,
                name="Closure product", sku="CLOSE-SKU", base_uom_id=uom.id,
                quantity_scale=0, quantity_step=Decimal("1"), lot_control_mode="REQUIRED",
                expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE",
                published_at=utc_now())
            now = utc_now()
            work = WorkSession(company_id=company.id, driver_id=field.driver.id,
                start_time=now, end_time=now, session_date=date.today(), is_settled=False)
            db.add_all([vehicle_location, variant, work])
            await db.flush()
            batch = ProductBatch(company_id=company.id, product_variant_id=variant.id,
                                 batch_number="CLOSE-LOT")
            db.add(batch)
            db.add(ProductLocation(company_id=company.id, location_id=warehouse.id,
                                   product_variant_id=variant.id, created_by=actor.driver_id))
            db.add(DispatchRoute(company_id=company.id, zone_id=zone.id,
                driver_id=field.driver.id, vehicle_id=vehicle.id, work_session_id=work.id,
                source_location_id=warehouse.id, dispatch_date=date.today(), status="closed"))
            await db.flush()
            tenant = NS(company_id=company.id, actor=actor, denied=denied, field=field,
                warehouse=warehouse.id, vehicle_location=vehicle_location.id, vehicle=vehicle.id,
                variant=variant.id, batch=batch.id, uom=uom.id, work=work.id)
            assert actor.context.is_company_owner is False
            assert len({actor.context.principal_id, actor.context.backoffice_user_id,
                        actor.driver_id}) == 3
            await _grant_location(db, company_id=company.id, driver_id=actor.driver_id,
                location_id=warehouse.id, codes=("inventory.read", "inventory.status_change",
                    "ledger.read", "location.read", "transfer.send", "transfer.destination"))
            await _grant_location(db, company_id=company.id, driver_id=actor.driver_id,
                location_id=vehicle_location.id, codes=("inventory.read", "ledger.read",
                    "transfer.send", "stocktake.start", "stocktake.count"))
            for code in ("inventory.transfer_policy.manage", "settlement.read", "settlement.execute",
                         *SPECIAL_TRANSFER_PERMISSION.values()):
                await _grant_company(db, company_id=company.id,
                                     driver_id=actor.driver_id, code=code)
            tenants.append(tenant)
        await db.commit()
    gate.a, gate.b = tenants
    for tenant in tenants:
        async with gate.session(tenant) as db:
            assert await db.scalar(select(func.count()).select_from(InventoryLocation).where(
                InventoryLocation.company_id == tenant.company_id,
                InventoryLocation.location_type == "WAREHOUSE")) == 1
            assert await db.get(InventoryLocation, next(
                other.warehouse for other in tenants if other is not tenant)) is None
            for location, status, quantity in (
                (tenant.warehouse, "AVAILABLE", "20"),
                (tenant.warehouse, "DAMAGED", "3"),
                (tenant.vehicle_location, "AVAILABLE", "6"),
                (tenant.vehicle_location, "DAMAGED", "4"),
            ):
                await apply_inventory_movement(db, company_id=tenant.company_id,
                    performed_by=tenant.actor.driver_id, product_variant_id=tenant.variant,
                    batch_id=tenant.batch, quantity=Decimal(quantity), movement_kind="PHYSICAL",
                    reference_type="CLOSURE_OPENING", reference_id=str(tenant.work),
                    idempotency_key="CLOSURE-" + uuid4().hex, source_location_id=None,
                    destination_location_id=location, source_stock_status=None,
                    destination_stock_status=status)
            await db.commit()
    return gate


async def evidence(gate, tenant):
    async with gate.session(tenant) as db:
        balances = (await db.execute(select(
            InventoryBalance.location_id, InventoryBalance.product_variant_id,
            InventoryBalance.batch_id, InventoryBalance.stock_status,
            InventoryBalance.on_hand_quantity, InventoryBalance.reserved_quantity,
        ).where(InventoryBalance.company_id == tenant.company_id).order_by(
            InventoryBalance.id))).all()
        movements = (await db.execute(select(
            InventoryMovement.id, InventoryMovement.source_location_id,
            InventoryMovement.destination_location_id, InventoryMovement.quantity,
        ).where(InventoryMovement.company_id == tenant.company_id).order_by(
            InventoryMovement.id))).all()
        snapshots = (await db.execute(select(
            SessionInventorySnapshot.id, SessionInventorySnapshot.stock_status,
            SessionInventorySnapshot.ending_quantity, SessionInventorySnapshot.settled_by,
            SessionInventorySnapshot.settled_at,
        ).where(SessionInventorySnapshot.company_id == tenant.company_id).order_by(
            SessionInventorySnapshot.id))).all()
        work = await db.get(WorkSession, tenant.work)
        audits = await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == tenant.company_id))
        return NS(balances=tuple(map(tuple, balances)), movements=tuple(map(tuple, movements)),
                  snapshots=tuple(map(tuple, snapshots)),
                  seal=(work.inventory_reconciled_at, work.inventory_reconciled_by),
                  settled=work.is_settled, audits=audits)


def receiver_module():
    try:
        return import_module("api.representative_settlement")
    except ModuleNotFoundError as exc:
        if exc.name != "api.representative_settlement":
            raise
        pytest.fail(
            "RECEIVER_CONTRACT_NOT_IN_CANDIDATE: integrate the reviewed Backend "
            "receiver implementation before running positive closure acceptance"
        )


async def runtime_request(gate, tenant, *, path, method="GET", body=None,
                          actor=None, receiver=False):
    """Actual routes/dependencies; override authenticated identity and DB only."""
    actor = actor or tenant.actor
    app = FastAPI()
    app.include_router(dispatch.router)
    if receiver:
        app.include_router(receiver_module().router)

    async def runtime_db():
        async with gate.session(tenant) as db:
            yield db

    app.dependency_overrides[get_db] = runtime_db
    app.dependency_overrides[get_current_backoffice_context] = lambda: actor.context
    app.dependency_overrides[dispatch.get_current_backoffice_legacy_driver] = (
        lambda: actor.operational_driver
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://closure.test") as client:
        return await client.request(method, path, json=body)


async def financial(gate, tenant, *, actor=None, session_id=None):
    return await runtime_request(gate, tenant, actor=actor, method="PUT",
        path=f"/admin/sessions/{session_id or tenant.work}/settle",
        body={
            "actual_cash": "0.000", "notes": "Acceptance",
            **({} if os.getenv("WANASAH_CLOSURE_BASELINE_EVIDENCE") == "1"
               else {"request_id": str(uuid4())}),
        })


async def custody(gate, tenant, *, body=None, actor=None, session_id=None):
    path = f"/admin/sessions/{session_id or tenant.work}/inventory-custody"
    return await runtime_request(gate, tenant, path=path + ("/receive" if body else ""),
        method="POST" if body else "GET", body=body, actor=actor, receiver=True)


async def receiving_command(gate, tenant):
    preview = await custody(gate, tenant)
    assert preview.status_code == 200, preview.text
    lines = preview.json()["lines"]
    assert {row["stock_status"] for row in lines} == {"AVAILABLE", "DAMAGED"}
    assert {row["batch_number"] for row in lines} == {"CLOSE-LOT"}
    return {
        "request_id": str(uuid4()), "destination_location_id": tenant.warehouse,
        "receiver_confirms_handoff": True, "notes": "Independent receiving evidence",
        "items": [{"line_key": row["line_key"], "actual_quantity": row["expected_quantity"]}
                  for row in lines],
    }, {row["stock_status"]: row["line_key"] for row in lines}


async def reconcile(gate, tenant, quantity):
    async with gate.session(tenant) as db:
        return await reconciliation.reconcile_driver_end_of_day(
            tenant.work, reconciliation.VehicleReconciliationRequest(counts=[
                {"product_variant_id": tenant.variant, "actual_quantity": quantity}
            ]), db, tenant.field.context, tenant.field.driver)


async def test_one_warehouse_quantity_status_is_exact_replay_safe_and_ledgered(closure):
    status = "QUARANTINED"
    a = closure.a
    command = InventoryStatusChangeRequest(request_id=uuid4(), location_id=a.warehouse,
        product_variant_id=a.variant, batch_id=a.batch, uom_id=a.uom,
        source_status="AVAILABLE", destination_status=status, quantity="2",
        reason="Independent closure acceptance")
    before = await evidence(closure, a)

    async def execute(payload=command, actor=a.actor):
        async with closure.session(a) as db:
            return await transfers.change_inventory_status(
                payload, db, actor.access(db), actor.operational_driver)

    async def fail_after_movement(*args, **kwargs):
        await apply_inventory_movement(*args, **kwargs)
        raise RuntimeError("Synthetic lost transaction before commit")

    with patch.object(transfers, "apply_inventory_movement", fail_after_movement):
        with pytest.raises(HTTPException) as aborted:
            await execute()
        assert aborted.value.status_code == 500
    assert vars(await evidence(closure, a)) == vars(before)
    one, two = await asyncio.gather(execute(), execute())
    assert one == two == await execute()  # lost response / concurrent duplicate
    after = await evidence(closure, a)
    assert len(after.movements) == len(before.movements) + 1
    quantities = {(r[0], r[3]): Decimal(r[4]) for r in after.balances}
    assert quantities[a.warehouse, "AVAILABLE"] == 18
    assert quantities[a.warehouse, status] == 2
    assert quantities[a.warehouse, "DAMAGED"] == 3
    assert quantities[a.vehicle_location, "AVAILABLE"] == 6
    assert quantities[a.vehicle_location, "DAMAGED"] == 4
    async with closure.session(a) as db:
        movement = await db.get(InventoryMovement, after.movements[-1][0])
        assert movement.movement_kind == "STATUS_CHANGE"
        assert movement.source_location_id == movement.destination_location_id == a.warehouse
        assert movement.batch_id == a.batch and Decimal(movement.quantity) == 2
        page = await ledger.get_warehouse_ledger_cursor(
            a.warehouse, None, 100, None, movement.reference_type,
            movement.reference_id, db, a.actor.access(db))
        assert movement.id in {row["id"] for row in page["items"]}
    for changed, statuses in (
        (command.model_copy(update={"quantity": Decimal("1")}), {409}),
        (command.model_copy(update={"request_id": uuid4(), "location_id": a.vehicle_location}), {403}),
        (command.model_copy(update={"request_id": uuid4(), "location_id": closure.b.warehouse}), {403, 404}),
    ):
        with pytest.raises(HTTPException) as rejected:
            await execute(changed)
        assert rejected.value.status_code in statuses
    with pytest.raises(HTTPException) as denied:
        await execute(actor=a.denied)
    assert denied.value.status_code == 403
    assert vars(await evidence(closure, a)) == vars(after)
    async with AsyncSession(closure.admin_engine, expire_on_commit=False) as db:
        roles = select(role_permissions.c.role_id).join(
            Permission, Permission.id == role_permissions.c.permission_id
        ).where(role_permissions.c.company_id == a.company_id,
                Permission.code == "inventory.status_change")
        await db.execute(UserLocationAccess.__table__.delete().where(
            UserLocationAccess.company_id == a.company_id,
            UserLocationAccess.driver_id == a.actor.driver_id,
            UserLocationAccess.location_id == a.warehouse,
            UserLocationAccess.role_id.in_(roles)))
        await db.commit()
    with pytest.raises(HTTPException) as revoked_replay:
        await execute()
    assert revoked_replay.value.status_code == 403
    assert vars(await evidence(closure, a)) == vars(after)


@pytest.mark.parametrize("purpose,source,target", [
    ("DISPOSAL", "AVAILABLE", "DISPOSAL_PENDING"),
    ("RETURN_TO_VENDOR", "AVAILABLE", "QUARANTINED"),
    ("DISPOSAL", "DAMAGED", "DISPOSAL_PENDING"),
    ("RETURN_TO_VENDOR", "DAMAGED", "DAMAGED"),
])
async def test_published_same_location_defaults_stage_without_another_warehouse(
    closure, purpose, source, target,
):
    """Null default contract is present in the quality worker's draft API, not base."""
    a = closure.a
    async with closure.session(a) as db:
        # Metadata only. Never patch balances or bypass the public stage endpoint.
        variant = await db.get(ProductVariant, a.variant)
        variant.operational_hold = "RECALL"
        await db.commit()
        draft = await transfer_policy.save_transfer_destination_policy(
            TransferDestinationPolicySaveRequest(request_id=uuid4(), payload={
                "quarantine_location_id": None, "disposal_location_id": None,
                "vendor_return_staging_location_id": None,
                "allow_retiring_warehouse_balancing": False,
            }), db, a.actor.access(db), a.actor.operational_driver)
        await transfer_policy.publish_transfer_destination_policy_endpoint(
            draft["policy"]["id"], TransferDestinationPolicyPublishRequest(
                request_id=uuid4(), expected_revision=draft["policy"]["revision"]),
            db, a.actor.access(db), a.actor.operational_driver)
    command = SpecialTransferDispatchRequest(request_id=uuid4(),
        source_location_id=a.warehouse, transfer_purpose=purpose,
        notes="Independent same-Warehouse quality staging",
        items=[dict(product_variant_id=a.variant, batch_id=a.batch,
                    source_status=source, quantity="2", uom_id=a.uom)])
    async def stage():
        async with closure.session(a) as db:
            return await transfers.stage_inventory_quality_handling(
                command, db, a.actor.access(db), a.actor.operational_driver)
    result = await stage()
    assert await stage() == result
    async with closure.session(a) as db:
        header = await db.get(InventoryTransferHeader, result["header_id"])
        assert header.status == "POSTED" and header.transit_location_id is None
        assert header.source_location_id == header.destination_location_id == a.warehouse
        portions = (await db.execute(select(
            InventoryBalance.stock_status, InventoryBalance.on_hand_quantity,
        ).where(InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.warehouse))).all()
        expected = {"AVAILABLE": Decimal("20"), "DAMAGED": Decimal("3")}
        expected[source] -= 2
        expected[target] = expected.get(target, Decimal("0")) + 2
        assert dict(portions) == expected
        assert await db.scalar(select(func.count()).select_from(InventoryLocation).where(
            InventoryLocation.company_id == a.company_id,
            InventoryLocation.location_type == "WAREHOUSE")) == 1
        moves = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == a.company_id,
            InventoryMovement.transfer_header_id == header.id))).all()
        if source == target:
            assert not moves  # staging DAMAGED for vendor preserves status and quantity
        else:
            assert len(moves) == 1 and moves[0].movement_kind == "STATUS_CHANGE"
            assert moves[0].batch_id == a.batch and Decimal(moves[0].quantity) == 2
            page = await ledger.get_warehouse_ledger_cursor(
                a.warehouse, None, 100, None, moves[0].reference_type,
                moves[0].reference_id, db, a.actor.access(db))
            assert moves[0].id in {row["id"] for row in page["items"]}


async def test_unsealed_financial_close_is_noop_and_capability_and_tenant_bound(closure):
    a = closure.a
    before = await evidence(closure, a)
    denied = await financial(closure, a, actor=a.denied)
    assert denied.status_code == 403
    foreign = await financial(closure, a, session_id=closure.b.work)
    absent = await financial(closure, a, session_id=2_147_483_647)
    assert foreign.status_code == absent.status_code == 404
    assert foreign.json() == absent.json()
    blocked = await financial(closure, a)
    assert blocked.status_code == 409
    assert vars(await evidence(closure, a)) == vars(before)


async def test_field_aggregate_match_never_implicitly_transfers_vehicle_custody(closure):
    a = closure.a
    before = await evidence(closure, a)
    await reconcile(closure, a, "10")
    await reconcile(closure, a, "10")
    after = await evidence(closure, a)
    assert after.balances == before.balances
    assert after.movements == before.movements
    assert after.settled is False


async def test_aggregate_variance_stays_open_and_retries_reuse_one_audit(closure):
    a = closure.a
    before = await evidence(closure, a)
    first = await reconcile(closure, a, "9")  # expected 6 AVAILABLE + 4 DAMAGED
    retry = await reconcile(closure, a, "9")
    assert first["requires_audit"] is retry["requires_audit"] is True
    assert first["stocktake_session_id"] == retry["stocktake_session_id"]
    after = await evidence(closure, a)
    assert after.balances == before.balances and after.movements == before.movements
    assert after.seal == (None, None) and after.settled is False
    async with closure.session(a) as db:
        assert await db.scalar(select(func.count()).select_from(StocktakeSession).where(
            StocktakeSession.company_id == a.company_id,
            StocktakeSession.related_work_session_id == a.work)) == 1
    assert (await financial(closure, a)).status_code == 409


async def test_financial_close_requires_receiver_handoff_not_only_legacy_seal(closure):
    a = closure.a
    await reconcile(closure, a, "10")
    before = await evidence(closure, a)
    # No receiver command has occurred; 6 AVAILABLE + 4 DAMAGED remain on Vehicle.
    response = await financial(closure, a)
    assert response.status_code == 409, (
        "Financial close accepted a legacy aggregate seal without confirmed Warehouse "
        f"custody handoff: {response.status_code} {response.text}"
    )
    assert vars(await evidence(closure, a)) == vars(before)


async def test_receiver_exact_status_handoff_then_financial_close_has_no_recount(closure):
    a = closure.a
    before = await evidence(closure, a)
    command, _ = await receiving_command(closure, a)
    assert vars(await evidence(closure, a)) == vars(before)  # opening never receives
    unconfirmed = await custody(closure, a, body={**command, "receiver_confirms_handoff": False})
    assert unconfirmed.status_code == 422
    assert (await custody(closure, a, actor=a.denied)).status_code == 403
    foreign = await custody(closure, a, session_id=closure.b.work)
    absent = await custody(closure, a, session_id=2_147_483_647)
    assert foreign.status_code == absent.status_code == 404
    assert foreign.json() == absent.json()
    assert vars(await evidence(closure, a)) == vars(before)
    first, duplicate = await asyncio.gather(
        custody(closure, a, body=command), custody(closure, a, body=command))
    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert first.json()["status"] == "CUSTODY_RECEIVED"
    assert first.json()["movement_count"] == 2
    assert (await custody(closure, a, body=command)).json() == first.json()
    received = await evidence(closure, a)
    quantities = {(r[0], r[3]): Decimal(r[4]) for r in received.balances}
    assert quantities[a.warehouse, "AVAILABLE"] == 26
    assert quantities[a.warehouse, "DAMAGED"] == 7
    assert quantities[a.vehicle_location, "AVAILABLE"] == 0
    assert quantities[a.vehicle_location, "DAMAGED"] == 0
    assert sum(Decimal(r[4]) for r in received.balances) == 33
    assert received.seal[0] is not None and received.settled is False
    async with closure.session(a) as db:
        moves = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == a.company_id,
            InventoryMovement.work_session_id == a.work,
            InventoryMovement.reference_type == "REPRESENTATIVE_CUSTODY_RECEIPT"))).all()
        assert {(m.source_stock_status, m.destination_stock_status, Decimal(m.quantity))
                for m in moves} == {
                    ("AVAILABLE", "AVAILABLE", Decimal("6")),
                    ("DAMAGED", "DAMAGED", Decimal("4")),
                }
        assert all(m.batch_id == a.batch and m.source_location_id == a.vehicle_location
                   and m.destination_location_id == a.warehouse
                   and m.performed_by == a.actor.driver_id for m in moves)
        # The accepted Ledger entry point is Warehouse-only. Check its complete
        # source/destination evidence, plus immutable impacts for BOTH custody legs.
        page = await ledger.get_warehouse_ledger_cursor(
            a.warehouse, None, 100, None, "REPRESENTATIVE_CUSTODY_RECEIPT",
            str(a.work), db, a.actor.access(db))
        assert {m.id for m in moves} <= {row["id"] for row in page["items"]}
        for row in page["items"]:
            assert row["source_location_id"] == a.vehicle_location
            assert row["destination_location_id"] == a.warehouse
            assert row["source_stock_status"] == row["destination_stock_status"]
        impacts = (await db.execute(select(
            InventoryBalance.location_id, InventoryBalance.stock_status,
            InventoryMovementImpact.on_hand_before, InventoryMovementImpact.on_hand_after,
        ).join(InventoryMovementImpact,
               InventoryMovementImpact.inventory_balance_id == InventoryBalance.id,
        ).where(InventoryMovementImpact.company_id == a.company_id,
                InventoryMovementImpact.movement_id.in_([m.id for m in moves])))).all()
        assert set(map(tuple, impacts)) == {
            (a.vehicle_location, "AVAILABLE", Decimal("6"), Decimal("0")),
            (a.warehouse, "AVAILABLE", Decimal("20"), Decimal("26")),
            (a.vehicle_location, "DAMAGED", Decimal("4"), Decimal("0")),
            (a.warehouse, "DAMAGED", Decimal("3"), Decimal("7")),
        }
        assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == a.company_id,
            SystemAuditLog.target_id == f"WorkSession_{a.work}",
            SystemAuditLog.action_type == "REPRESENTATIVE_CUSTODY_RECEIVED")) == 1
    closed = await financial(closure, a)
    assert closed.status_code == 200 and closed.json()["is_settled"] is True
    after_finance = await evidence(closure, a)
    for field in ("balances", "movements", "snapshots", "seal"):
        assert getattr(after_finance, field) == getattr(received, field)
    assert after_finance.settled is True
    assert (await financial(closure, a)).status_code == 409
    assert vars(await evidence(closure, a)) == vars(after_finance)


@pytest.mark.parametrize("available,damaged", [("6", "3"), ("5", "5")])
async def test_receiver_variance_preserves_exact_status_evidence_not_just_total(
    closure, available, damaged,
):
    a = closure.a
    before = await evidence(closure, a)
    command, keys = await receiving_command(closure, a)
    incomplete = await custody(closure, a, body={**command, "items": command["items"][:1]})
    assert incomplete.status_code == 422
    assert vars(await evidence(closure, a)) == vars(before)
    quantities = {keys["AVAILABLE"]: available, keys["DAMAGED"]: damaged}
    command["items"] = [{"line_key": item["line_key"],
                         "actual_quantity": quantities[item["line_key"]]}
                        for item in command["items"]]
    first = await custody(closure, a, body=command)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "REVIEW_REQUIRED"
    assert first.json()["movement_count"] == 0
    retry = await custody(closure, a, body=command)
    assert retry.status_code == 200 and retry.json() == first.json()
    changed = await custody(closure, a, body={**command, "notes": "Different command"})
    assert changed.status_code == 409
    after = await evidence(closure, a)
    assert after.balances == before.balances and after.movements == before.movements
    assert after.seal == (None, None) and after.settled is False
    async with closure.session(a) as db:
        rows = (await db.execute(select(
            StocktakeLine.batch_id, StocktakeLine.stock_status,
            StocktakeCountAttemptLine.expected_quantity,
            StocktakeCountAttemptLine.actual_quantity,
            StocktakeCountAttemptLine.variance_quantity,
        ).join(StocktakeCountAttemptLine,
               StocktakeCountAttemptLine.stocktake_line_id == StocktakeLine.id).join(
            StocktakeSession, StocktakeSession.id == StocktakeLine.stocktake_session_id,
        ).where(StocktakeSession.company_id == a.company_id,
                StocktakeSession.related_work_session_id == a.work))).all()
        assert set(map(tuple, rows)) == {
            (a.batch, "AVAILABLE", Decimal("6"), Decimal(available), Decimal(available) - 6),
            (a.batch, "DAMAGED", Decimal("4"), Decimal(damaged), Decimal(damaged) - 4),
        }
        assert await db.scalar(select(func.count()).select_from(StocktakeSession).where(
            StocktakeSession.company_id == a.company_id,
            StocktakeSession.related_work_session_id == a.work)) == 1
    assert (await financial(closure, a)).status_code == 409


async def test_receiver_partial_failure_retry_scope_and_revoked_replay(closure):
    a = closure.a
    module = receiver_module()
    command, _ = await receiving_command(closure, a)
    before = await evidence(closure, a)
    denied = await custody(closure, a, body=command, actor=a.denied)
    foreign = await custody(closure, a, body={
        **command, "destination_location_id": closure.b.warehouse,
    })
    assert denied.status_code == 403 and foreign.status_code in {403, 404}
    real_apply = module.apply_inventory_movements_batch

    async def fail_after_first_movement(db, **kwargs):
        await real_apply(db, **{**kwargs, "movements": kwargs["movements"][:1]})
        raise RuntimeError("Synthetic interruption between custody rows")

    with patch.object(module, "apply_inventory_movements_batch", fail_after_first_movement):
        failed = await custody(closure, a, body=command)
    assert failed.status_code == 500
    assert vars(await evidence(closure, a)) == vars(before)
    retried = await custody(closure, a, body=command)
    assert retried.status_code == 200 and retried.json()["status"] == "CUSTODY_RECEIVED"
    received = await evidence(closure, a)
    fresh_id = await custody(closure, a, body={**command, "request_id": str(uuid4())})
    assert fresh_id.status_code == 409
    async with AsyncSession(closure.admin_engine, expire_on_commit=False) as db:
        roles = select(role_permissions.c.role_id).join(
            Permission, Permission.id == role_permissions.c.permission_id,
        ).where(role_permissions.c.company_id == a.company_id, Permission.code == "transfer.send")
        await db.execute(UserLocationAccess.__table__.delete().where(
            UserLocationAccess.company_id == a.company_id,
            UserLocationAccess.driver_id == a.actor.driver_id,
            UserLocationAccess.location_id == a.vehicle_location,
            UserLocationAccess.role_id.in_(roles)))
        await db.commit()
    assert (await custody(closure, a, body=command)).status_code == 403
    assert vars(await evidence(closure, a)) == vars(received)
