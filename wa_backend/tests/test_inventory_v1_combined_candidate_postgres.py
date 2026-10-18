"""Combined-candidate contracts. No worker SHA, fallback, xfail or fake handoff."""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from psycopg.types.range import Range
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import transfer_policy, transfers
from domains.sales_calculation.policy import publish_commercial_rounding_policy
from domains.taxation.models import TaxRuleSet, TaxRuleSetVersion, TaxRuleComponent
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation, InventoryMovement,
    PriceBook, PriceBookAssignment, PriceBookEntry, PricePublication, ProductLocation,
    ProductVariant, RouteCommercialContext, SessionInventorySnapshot,
    StocktakeCountAttemptLine, StocktakeLine, StocktakeSession,
    SystemAuditLog, TenantOperationalPolicy, Permission, UserLocationAccess, UserRole,
    role_permissions, utc_now,
)
from schemas import (
    SpecialTransferDispatchRequest, TransferDestinationPolicySaveRequest,
    TransferDestinationPolicyPublishRequest, UnifiedReceiveRequest,
)
from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture
from tests.test_inventory_v1_final_closure_acceptance_postgres import (
    closure, custody, evidence, financial, receiving_command, runtime_request,
)
from tests.test_cp14c_stocktake_lifecycle_postgres import (
    _ensure_permissions, _grant_company, _grant_location,
)

# Reuse the guarded real PostgreSQL fixture; CI rejects every skipped case.
pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_CP8_PG_GATE") != "1",
                      reason="Explicit disposable PostgreSQL gate only"),
    pytest.mark.asyncio(loop_scope="function"),
]
PASSWORD = "SyntheticFixture123"


async def policy_rows(gate, tenant):
    async with gate.session(tenant) as db:
        return tuple((await db.execute(select(
            TenantOperationalPolicy.id, TenantOperationalPolicy.revision,
            TenantOperationalPolicy.status, TenantOperationalPolicy.validated_payload,
        ).where(TenantOperationalPolicy.company_id == tenant.company_id,
                TenantOperationalPolicy.policy_code == "INVENTORY_TRANSFER_DESTINATIONS")
         .order_by(TenantOperationalPolicy.id))).all())


