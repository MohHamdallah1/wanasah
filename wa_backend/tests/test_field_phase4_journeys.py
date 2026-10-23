"""Committed replay, mixed decisions and cross-surface business evidence.

These are server integration tests using the same wire payloads as Flutter.
Discarding a successful response models a lost response, not a physical device.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryBalance, Visit
from tests.field_phase4_fixture import (
    scene, call, completed_replay_revocation, evidence, new_transfers,
    no_effect, posted, sale,
)

pytestmark = pytest.mark.asyncio


async def exact_money(invoice):
    assert invoice["currency_code"] == "JOD"
    assert invoice["rounding"]["precision"] == 3
    assert invoice["rounding"]["mode"] in ("HALF_UP", "HALF_EVEN")
    for amount in invoice["totals"].values():
        assert type(amount) is str
        assert Decimal(amount).is_finite()
    for line in invoice["lines"]:
        for key in ("gross_amount", "discount_amount", "tax_amount", "final_amount"):
            assert type(line[key]) is str and Decimal(line[key]).is_finite()


async def test_completed_visit_replay_requires_current_grant_with_unchanged_token(scene):
    g = scene
    command = sale(g)
    response = await posted(g, "PUT", f"/visits/{g.visit}", command)
    await completed_replay_revocation(g, "PUT", f"/visits/{g.visit}", command, response)


async def test_completed_shop_replay_requires_current_grant_with_unchanged_token(scene):
    g = scene
    command = {"request_id": str(uuid4()), "name": "P4 synthetic shop",
               "phone_number": uuid4().hex[:15], "latitude": 31.9, "longitude": 35.9}
    response = await posted(g, "POST", "/shops", command, 201)
    await completed_replay_revocation(g, "POST", "/shops", command, response)


@pytest.mark.parametrize("decisions", [
    ["accepted"], ["rejected"], ["accepted", "accepted"],
    ["rejected", "rejected"], ["accepted", "rejected"],
])
async def test_completed_transfer_decisions_require_current_grants_even_for_exact_replay(scene, decisions):
    g = scene
    ids = await new_transfers(g, count=len(decisions))
    if len(ids) == 1:
        path = f"/driver/transfers/{ids[0]}/respond"
        body = {"response": decisions[0], "reason": "P4 synthetic decision"}
    else:
        path = "/driver/transfers/batch_respond"
        body = {"transfers": [
            {"transfer_id": i, "status": d, "reason": "P4 synthetic decision"}
            for i, d in zip(ids, decisions)
        ]}
    response = await posted(g, "PUT", path, body)
    await completed_replay_revocation(g, "PUT", path, body, response)


async def test_completed_inventory_reconciliation_replay_requires_current_grant(scene):
    g = scene
    await posted(g, "PUT", "/driver/sessions/end", None)
    path = f"/driver/session/{g.session}/reconcile"
    body = {"counts": [{"product_variant_id": g.variant["id"], "actual_quantity": "150"}]}
    response = await posted(g, "POST", path, body)
    assert response.json()["requires_audit"] is False
    # The state-idempotent replay deliberately returns already_reconciled=True.
    before = await evidence(g)
    replay = await posted(g, "POST", path, body)
    assert replay.json()["already_reconciled"] is True
    assert await evidence(g) == before
    from tests.field_phase4_fixture import revoke_default, grant_default
    await revoke_default(g)
    await no_effect(g, "POST", path, body, statuses=(403,), code="FIELD_CAPABILITY_DENIED")
    await grant_default(g)
    before = await evidence(g)
    assert (await posted(g, "POST", path, body)).json() == replay.json()
    assert await evidence(g) == before


@pytest.mark.parametrize("remaining", ["transfer.receive", "transfer.reject"])
async def test_completed_mixed_batch_replay_still_needs_both_decision_grants(scene, remaining):
    g = scene
    ids = await new_transfers(g)
    body = {"transfers": [
        {"transfer_id": ids[0], "status": "accepted"},
        {"transfer_id": ids[1], "status": "rejected", "reason": "P4 rejected"},
    ]}
    await posted(g, "PUT", "/driver/transfers/batch_respond", body)
    role = await call(g, "POST", "/inventory/access/roles",
        {"name": "P4-only-" + uuid4().hex, "permissions": [remaining]}, token=g.owner_token)
    assert role.status_code == 201, role.text
    granted = await call(g, "POST", f"/representatives/{g.field.context.representative_id}/field-roles",
        {"request_id": str(uuid4()), "role_id": role.json()["id"]}, token=g.owner_token)
    assert granted.status_code == 200, granted.text
    from tests.field_phase4_fixture import revoke_default
    await revoke_default(g)
    await no_effect(g, "PUT", "/driver/transfers/batch_respond", body,
                    statuses=(403,), code="FIELD_CAPABILITY_DENIED")


@pytest.mark.parametrize("first", ["accepted", "rejected"])
async def test_transfer_decision_or_reason_change_never_replays_as_original_success(scene, first):
    g = scene
    ids = await new_transfers(g, count=1)
    path = f"/driver/transfers/{ids[0]}/respond"
    original = {"response": first, "reason": "Original reason"}
    await posted(g, "PUT", path, original)
    opposite = "rejected" if first == "accepted" else "accepted"
    await no_effect(g, "PUT", path, {"response": opposite, "reason": "Different decision"}, statuses=(409,))
    if first == "rejected":
        await no_effect(g, "PUT", path, {"response": first, "reason": "Different reason"}, statuses=(409,))


async def test_lost_visit_response_same_request_conflict_and_completed_correction_have_one_effect(scene):
    g = scene
    path = f"/visits/{g.visit}"
    original = sale(g)
    response = await posted(g, "PUT", path, original)
    # A transport may discard this response. Retrying the exact durable request
    # returns its stored result and makes no additional inventory/financial/audit effect.
    before = await evidence(g)
    replay = await posted(g, "PUT", path, original)
    assert replay.json() == response.json()
    assert await evidence(g) == before
    changed = {**sale(g, 4), "request_id": original["request_id"]}
    await no_effect(g, "PUT", path, changed, statuses=(409,))
    correction = sale(g, 4)
    corrected = await posted(g, "PUT", path, correction)
    assert corrected.json()["invoice"]["totals"]["final_amount"] == "20"
    frozen = await call(g, "GET", path + "/invoice")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["invoice"]["revision_number"] == 2
    assert frozen.json()["invoice"]["totals"] == corrected.json()["invoice"]["totals"]
    before = await evidence(g)
    assert (await posted(g, "PUT", path, correction)).json() == corrected.json()
    # A late original retry returns original evidence, never reapplies the old sale.
    assert (await posted(g, "PUT", path, original)).json() == response.json()
    assert await evidence(g) == before
    async with g.admin.connect() as db:
        balance = await db.scalar(text(
            "SELECT sum(on_hand_quantity) FROM inventory_balances "
            "WHERE company_id=:c AND location_id=:l AND stock_status='AVAILABLE'"),
            {"c": g.tenant, "l": g.location})
        assert balance == Decimal("146")
    report = await call(g, "GET", f"/admin/sessions/{g.session}/settlement_report", token=g.owner_token)
    assert report.status_code == 200, report.text
    assert Decimal(report.json()["financials"]["cash_from_sales"]) == Decimal("20")
    assert report.json()["visits"]["successful_sales"] == 1


async def test_field_sale_frozen_invoice_and_backoffice_views_share_same_truth(scene):
    g = scene
    before = await evidence(g)
    preview = await posted(g, "POST", f"/visits/{g.visit}/invoice-preview",
        {"cart_items": [{"product_variant_id": g.variant["id"], "packs_quantity": 10}]})
    assert preview.json()["commit_required"] is True
    assert preview.json()["invoice"]["status"] == "PREVIEW"
    await exact_money(preview.json()["invoice"])
    assert await evidence(g) == before, "Preview must not commit a sale"
    command = sale(g)
    result = await posted(g, "PUT", f"/visits/{g.visit}", command)
    invoice = result.json()["invoice"]
    assert invoice["status"] == "COMMITTED"
    await exact_money(invoice)
    frozen = await call(g, "GET", f"/visits/{g.visit}/invoice")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["invoice"]["revision_number"] == 1
    assert frozen.json()["invoice"]["totals"] == invoice["totals"] == preview.json()["invoice"]["totals"]
    field = await call(g, "GET", f"/visits/{g.visit}")
    office = await call(g, "GET", f"/visits/{g.visit}", token=g.bo_token)
    assert field.status_code == office.status_code == 200, (field.text, office.text)
    assert field.json() == office.json()
    assert field.json()["status"] == "Completed" and field.json()["outcome"] == "Sale"
    assert field.json()["cart_items"][0]["packs_quantity"] == 10
    assert Decimal(field.json()["cart_items"][0]["total_price"]) == Decimal(invoice["totals"]["final_amount"])
    report = await call(g, "GET", f"/admin/sessions/{g.session}/settlement_report", token=g.owner_token)
    assert report.status_code == 200, report.text
    assert report.json()["visits"]["completed_total"] == report.json()["visits"]["successful_sales"] == 1
    assert Decimal(report.json()["financials"]["cash_from_sales"]) == Decimal("50")
    dashboard = await call(g, "GET", "/driver/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert Decimal(dashboard.json()["financials"]["total_sales_cash"]) == Decimal("50")
    bo_stock = await call(g, "GET", f"/dispatch/inventory/{g.vehicle}", token=g.owner_token)
    assert bo_stock.status_code == 200, bo_stock.text
    stock = next(i for i in bo_stock.json() if int(i["product_id"]) == g.variant["id"])
    assert stock["current_quantity"] * 50 + stock["current_loose_packs"] == 140
    async with g.admin.connect() as db:
        quantity = await db.scalar(text(
            "SELECT sum(on_hand_quantity) FROM inventory_balances WHERE company_id=:c "
            "AND location_id=:l AND stock_status='AVAILABLE'"), {"c": g.tenant, "l": g.location})
        assert quantity == Decimal("140")
    # Cross-surface reads themselves must not write audit, projections or balances.
    after = await evidence(g)
    assert (await call(g, "GET", f"/visits/{g.visit}/invoice")).json() == frozen.json()
    assert await evidence(g) == after


async def test_opaque_return_evidence_and_all_three_reasons_match_canonical_custody(scene):
    g = scene
    # Establish authoritative sold evidence before customer returns.
    await posted(g, "PUT", f"/visits/{g.visit}", sale(g))
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        source = await db.get(Visit, g.visit)
        target = Visit(id=1700000000 + uuid4().int % 300000000, company_id=g.tenant,
            shop_id=source.shop_id, driver_id=g.field.driver.id, operational_date=source.operational_date,
            sequence=2, status="Pending", outcome="Pending")
        db.add(target)
        await db.commit()
    returns = []
    for reason in ("Damaged", "Expired", "Factory_Defect"):
        request = {"product_variant_id": g.variant["id"], "packs_quantity": 1, "return_type": reason}
        before = await evidence(g)
        resolution = await posted(g, "POST", f"/visits/{target.id}/return-resolution", request)
        assert resolution.json()["status"] == "RESOLVED"
        assert "batch_id" not in resolution.text
        assert type(resolution.json()["resolution_token"]) is str
        assert await evidence(g) == before
        returns.append({**request, "resolution_token": resolution.json()["resolution_token"]})
    # The same signed evidence cannot authorize another representative's operation.
    await no_effect(g, "PUT", f"/visits/{target.id}",
                    {"request_id": str(uuid4()), "outcome": "NoSale", "returns": returns},
                    token=g.other_token, statuses=(403, 404, 409))
    tampered = [{**returns[0], "resolution_token": returns[0]["resolution_token"] + "x"}]
    await no_effect(g, "PUT", f"/visits/{target.id}",
                    {"request_id": str(uuid4()), "outcome": "NoSale", "returns": tampered},
                    statuses=(403, 409, 422))
    command = {"request_id": str(uuid4()), "outcome": "NoSale", "returns": returns}
    result = await posted(g, "PUT", f"/visits/{target.id}", command)
    await completed_replay_revocation(g, "PUT", f"/visits/{target.id}", command, result)
    custody = await call(g, "GET", "/driver/custody")
    assert custody.status_code == 200, custody.text
    assert "batch_id" not in custody.text
    items = custody.json()["items"]
    assert sum(Decimal(i["quantity"]) for i in items) == Decimal("3")
    assert all(type(i["quantity"]) is str for i in items)
    async with g.admin.connect() as db:
        rows = (await db.execute(text(
            "SELECT stock_status,sum(on_hand_quantity) FROM inventory_balances "
            "WHERE company_id=:c AND location_id=:l AND stock_status<>'AVAILABLE' "
            "AND on_hand_quantity>0 GROUP BY stock_status"), {"c": g.tenant, "l": g.location})).all()
        expected = {status: amount for status, amount in rows}
    assert {i["stock_status"]: Decimal(i["quantity"]) for i in items} == expected
    field = await call(g, "GET", f"/visits/{target.id}")
    office = await call(g, "GET", f"/visits/{target.id}", token=g.owner_token)
    assert field.status_code == office.status_code == 200, (field.text, office.text)
    assert field.json() == office.json()
    assert {i["return_type"] for i in field.json()["returns"]} == {"Damaged", "Expired", "Factory_Defect"}
