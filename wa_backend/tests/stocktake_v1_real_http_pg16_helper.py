"""One real bearer → FastAPI → restricted PG16 Stocktake V1 journey.

Invoked by CP14-C's existing disposable-database test after the accepted
canonical fixture has completed. This is not a mocked dependency/unit route.
No business tables are seeded via InventoryBalance writes, and no production
database may be selected.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import auth
from api.warehouse import ledger, live_stock, stocktake
from config import Config
from domains.auth_sessions.codec import issue_access_token
from domains.identity.models import CompanyPrincipal
from domains.live_stock_projection.service import rebuild_live_stock_company
from models import (
    Company, Driver, InventoryBalance, InventoryCostEvent, InventoryCostState,
    InventoryLock, InventoryMovement, ProductBatch, StocktakeSession,
    StocktakeCountAttempt, SystemAuditLog, SystemSetting,
)


def _body_id():
    return str(uuid4())


def _check(response, status=200):
    assert response.status_code == status, (
        response.request.method, str(response.request.url),
        response.status_code, response.text[:800],
    )
    return response.json()


async def assert_real_http_stocktake(
    *,
    runtime_engine,
    admin_engine,
    a,
    b,
    earlier_discovered_batch_id: int,
    runtime_session,
    grant_location,
    operator_password: str,
    recounter_password: str,
):
    # Keep seed writes test-only. An *already registered* physical Lot is
    # discovered through the normal API. Neither the test nor the HTTP
    # endpoint may invent a Batch or directly credit InventoryBalance.
    async with AsyncSession(admin_engine, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"),
                         {"c": str(a.company_id)})
        await grant_location(
            db, company_id=a.company_id, driver_id=a.counter.driver_id,
            location_id=a.a2,
            codes=("stocktake.read", "stocktake.count", "stocktake.recount"),
        )
        new_batch = ProductBatch(
            company_id=a.company_id, product_variant_id=a.variant,
            batch_number="CP14C-HTTP-DISCOVERED-" + uuid4().hex,
            production_date=date(2024, 12, 1), expiry_date=date(2025, 1, 1),
        )
        db.add(new_batch)
        await db.flush()
        new_batch_id = int(new_batch.id)
        company = await db.get(Company, a.company_id)
        assert company is not None
        company_code = company.company_code
        operator_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == a.operator.context.principal_id,
            CompanyPrincipal.company_id == a.company_id,
        ))
        recounter_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == a.counter.context.principal_id,
            CompanyPrincipal.company_id == a.company_id,
        ))
        authorizer_legacy_username = await db.scalar(select(Driver.username).where(
            Driver.company_id == a.company_id,
            Driver.id == a.counter.driver_id,
        ))
        operator_legacy_username = await db.scalar(select(Driver.username).where(
            Driver.company_id == a.company_id,
            Driver.id == a.operator.driver_id,
        ))
        assert operator_name and recounter_name and authorizer_legacy_username and operator_legacy_username
        await db.commit()

    # Rebuild only this disposable company through the real canonical
    # projection API so Live Stock can be read with a READY v2 read model.
    async with runtime_session(runtime_engine, a.company_id) as db:
        await rebuild_live_stock_company(db, company_id=a.company_id)
        await db.commit()
        # Independent test fixture truth, not visible to the blind count UI.
        # Other snapshot lines must be counted at exactly their physical
        # amounts; never guess an earlier transfer result.
        physical_before = {
            (int(balance.batch_id), balance.stock_status):
                Decimal(balance.on_hand_quantity)
            for balance in (await db.scalars(select(InventoryBalance).where(
                InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.a2,
                InventoryBalance.product_variant_id == a.variant,
                InventoryBalance.on_hand_quantity > 0,
            ))).all()
        }
    old_key = (earlier_discovered_batch_id, "QUARANTINED")
    assert physical_before[old_key] == Decimal("1.000"), physical_before
    total_before = sum(physical_before.values(), Decimal("0"))

    # Production routers + production auth dependencies. In particular, do
    # NOT override get_db, bearer decoding, capability checks or legacy map.
    # Config.DATABASE_URL points to cp14c_app, restricted NOBYPASSRLS role.
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(stocktake.router)
    app.include_router(live_stock.router)
    app.include_router(ledger.router)

    base = "/warehouse/unified/stocktake"
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://stocktake-cp14c.test",
                           timeout=30.0) as client:
        _check(await client.get("/warehouse/unified/stocktakes/active",
                                params={"location_id": a.a2}), 401)
        login = _check(await client.post("/login", json={
            "company_code": company_code,
            "username": operator_name,
            "password": operator_password,
        }))
        auth_header = {"Authorization": "Bearer " + login["token"]}
        recount_login = _check(await client.post("/login", json={
            "company_code": company_code,
            "username": recounter_name,
            "password": recounter_password,
        }))
        recount_header = {"Authorization": "Bearer " + recount_login["token"]}
        # Signed with the same production codec but never admitted by public
        # login: persisted no-grant principal must fail the real 403 guard.
        denied_token = issue_access_token(
            principal_id=a.denied.context.principal_id,
            company_id=a.company_id,
            channel="DASHBOARD",
            principal_type="BACKOFFICE",
            auth_revision=a.denied.context.auth_revision,
            secret=Config.SECRET_KEY,
        )
        denied_header = {"Authorization": "Bearer " + denied_token}
        _check(await client.get("/warehouse/unified/stocktakes/active",
                                params={"location_id": a.a2},
                                headers=denied_header), 403)
        foreign = await client.get("/warehouse/unified/stocktakes/active",
                                   params={"location_id": b.a1},
                                   headers=auth_header)
        assert foreign.status_code in {403, 404}, foreign.text
        _check(await client.get("/warehouse/unified/stocktakes/active",
                                params={"location_id": a.a2},
                                headers=auth_header))

        starting = {
            "request_id": _body_id(),
            "location_id": a.a2,
            "stocktake_type": "CYCLE_COUNT",
            "product_variant_id": a.variant,
            "notes": "CP14C real bearer ASGI cycle-count proof",
        }
        started = _check(await client.post(base + "/start",
                                            json=starting, headers=auth_header), 201)
        sid = int(started["session_id"])
        assert _check(await client.post(base + "/start",
                                        json=starting, headers=auth_header), 201) == started
        wrong_start = {**starting, "notes": "mutated replay is forbidden"}
        _check(await client.post(base + "/start", json=wrong_start,
                                 headers=auth_header), 409)
        sheet = _check(await client.get(f"{base}/{sid}/count-sheet",
                                        headers=auth_header))
        assert len(sheet) == len(physical_before) and all(
            "expected_quantity" not in row and
            int(row["base_uom_id"]) == a.uom for row in sheet
        ), sheet
        # Registered exact outer UOM is read-only display metadata. Every
        # physical batch/status line keeps the same canonical base identity.
        assert all({
            key: row[key] for key in row if key.startswith("count_outer_")
        } == {
            "count_outer_uom_id": a.outer_uom,
            "count_outer_uom_name": "CP14C Box",
            "count_outer_uom_code": "CP14C_BOX",
            "count_outer_factor_numerator": 50,
            "count_outer_factor_denominator": 1,
        } for row in sheet), sheet
        assert {(int(row["batch_id"]), row["stock_status"]) for row in sheet} == set(physical_before)
        assert any(int(row["batch_id"]) == earlier_discovered_batch_id
                   for row in sheet)
        options = _check(await client.get(
            f"{base}/{sid}/discovery-options",
            params={"product_variant_id": a.variant, "limit": 100},
            headers=auth_header,
        ))
        assert any(int(item["id"]) == new_batch_id for item in options["items"])
        assert all(
            row["count_outer_uom_id"] == a.outer_uom
            and row["count_outer_factor_numerator"] == 50
            and row["count_outer_factor_denominator"] == 1
            for row in options["items"]
        )
        assert all("expected_quantity" not in row for row in options["items"])
        zero_items = []
        for row in sheet:
            # An explicit 0 is a real physical count, not an omitted line.
            key = (int(row["batch_id"]), row["stock_status"])
            quantity = ("0.000" if key == old_key
                        else format(physical_before[key], "f"))
            zero_items.append({
                "product_variant_id": row["product_variant_id"],
                "batch_id": row["batch_id"],
                "stock_status": row["stock_status"],
                "uom_id": row["base_uom_id"],
                "actual_quantity": quantity,
            })
        discovered = {
            "product_variant_id": a.variant, "batch_id": new_batch_id,
            "stock_status": "QUARANTINED", "uom_id": a.uom,
            "actual_quantity": "1.000",
        }
        submission = {"request_id": _body_id(),
                      "items": [*zero_items, discovered],
                      "notes": "Zero + physically discovered registered Lot"}
        # Safe rejection: a Lot absent from the genuine product registry
        # cannot create an inventory adjustment.
        forged = {
            "request_id": _body_id(),
            "items": [*zero_items, {**discovered, "batch_id": 2147000000}],
        }
        invalid = await client.post(f"{base}/{sid}/count", json=forged,
                                    headers=auth_header)
        assert invalid.status_code in {400, 404, 409, 422}, invalid.text
        submitted = _check(await client.post(f"{base}/{sid}/count",
                                              json=submission, headers=auth_header))
        assert submitted["status"] == "PENDING_REVIEW"
        assert _check(await client.post(f"{base}/{sid}/count",
                                        json=submission, headers=auth_header)) == submitted
        assert (await client.post(f"{base}/{sid}/count",
                                  json={**submission, "notes": "changed body"},
                                  headers=auth_header)).status_code == 409
        reviewed = _check(await client.get(f"{base}/{sid}/review",
                                           headers=auth_header))
        assert any(line["line_origin"] == "DISCOVERED" and
                   int(line["batch_id"]) == new_batch_id
                   for line in reviewed["lines"])
        assert any(int(line["batch_id"]) == earlier_discovered_batch_id and
                   Decimal(line["actual_quantity"]) == 0
                   for line in reviewed["lines"])
        assert reviewed["latest_attempt"]["requires_independent_recount"] is True
        first_attempt = int(reviewed["latest_attempt"]["id"])
        premature = await client.post(f"{base}/{sid}/approve", json={
            "request_id": _body_id(),
            "count_attempt_id": first_attempt,
            "password": operator_password,
        }, headers=auth_header)
        assert premature.status_code in {403, 409}, premature.text
        recounted = _check(await client.post(f"{base}/{sid}/recount", json={
            "request_id": _body_id(),
            "count_attempt_id": first_attempt,
            "reason": "Independent physical recount for zero stock",
            "authorizer_username": authorizer_legacy_username,
            "authorizer_password": recounter_password,
        }, headers=auth_header))
        assert recounted["requires_independent_counter"] is True
        assert (await client.get(f"{base}/{sid}/count-sheet",
                                 headers=auth_header)).status_code == 403
        recount_sheet = _check(await client.get(f"{base}/{sid}/count-sheet",
                                               headers=recount_header))
        assert all(
            row["count_outer_factor_numerator"] == 50 and
            row["base_uom_id"] == a.uom and
            "expected_quantity" not in row
            for row in recount_sheet
        )
        recount_items = []
        for row in recount_sheet:
            batch_id = int(row["batch_id"])
            key = (batch_id, row["stock_status"])
            quantity = ("0.000" if key == old_key
                        else "1.000" if batch_id == new_batch_id
                        else format(physical_before[key], "f"))
            recount_items.append({
                "product_variant_id": row["product_variant_id"],
                "batch_id": row["batch_id"],
                "stock_status": row["stock_status"],
                "uom_id": row["base_uom_id"],
                "actual_quantity": quantity,
            })
        assert len(recount_items) == len(submission["items"])
        recount_submission = _check(await client.post(f"{base}/{sid}/count",
                                      json={"request_id": _body_id(),
                                            "items": recount_items},
                                      headers=recount_header))
        assert recount_submission["status"] == "PENDING_REVIEW"
        second_review = _check(await client.get(f"{base}/{sid}/review",
                                                headers=auth_header))
        assert second_review["independent_recount_satisfied"] is True
        assert len(second_review["attempt_history"]) == 2
        assert int(second_review["latest_attempt"]["id"]) == int(recount_submission["attempt_id"])

        approval = {
            "request_id": _body_id(),
            "count_attempt_id": recount_submission["attempt_id"],
            "password": operator_password,
            "notes": "CP14C HTTP restricted role final approval",
        }
        approved = _check(await client.post(f"{base}/{sid}/approve",
                                            json=approval, headers=auth_header))
        assert approved["status"] == "POSTED"
        assert int(approved["movement_count"]) == 2, {"approval": approved, "review_lines": second_review["lines"]}
        assert _check(await client.post(f"{base}/{sid}/approve",
                                        json=approval, headers=auth_header)) == approved
        locked_after = await client.get(f"{base}/{sid}/count-sheet",
                                        headers=auth_header)
        assert locked_after.status_code == 409

        # Read Live Stock and Ledger via real HTTP, then independently verify
        # exact physical lot quantities, unique movements and cost invariants
        # from the restricted SQL role; no test-inserted InventoryBalance rows.
        page = _check(await client.get("/warehouse/inventory/cursor",
                                        params={"location_id": a.a2, "limit": 50,
                                                "view": "warehouse"},
                                        headers=auth_header))
        stock = next(item for item in page["items"]
                     if int(item["id"]) == a.variant)
        assert stock["total_quantity_scope"] == "WAREHOUSE_PHYSICAL"
        assert Decimal(stock["on_hand_quantity"]) == total_before - physical_before[old_key] + Decimal("1.000")
        ledger_page = _check(await client.get("/warehouse/ledger/cursor",
                                               params={"location_id": a.a2,
                                                       "reference_type": "AUDIT_ADJUSTMENT",
                                                       "limit": 50},
                                               headers=auth_header))
        async with runtime_session(runtime_engine, a.company_id) as db:
            moves = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == a.company_id,
                InventoryMovement.stocktake_session_id == sid,
            ))).all()
            assert len(moves) == 2
            assert {(m.batch_id, Decimal(m.quantity),
                     m.source_location_id, m.destination_location_id)
                     for m in moves} == {
                (earlier_discovered_batch_id, physical_before[old_key], a.a2, None),
                (new_batch_id, Decimal("1.000"), None, a.a2),
            }
            assert {m.id for m in moves} <= {
                int(row["id"]) for row in ledger_page["items"]
            }
            old_qty = await db.scalar(select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.a2,
                InventoryBalance.product_variant_id == a.variant,
                InventoryBalance.batch_id == earlier_discovered_batch_id,
                InventoryBalance.stock_status == "QUARANTINED",
            ))
            new_qty = await db.scalar(select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.a2,
                InventoryBalance.product_variant_id == a.variant,
                InventoryBalance.batch_id == new_batch_id,
                InventoryBalance.stock_status == "QUARANTINED",
            ))
            assert (Decimal(old_qty or 0), Decimal(new_qty or 0)) == (
                Decimal("0"), Decimal("1.000"))
            assert int(await db.scalar(select(func.count(InventoryLock.id)).where(
                InventoryLock.company_id == a.company_id,
                InventoryLock.stocktake_session_id == sid,
                InventoryLock.released_at.is_(None),
            ))) == 0
            costs = (await db.scalars(select(InventoryCostEvent).where(
                InventoryCostEvent.company_id == a.company_id,
                InventoryCostEvent.inventory_movement_id.in_([m.id for m in moves]),
            ))).all()
            assert len({c.inventory_movement_id for c in costs}) == len(costs)
            assert all(Decimal(c.total_cost) >= 0 for c in costs)
            state = await db.scalar(select(InventoryCostState).where(
                InventoryCostState.company_id == a.company_id,
                InventoryCostState.product_variant_id == a.variant,
            ))
            if state is not None:
                assert Decimal(state.quantity) >= 0
                assert Decimal(state.inventory_value) >= 0
                assert Decimal(state.average_unit_cost) >= 0

        # Cancellation is a separate, terminal HTTP command: no posting.
        cancel_start = _check(await client.post(base + "/start", json={
            **starting, "request_id": _body_id(),
            "notes": "CP14C HTTP cancel after posted session",
        }, headers=auth_header), 201)
        cancel_id = int(cancel_start["session_id"])
        cancellation = {"request_id": _body_id(), "password": operator_password,
                        "reason": "Cancelled isolated HTTP test session"}
        done = _check(await client.post(f"{base}/{cancel_id}/cancel",
                                        json=cancellation, headers=auth_header))
        assert done["status"] == "CANCELLED"
        assert _check(await client.post(f"{base}/{cancel_id}/cancel",
                                        json=cancellation, headers=auth_header)) == done
        async with runtime_session(runtime_engine, a.company_id) as db:
            assert int(await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == a.company_id,
                InventoryMovement.stocktake_session_id == cancel_id,
            ))) == 0
            assert int(await db.scalar(select(func.count(InventoryLock.id)).where(
                InventoryLock.company_id == a.company_id,
                InventoryLock.stocktake_session_id == cancel_id,
                InventoryLock.released_at.is_(None),
            ))) == 0

        # #798: The previously submitted mandatory attempt is immutable even
        # when the company's explicit policy is later removed. Test-only
        # configuration changes use the ADMIN role, never a runtime stock write.
        async with AsyncSession(admin_engine, expire_on_commit=False) as config_db:
            await config_db.execute(text(
                "SELECT set_config('app.current_tenant', :company, true)"
            ), {"company": str(a.company_id)})
            configured = (await config_db.scalars(select(SystemSetting).where(
                SystemSetting.company_id == a.company_id,
                SystemSetting.setting_key == "stocktake_material_shortage_packs",
            ))).all()
            assert len(configured) == 1 and configured[0].setting_value == "0"
            historical = await config_db.get(StocktakeCountAttempt, first_attempt)
            assert historical is not None and historical.requires_independent_recount is True
            await config_db.execute(delete(SystemSetting).where(
                SystemSetting.company_id == a.company_id,
                SystemSetting.setting_key == "stocktake_material_shortage_packs",
            ))
            await config_db.commit()
            historical = await config_db.get(StocktakeCountAttempt, first_attempt)
            assert historical is not None and historical.requires_independent_recount is True

        # One single *operating* account performs start, blind count, review,
        # approval and optional recount. Other preseeded actors are not used.
        # No policy settings remain for company A.
        first_optional = _check(await client.post(base + "/start", json={
            "request_id": _body_id(),
            "location_id": a.a2,
            "stocktake_type": "CYCLE_COUNT",
            "product_variant_id": a.variant,
            "batch_id": new_batch_id,
            "notes": "Single operator optional policy direct approval",
        }, headers=auth_header), 201)
        optional_sid = int(first_optional["session_id"])
        # The protected review must never disclose expected stock before
        # a genuine count attempt has been submitted and committed.
        blind_review = await client.get(
            f"{base}/{optional_sid}/review", headers=auth_header)
        assert blind_review.status_code == 409
        optional_sheet = _check(await client.get(f"{base}/{optional_sid}/count-sheet",
                                               headers=auth_header))
        assert len(optional_sheet) == 1
        assert optional_sheet[0]["stock_status"] == "QUARANTINED"
        assert "expected_quantity" not in optional_sheet[0]
        optional_zero = _check(await client.post(f"{base}/{optional_sid}/count", json={
            "request_id": _body_id(),
            "items": [{
                "product_variant_id": optional_sheet[0]["product_variant_id"],
                "batch_id": optional_sheet[0]["batch_id"],
                "stock_status": optional_sheet[0]["stock_status"],
                "uom_id": optional_sheet[0]["base_uom_id"],
                "actual_quantity": "0.000",
            }],
        }, headers=auth_header))
        assert optional_zero["requires_independent_recount"] is False
        optional_review = _check(await client.get(f"{base}/{optional_sid}/review",
                                               headers=auth_header))
        assert optional_review["latest_attempt"]["requires_independent_recount"] is False
        assert optional_review["independent_recount_satisfied"] is True
        assert Decimal(optional_review["lines"][0]["variance_quantity"]) == Decimal("-1.000")

        forbidden_approval = await client.post(f"{base}/{optional_sid}/approve", json={
            "request_id": _body_id(),
            "count_attempt_id": optional_zero["attempt_id"],
            "password": operator_password,
        }, headers=denied_header)
        assert forbidden_approval.status_code == 403
        wrong_password = await client.post(f"{base}/{optional_sid}/approve", json={
            "request_id": _body_id(),
            "count_attempt_id": optional_zero["attempt_id"],
            "password": "NotTheActualOperatorPassword",
        }, headers=auth_header)
        assert wrong_password.status_code == 403
        foreign_review = await client.get(f"{base}/{optional_sid}/review",
                                          headers=denied_header)
        assert foreign_review.status_code == 403
        wrong_company = await client.get("/warehouse/unified/stocktakes/active",
                                         params={"location_id": b.a1},
                                         headers=auth_header)
        assert wrong_company.status_code in {403, 404}

        approval_once = {
            "request_id": _body_id(),
            "count_attempt_id": optional_zero["attempt_id"],
            "password": operator_password,
            "notes": "Single authorized account confirms physically absent batch",
        }
        direct = _check(await client.post(f"{base}/{optional_sid}/approve",
                                          json=approval_once, headers=auth_header))
        assert direct["status"] == "POSTED" and direct["movement_count"] == 1
        assert _check(await client.post(f"{base}/{optional_sid}/approve",
                                        json=approval_once, headers=auth_header)) == direct
        async with runtime_session(runtime_engine, a.company_id) as db:
            direct_moves = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == a.company_id,
                InventoryMovement.stocktake_session_id == optional_sid,
            ))).all()
            assert len(direct_moves) == 1
            assert Decimal(direct_moves[0].quantity) == Decimal("1.000")
            direct_audits = (await db.scalars(select(SystemAuditLog.action_type).where(
                SystemAuditLog.company_id == a.company_id,
                SystemAuditLog.target_id == f"Stocktake_{optional_sid}",
            ))).all()
            assert "STOCKTAKE_APPROVAL_REJECTED" in direct_audits
            assert "STOCKTAKE_APPROVED_AND_POSTED" in direct_audits
            current_a2 = await db.scalar(select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.a2,
                InventoryBalance.product_variant_id == a.variant,
                InventoryBalance.batch_id == a.batch,
                InventoryBalance.stock_status == "AVAILABLE",
            ))
            assert current_a2 is not None and Decimal(current_a2) > Decimal("0.125")
            physical_a2 = Decimal(current_a2)

        new_optional = _check(await client.post(base + "/start", json={
            "request_id": _body_id(),
            "location_id": a.a2,
            "stocktake_type": "CYCLE_COUNT",
            "product_variant_id": a.variant,
            "batch_id": a.batch,
            "notes": "Single account optional recount of other physical lot",
        }, headers=auth_header), 201)
        optional_recount_sid = int(new_optional["session_id"])
        forbidden_precount_review = await client.get(
            f"{base}/{optional_recount_sid}/review", headers=auth_header)
        assert forbidden_precount_review.status_code == 409
        blind_sheet = _check(await client.get(f"{base}/{optional_recount_sid}/count-sheet",
                                             headers=auth_header))
        assert len(blind_sheet) == 1 and "expected_quantity" not in blind_sheet[0]
        next_qty = format(physical_a2 - Decimal("0.125"), "f")
        row = {
            "product_variant_id": blind_sheet[0]["product_variant_id"],
            "batch_id": blind_sheet[0]["batch_id"],
            "stock_status": blind_sheet[0]["stock_status"],
            "uom_id": blind_sheet[0]["base_uom_id"],
            "actual_quantity": next_qty,
        }
        first_recount_attempt = _check(await client.post(
            f"{base}/{optional_recount_sid}/count", json={
                "request_id": _body_id(), "items": [row],
            }, headers=auth_header))
        assert first_recount_attempt["requires_independent_recount"] is False
        before_recount = _check(await client.get(
            f"{base}/{optional_recount_sid}/review", headers=auth_header))
        assert before_recount["latest_attempt"]["requires_independent_recount"] is False
        assert Decimal(before_recount["lines"][0]["variance_quantity"]) == Decimal("-0.125")

        recount_body = {
            "request_id": _body_id(),
            "count_attempt_id": first_recount_attempt["attempt_id"],
            "reason": "Same authorized account physically verifies discrepancy",
            "authorizer_username": operator_legacy_username,
            "authorizer_password": operator_password,
        }
        forbidden_recount = await client.post(
            f"{base}/{optional_recount_sid}/recount",
            json=recount_body, headers=denied_header)
        assert forbidden_recount.status_code == 403
        # This other actor has stocktake.recount only at A1, not A2.
        # A valid role at the wrong location is still forbidden.
        wrong_location_recount = await client.post(
            f"{base}/{optional_recount_sid}/recount",
            json={**recount_body, "request_id": _body_id()},
            headers=recount_header)
        assert wrong_location_recount.status_code == 403
        wrong_recount = await client.post(
            f"{base}/{optional_recount_sid}/recount",
            json={**recount_body, "request_id": _body_id(),
                  "authorizer_password": "WrongPassword"},
            headers=auth_header)
        assert wrong_recount.status_code == 403
        permitted = _check(await client.post(
            f"{base}/{optional_recount_sid}/recount", json=recount_body,
            headers=auth_header))
        assert permitted["status"] == "RECOUNT_REQUIRED"
        assert permitted["requires_independent_counter"] is False
        assert _check(await client.post(
            f"{base}/{optional_recount_sid}/recount", json=recount_body,
            headers=auth_header)) == permitted
        same_actor_sheet = _check(await client.get(
            f"{base}/{optional_recount_sid}/count-sheet", headers=auth_header))
        assert len(same_actor_sheet) == 1 and "expected_quantity" not in same_actor_sheet[0]
        second_attempt = _check(await client.post(
            f"{base}/{optional_recount_sid}/count",
            json={"request_id": _body_id(), "items": [row]},
            headers=auth_header))
        assert second_attempt["attempt_number"] == 2
        reviewed_again = _check(await client.get(
            f"{base}/{optional_recount_sid}/review", headers=auth_header))
        assert reviewed_again["independent_recount_satisfied"] is True
        assert len(reviewed_again["attempt_history"]) == 2
        assert reviewed_again["attempt_history"][0]["counted_by"] == reviewed_again["attempt_history"][1]["counted_by"]
        assert reviewed_again["attempt_history"][1]["recount_of_attempt_id"] == first_recount_attempt["attempt_id"]
        assert reviewed_again["attempt_history"][1]["recount_reason"] == recount_body["reason"]
        approved_recount = _check(await client.post(
            f"{base}/{optional_recount_sid}/approve", json={
                "request_id": _body_id(),
                "count_attempt_id": second_attempt["attempt_id"],
                "password": operator_password,
            }, headers=auth_header))
        assert approved_recount["status"] == "POSTED"
        assert approved_recount["movement_count"] == 1

        async with runtime_session(runtime_engine, a.company_id) as db:
            moves = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == a.company_id,
                InventoryMovement.stocktake_session_id == optional_recount_sid,
            ))).all()
            assert len(moves) == 1
            assert Decimal(moves[0].quantity) == Decimal("0.125")
            attempts = (await db.scalars(select(StocktakeCountAttempt).where(
                StocktakeCountAttempt.company_id == a.company_id,
                StocktakeCountAttempt.stocktake_session_id == optional_recount_sid,
            ).order_by(StocktakeCountAttempt.attempt_number))).all()
            assert len(attempts) == 2
            assert attempts[0].counted_by == attempts[1].counted_by == a.operator.driver_id
            assert attempts[0].requires_independent_recount is False
            audit_actions = (await db.scalars(select(SystemAuditLog.action_type).where(
                SystemAuditLog.company_id == a.company_id,
                SystemAuditLog.target_id == f"Stocktake_{optional_recount_sid}",
            ))).all()
            assert "STOCKTAKE_RECOUNT_AUTH_REJECTED" in audit_actions
            assert "STOCKTAKE_RECOUNT_AUTHORIZED" in audit_actions
            assert "STOCKTAKE_APPROVED_AND_POSTED" in audit_actions
        print("STOCKTAKE_798_OPTIONAL_SAME_AUTHORIZED_ACCOUNT_HTTP_PG16=PASS")

    print("CP14C_REAL_ASGI_BEARER_HTTP_START_ZERO_DISCOVERED_RECOUNT_APPROVE_LEDGER=PASS")