@pytest_asyncio.fixture(loop_scope="function")
async def journey(closure):
    """Independent counter + real commercial evidence for shortage and later reload."""
    a = closure.a
    async with AsyncSession(closure.admin_engine, expire_on_commit=False) as db:
        codes = {"stocktake.read", "stocktake.review", "stocktake.approve",
                 "stocktake.recount", "dispatch.execute", "transfer.receive", "transfer.read"}
        await _ensure_permissions(db, codes)
        counter = await seed_ordinary_backoffice_fixture(db, a.company_id, password=PASSWORD)
        actor_driver = await db.get(Driver, counter.driver_id)
        a.counter = counter
        a.counter_username = actor_driver.username
        for actor in (a.actor, counter):
            for code in ("settlement.read", "settlement.execute"):
                await _grant_company(db, company_id=a.company_id,
                                     driver_id=actor.driver_id, code=code)
            await _grant_location(db, company_id=a.company_id, driver_id=actor.driver_id,
                location_id=a.vehicle_location, codes=("inventory.read", "stocktake.read",
                    "stocktake.start", "stocktake.count", "stocktake.review",
                    "stocktake.approve", "stocktake.recount", "dispatch.execute"))
        await _grant_location(db, company_id=a.company_id, driver_id=a.actor.driver_id,
            location_id=a.warehouse, codes=("dispatch.execute",))
        variant = await db.get(ProductVariant, a.variant)
        variant.packs_per_carton = 1
        earlier = utc_now() - timedelta(days=1)
        book = PriceBook(company_id=a.company_id, code="CLOSURE-PRICE",
            name="Closure locked price", currency_code="JOD", status="ACTIVE",
            created_by=a.actor.driver_id)
        db.add(book)
        await db.flush()
        publication = PricePublication(company_id=a.company_id, price_book_id=book.id,
            revision=1, status="PUBLISHED", effective_at=earlier, published_at=earlier,
            approved_at=earlier, approved_by=a.actor.driver_id, created_by=a.actor.driver_id,
            request_id=uuid4())
        db.add(publication)
        await db.flush()
        effectivity = Range(lower=earlier, upper=None, lower_inc=True)
        db.add_all([
            PriceBookEntry(company_id=a.company_id, price_book_id=book.id,
                publication_id=publication.id, product_variant_id=a.variant, uom_id=a.uom,
                amount=Decimal("5.000000"), effectivity=effectivity, is_published=True,
                priority=0, entry_metadata={}),
            PriceBookAssignment(company_id=a.company_id, price_book_id=book.id,
                scope_type="COMPANY_DEFAULT", scope_id=None, revision=1, priority=0,
                allow_offers=False, effectivity=effectivity, created_by=a.actor.driver_id),
        ])
        route = await db.scalar(select(DispatchRoute).where(
            DispatchRoute.company_id == a.company_id, DispatchRoute.work_session_id == a.work))
        context = RouteCommercialContext(company_id=a.company_id, dispatch_route_id=route.id,
            pricing_locked_at=utc_now(), price_publication_revision=1, assignment_revision=1,
            offer_ruleset_version=0, tax_ruleset_version=1,
            transaction_currency_code="JOD", functional_currency_code="JOD",
            rounding_policy_version=1, tenant_policy_revision=1)
        db.add(context)
        await db.flush()
        from models import WorkSession
        work = await db.get(WorkSession, a.work)
        work.commercial_context_id = context.id
        a.route, a.zone = route.id, route.zone_id
        tax = TaxRuleSet(company_id=a.company_id, code="CLOSURE-ZERO",
            name="Explicit zero tax", created_by=a.actor.driver_id)
        db.add(tax)
        await db.flush()
        aware = earlier.replace(tzinfo=timezone.utc)
        version = TaxRuleSetVersion(company_id=a.company_id, tax_rule_set_id=tax.id,
            revision=1, definition_version=1, status="PUBLISHED", priority=0,
            price_mode="EXCLUSIVE", effective_from=aware, request_id=uuid4(),
            created_by=a.actor.driver_id, approved_by=a.actor.driver_id,
            approved_at=aware, published_at=aware)
        db.add(version)
        await db.flush()
        db.add(TaxRuleComponent(company_id=a.company_id, tax_rule_set_version_id=version.id,
            component_code="ZERO", name="Zero", sequence=1, rate=Decimal("0"),
            basis_mode="TAXABLE_BASE"))
        await publish_commercial_rounding_policy(db, company_id=a.company_id,
            actor_id=a.actor.driver_id, expected_revision=0, precision=3, mode="HALF_UP")
        await db.commit()
    return closure


async def receive_exact(gate, tenant):
    command, _ = await receiving_command(gate, tenant)
    result = await custody(gate, tenant, body=command)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "CUSTODY_RECEIVED"
    return command


async def financial_effects(gate, tenant):
    async with gate.session(tenant) as db:
        return tuple((await db.execute(select(SystemAuditLog.id, SystemAuditLog.new_value).where(
            SystemAuditLog.company_id == tenant.company_id,
            SystemAuditLog.action_type == "FINANCIAL_SETTLEMENT")
            .order_by(SystemAuditLog.id))).all())


async def inventory_image(gate, tenant):
    """All persisted columns, not a projection that could hide metadata mutation."""
    async with gate.session(tenant) as db:
        result = {}
        for model in (InventoryBalance, InventoryMovement, SessionInventorySnapshot):
            rows = (await db.execute(select(*model.__table__.columns).where(
                model.company_id == tenant.company_id).order_by(model.id))).all()
            result[model.__tablename__] = tuple(map(tuple, rows))
        return result


async def test_financial_lost_response_requires_bound_original_success_replay(closure):
    a = closure.a
    await receive_exact(closure, a)  # never fabricate a received audit or sealed snapshot
    before = await evidence(closure, a)
    inventory_before = await inventory_image(closure, a)
    assert await financial_effects(closure, a) == ()
    body = {"request_id": str(uuid4()), "actual_cash": "0.000",
            "notes": "Stable financial command"}
    path = f"/admin/sessions/{a.work}/settle"
    original = None

    async def deliver_then_drop_response():
        nonlocal original
        original = await runtime_request(closure, a, method="PUT", path=path, body=body)
        assert original.status_code == 200, (
            "FINANCIAL_STABLE_ID_CONTRACT_REQUIRED: " + original.text)
        raise httpx.ReadTimeout("Synthetic response lost AFTER server commit")

    with pytest.raises(httpx.ReadTimeout):
        await deliver_then_drop_response()
    committed = await evidence(closure, a)
    assert committed.settled is True
    assert len(await financial_effects(closure, a)) == 1
    replay, concurrent_replay = await asyncio.gather(
        runtime_request(closure, a, method="PUT", path=path, body=body),
        runtime_request(closure, a, method="PUT", path=path, body=body))
    assert replay.status_code == concurrent_replay.status_code == 200
    assert replay.json() == concurrent_replay.json() == original.json()
    changed = await runtime_request(closure, a, method="PUT", path=path,
        body={**body, "actual_cash": "1.000", "notes": "Changed same-ID command"})
    fresh = await runtime_request(closure, a, method="PUT", path=path,
        body={**body, "request_id": str(uuid4())})
    assert changed.status_code == fresh.status_code == 409
    after = await evidence(closure, a)
    assert vars(after) == vars(committed)
    assert len(await financial_effects(closure, a)) == 1
    assert await inventory_image(closure, a) == inventory_before
    for key in ("balances", "movements", "snapshots", "seal"):
        assert getattr(after, key) == getattr(before, key)


async def business(gate, tenant, suffix, *, body=None, actor=None):
    return await runtime_request(gate, tenant, receiver=True, actor=actor,
        path=f"/admin/sessions/{tenant.work}/inventory-custody/{suffix}",
        method="POST" if body is not None else "GET", body=body)


async def test_independent_recount_approval_then_receiver_handoff_preserves_variance(journey):
    gate, a = journey, journey.a
    command, keys = await receiving_command(gate, a)
    command["items"] = [
        {**row, "actual_quantity": "3" if row["line_key"] == keys["DAMAGED"] else "6"}
        for row in command["items"]]
    variance = await custody(gate, a, body=command)
    assert variance.status_code == 200 and variance.json()["status"] == "REVIEW_REQUIRED"
    before = await evidence(gate, a)
    review = await business(gate, a, "variance")
    assert review.status_code == 200
    assert review.json()["requires_independent_recount"] is True
    damaged = next(r for r in review.json()["lines"] if r["stock_status"] == "DAMAGED")
    assert tuple(Decimal(damaged[k]) for k in (
        "expected_quantity", "actual_quantity", "variance_quantity")) == (4, 3, -1)
    approve = {"request_id": str(uuid4()), "password": PASSWORD}
    premature = await business(gate, a, "variance/approve", body=approve)
    assert premature.status_code == 409
    recount = await business(gate, a, "variance/recount", body={
        "request_id": str(uuid4()), "reason": "Independent physical receiving recount",
        "authorizer_username": a.counter_username, "authorizer_password": PASSWORD})
    assert recount.status_code == 200 and recount.json()["recount_authorized"] is True
    self_count = await business(gate, a, "variance/count-sheet")
    assert self_count.status_code in {403, 409}
    sheet = await business(gate, a, "variance/count-sheet", actor=a.counter)
    assert sheet.status_code == 200
    assert all("expected_quantity" not in r for r in sheet.json()["lines"])
    counted = await business(gate, a, "variance/count", actor=a.counter, body={
        "request_id": str(uuid4()),
        "items": [{"line_key": r["line_key"],
                   "actual_quantity": "3" if r["stock_status"] == "DAMAGED" else "6"}
                  for r in sheet.json()["lines"]]})
    assert counted.status_code == 200
    review = await business(gate, a, "variance")
    assert review.json()["independent_recount_satisfied"] is True
    assert (await financial(gate, a)).status_code == 409
    approved = await business(gate, a, "variance/approve", body=approve)
    assert approved.status_code == 200, approved.text
    assert approved.json()["receiver_must_confirm_handoff"] is True
    assert approved.json()["financial_ready"] is False
    adjusted = await evidence(gate, a)
    assert len(adjusted.movements) == len(before.movements) + 1
    assert (await financial(gate, a)).status_code == 409  # approval alone is not receiving
    receipt, _ = await receiving_command(gate, a)
    assert sorted(Decimal(r["actual_quantity"]) for r in receipt["items"]) == [3, 6]
    received = await custody(gate, a, body=receipt)
    assert received.status_code == 200 and received.json()["status"] == "CUSTODY_RECEIVED"
    async with gate.session(a) as db:
        history = (await db.execute(select(
            StocktakeCountAttemptLine.expected_quantity,
            StocktakeCountAttemptLine.actual_quantity,
            StocktakeCountAttemptLine.variance_quantity,
        ).join(StocktakeLine, StocktakeLine.id == StocktakeCountAttemptLine.stocktake_line_id)
         .join(StocktakeSession, StocktakeSession.id == StocktakeLine.stocktake_session_id)
         .where(StocktakeSession.company_id == a.company_id,
                StocktakeSession.related_work_session_id == a.work,
                StocktakeLine.stock_status == "DAMAGED"))).all()
        assert len(history) == 2 and all(tuple(r) == (4, 3, -1) for r in history)
        moves = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == a.company_id,
            InventoryMovement.work_session_id == a.work,
            InventoryMovement.reference_type == "REPRESENTATIVE_CUSTODY_RECEIPT"))).all()
        assert {(m.source_stock_status, m.destination_stock_status, Decimal(m.quantity))
                for m in moves} == {("AVAILABLE", "AVAILABLE", Decimal("6")),
                                   ("DAMAGED", "DAMAGED", Decimal("3"))}
    stock = await evidence(gate, a)
    inventory_before_finance = await inventory_image(gate, a)
    assert (await financial(gate, a)).status_code == 200
    closed = await evidence(gate, a)
    assert await inventory_image(gate, a) == inventory_before_finance
    for field in ("balances", "movements", "snapshots", "seal"):
        assert getattr(closed, field) == getattr(stock, field)


async def test_later_vehicle_reload_is_new_route_custody_not_closed_settlement_edit(journey):
    gate, a = journey, journey.a
    old_command = await receive_exact(gate, a)
    assert (await financial(gate, a)).status_code == 200
    closed = await evidence(gate, a)
    effects = await financial_effects(gate, a)
    launched = await runtime_request(gate, a, method="POST", path="/dispatch/route", body={
        "zone_id": a.zone, "driver_id": a.field.driver.id, "vehicle_id": a.vehicle,
        "source_location_id": a.warehouse, "inventory": {str(a.variant): 2}})
    assert launched.status_code == 201, launched.text
    async with gate.session(a) as db:
        routes = (await db.scalars(select(DispatchRoute).where(
            DispatchRoute.company_id == a.company_id,
            DispatchRoute.vehicle_id == a.vehicle).order_by(DispatchRoute.id))).all()
        assert len(routes) == 2 and routes[0].id == a.route
        assert routes[0].status == "closed" and routes[0].work_session_id == a.work
        new_route = routes[1]
        assert new_route.status == "active" and new_route.work_session_id is None
        loads = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == a.company_id,
            InventoryMovement.reference_type == "DISPATCH_LOAD",
            InventoryMovement.reference_id == str(new_route.id)))).all()
        assert len(loads) == 1 and loads[0].work_session_id is None
        assert loads[0].source_location_id == a.warehouse
        assert loads[0].destination_location_id == a.vehicle_location
        assert Decimal(loads[0].quantity) == 2 and loads[0].batch_id == a.batch
    after_reload = await evidence(gate, a)
    assert after_reload.snapshots == closed.snapshots and after_reload.seal == closed.seal
    assert after_reload.settled is True and await financial_effects(gate, a) == effects
    replay = await custody(gate, a, body=old_command)
    assert replay.status_code == 200  # recover old receipt even after later load
    fresh = await custody(gate, a, body={**old_command, "request_id": str(uuid4())})
    assert fresh.status_code == 409
    assert vars(await evidence(gate, a)) == vars(after_reload)


@pytest.mark.parametrize("purpose,source,target,hold", [
    ("QUARANTINE", "AVAILABLE", "QUARANTINED", "SALES_HOLD"),
    ("DISPOSAL", "AVAILABLE", "DISPOSAL_PENDING", "RECALL"),
    ("DISPOSAL", "DAMAGED", "DISPOSAL_PENDING", "NONE"),
    ("RETURN_TO_VENDOR", "DAMAGED", "DAMAGED", "NONE"),
])
async def test_first_quality_action_needs_no_setup_or_fake_warehouse(
    closure, purpose, source, target, hold,
):
    gate, a = closure, closure.a
    assert await policy_rows(gate, a) == ()
    async with gate.session(a) as db:
        before = await transfer_policy.get_transfer_destination_policy(db, a.actor.access(db))
        assert before["draft"] is None and before["published"] is None
    assert await policy_rows(gate, a) == ()  # opening is a pure read
    async with gate.session(a) as db:
        variant = await db.get(ProductVariant, a.variant)
        variant.operational_hold = hold
        await db.commit()
    command = SpecialTransferDispatchRequest(request_id=uuid4(), source_location_id=a.warehouse,
        transfer_purpose=purpose, notes="First operation, no prior setup",
        items=[dict(product_variant_id=a.variant, batch_id=a.batch, source_status=source,
                    quantity="2", uom_id=a.uom)])
    async def send(payload=command, actor=a.actor):
        async with gate.session(a) as db:
            return await transfers.special_transfer_dispatch(
                payload, db, actor.access(db), actor.operational_driver)
    with pytest.raises(HTTPException) as denied:
        await send(actor=a.denied)
    assert denied.value.status_code == 403 and await policy_rows(gate, a) == ()
    for forbidden in (a.vehicle_location, gate.b.warehouse):
        with pytest.raises(HTTPException) as rejected:
            await send(command.model_copy(update={"source_location_id": forbidden,
                                                  "request_id": uuid4()}))
        assert rejected.value.status_code in {403, 404}
    assert await policy_rows(gate, a) == ()
    # The fixture's Vehicle has transfer.send for custody, but not destination;
    # its special source must fail atomically, including any lazy default.
    response = await send()
    assert await send() == response
    assert response["source_location_id"] == response["destination_location_id"] == a.warehouse
    async with gate.session(a) as db:
        assert await db.scalar(select(func.count()).select_from(InventoryLocation).where(
            InventoryLocation.company_id == a.company_id,
            InventoryLocation.location_type == "WAREHOUSE")) == 1
        quantities = dict((await db.execute(select(
            InventoryBalance.stock_status, InventoryBalance.on_hand_quantity,
        ).where(InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.warehouse))).all())
        expected = {"AVAILABLE": Decimal("20"), "DAMAGED": Decimal("3")}
        expected[source] -= 2
        expected[target] = expected.get(target, Decimal("0")) + 2
        assert quantities == expected
    rows = await policy_rows(gate, a)
    assert len(rows) == 1 and rows[0].status == "PUBLISHED"
    assert await policy_rows(gate, gate.b) == ()


async def test_explicit_legacy_policy_read_and_real_routing_are_preserved(closure):
    gate, a = closure, closure.a
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        await _ensure_permissions(db, {"transfer.receive", "transfer.read"})
        destination = InventoryLocation(company_id=a.company_id, code="LEGACY-DEST",
            name="Real legacy destination", location_type="WAREHOUSE", is_active=True)
        db.add(destination)
        await db.flush()
        db.add(ProductLocation(company_id=a.company_id, location_id=destination.id,
                               product_variant_id=a.variant, created_by=a.actor.driver_id))
        await _grant_location(db, company_id=a.company_id, driver_id=a.actor.driver_id,
            location_id=destination.id, codes=("location.read", "inventory.read", "ledger.read",
                "transfer.read", "transfer.receive", "transfer.destination"))
        destination_id = destination.id
        variant = await db.get(ProductVariant, a.variant)
        variant.operational_hold = "RECALL"
        await db.commit()
    async with gate.session(a) as db:
        draft = await transfer_policy.save_transfer_destination_policy(
            TransferDestinationPolicySaveRequest(request_id=uuid4(), payload={
                "quarantine_location_id": destination_id, "disposal_location_id": destination_id,
                "vendor_return_staging_location_id": destination_id,
                "allow_retiring_warehouse_balancing": False,
            }), db, a.actor.access(db), a.actor.operational_driver)
        await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"],
            TransferDestinationPolicyPublishRequest(request_id=uuid4(),
                expected_revision=draft["policy"]["revision"]),
            db, a.actor.access(db), a.actor.operational_driver)
    original = await policy_rows(gate, a)
    async with gate.session(a) as db:
        view = await transfer_policy.get_transfer_destination_policy(db, a.actor.access(db))
        assert set(view["published"]["validated_payload"].values()) == {destination_id, False}
    assert await policy_rows(gate, a) == original
    async with gate.session(a) as db:
        sent = await transfers.special_transfer_dispatch(SpecialTransferDispatchRequest(
            request_id=uuid4(), source_location_id=a.warehouse, transfer_purpose="DISPOSAL",
            notes="Existing explicit route", items=[dict(product_variant_id=a.variant,
                batch_id=a.batch, source_status="AVAILABLE", quantity="2", uom_id=a.uom)]),
            db, a.actor.access(db), a.actor.operational_driver)
        assert sent["destination_location_id"] == destination_id
        await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=uuid4(),
            transfer_header_id=sent["header_id"], destination_location_id=destination_id),
            db, a.actor.access(db), a.actor.operational_driver)
        balance = await db.scalar(select(InventoryBalance).where(
            InventoryBalance.company_id == a.company_id,
            InventoryBalance.location_id == destination_id,
            InventoryBalance.batch_id == a.batch,
            InventoryBalance.stock_status == "DISPOSAL_PENDING"))
        assert Decimal(balance.on_hand_quantity) == 2
    assert await policy_rows(gate, a) == original


async def test_full_app_registers_the_complete_receiver_journey():
    from main import app
    base = "/admin/sessions/{session_id}/inventory-custody"
    actual = {(route.path, method) for route in app.routes
              for method in getattr(route, "methods", set())}
    required = {(base, "GET"), (base + "/receive", "POST"),
                (base + "/variance", "GET"), (base + "/variance/recount", "POST"),
                (base + "/variance/count-sheet", "GET"),
                (base + "/variance/count", "POST"), (base + "/variance/approve", "POST"),
                ("/admin/sessions/{session_id}/settle", "PUT")}
    assert required <= actual, "Combined candidate lacks actual full-app route wiring"


async def test_quality_policy_permission_tenant_and_explicit_reference_scope_are_exact(closure):
    gate, a = closure, closure.a
    async with gate.session(a) as db:
        with pytest.raises(HTTPException) as denied:
            await transfer_policy.get_transfer_destination_policy(db, a.denied.access(db))
        assert denied.value.status_code == 403
    signatures = []
    for reference in (gate.b.warehouse, 2_147_483_647):
        async with gate.session(a) as db:
            with pytest.raises(HTTPException) as rejected:
                await transfer_policy.save_transfer_destination_policy(
                    TransferDestinationPolicySaveRequest(request_id=uuid4(), payload={
                        "quarantine_location_id": reference, "disposal_location_id": reference,
                        "vendor_return_staging_location_id": reference,
                        "allow_retiring_warehouse_balancing": False,
                    }), db, a.actor.access(db), a.actor.operational_driver)
            detail = rejected.value.detail
            signatures.append((rejected.value.status_code,
                               detail.get("code") if isinstance(detail, dict) else detail))
    assert signatures[0] == signatures[1] and signatures[0][0] in {403, 404}
    assert await policy_rows(gate, a) == ()
    async with gate.session(a) as db:
        await transfer_policy.save_transfer_destination_policy(
            TransferDestinationPolicySaveRequest(request_id=uuid4(), payload={
                "quarantine_location_id": a.warehouse, "disposal_location_id": a.warehouse,
                "vendor_return_staging_location_id": a.warehouse,
                "allow_retiring_warehouse_balancing": False,
            }), db, a.actor.access(db), a.actor.operational_driver)
    original = await policy_rows(gate, a)
    async with gate.session(gate.b) as db:
        view = await transfer_policy.get_transfer_destination_policy(db, gate.b.actor.access(db))
        assert view["draft"] is None and view["published"] is None
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        roles = select(role_permissions.c.role_id).join(
            Permission, Permission.id == role_permissions.c.permission_id,
        ).where(role_permissions.c.company_id == a.company_id, Permission.code == "location.read")
        await db.execute(UserLocationAccess.__table__.delete().where(
            UserLocationAccess.company_id == a.company_id,
            UserLocationAccess.driver_id == a.actor.driver_id,
            UserLocationAccess.location_id == a.warehouse,
            UserLocationAccess.role_id.in_(roles)))
        await db.commit()
    async with gate.session(a) as db:
        with pytest.raises(HTTPException) as location_denied:
            await transfer_policy.get_transfer_destination_policy(db, a.actor.access(db))
        assert location_denied.value.status_code == 403
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        roles = select(role_permissions.c.role_id).join(
            Permission, Permission.id == role_permissions.c.permission_id,
        ).where(role_permissions.c.company_id == a.company_id,
                Permission.code == "inventory.transfer_policy.manage")
        await db.execute(UserRole.__table__.delete().where(
            UserRole.company_id == a.company_id, UserRole.driver_id == a.actor.driver_id,
            UserRole.role_id.in_(roles)))
        await db.commit()
    async with gate.session(a) as db:
        with pytest.raises(HTTPException) as capability_denied:
            await transfer_policy.get_transfer_destination_policy(db, a.actor.access(db))
        assert capability_denied.value.status_code == 403
    assert await policy_rows(gate, a) == original
