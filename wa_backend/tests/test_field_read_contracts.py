"""Field commercial/custody transport, exact money and channel isolation."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from starlette.exceptions import HTTPException

from api import field_contracts
from api.authentication.dependencies import (
    get_current_field_context, get_current_principal_context,
)
from api.authentication.field_compatibility import get_current_field_legacy_driver
from api.field_visit_contracts import begin_field_shop_command, complete_field_shop_command
from database import get_db
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.field_operations import context as field_context, custody, invoice
from domains.field_operations.contracts import FieldContractError, InvoicePreviewRequest
from main import WanasahRawASGIMiddleware, custom_http_exception_handler
from schemas import AddShopRequest

CTX = FieldRequestContext(101, 7, 202, 1)
NOW = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


def result(value=None, *, rows=()):
    out = Mock()
    out.scalar_one_or_none.return_value = value
    out.one_or_none.return_value = value
    out.scalars.return_value.all.return_value = list(rows)
    out.all.return_value = list(rows)
    return out


def calculation():
    values = dict(gross_amount=Decimal("10.123456"), discount_amount=Decimal("1.123456"),
                  post_offer_amount=Decimal("9"), taxable_amount=Decimal("9"),
                  tax_amount=Decimal("1.26"), line_total_amount=Decimal("10.26"),
                  rounding_adjustment=Decimal("0.001"), final_amount=Decimal("10.261"))
    return NS(
        totals=NS(**values), transaction_currency_code="JOD", calculated_at=NOW,
        rounding_policy=NS(precision=3, mode="HALF_UP"),
        lines=[NS(product_variant_id=44, **values)],
        rewards=[NS(product_variant_id=45, base_quantity=Decimal("0.500000"))],
    )


@pytest.mark.asyncio
async def test_owned_visit_filters_company_driver_and_visit_before_any_result():
    db = NS(execute=AsyncMock(return_value=result()))
    with pytest.raises(FieldContractError) as failure:
        await field_context.owned_visit(db, context=CTX, driver_id=303, visit_id=11)
    assert failure.value.status_code == 404
    sql = str(db.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for fragment in ("visits.company_id = 7", "visits.driver_id = 303",
                     "visits.id = 11", "shops.company_id = 7"):
        assert fragment in sql


@pytest.mark.asyncio
async def test_shop_tax_state_is_actionable_and_canonical_completion_is_refreshed():
    db = NS()
    pending = await field_context.shop_commercial_state(
        db, company_id=7, shop=NS(tax_jurisdiction_id=None))
    assert pending == field_context.pending_shop_commercial_state()
    assert pending["sale_ready"] is False
    with patch.object(field_context, "jurisdiction_chain", AsyncMock(return_value={99: 0})), \
         patch.object(field_context, "require_active_jurisdictions", AsyncMock(return_value={99})) as active:
        ready = await field_context.shop_commercial_state(
            db, company_id=7, shop=NS(tax_jurisdiction_id=99))
    assert ready["sale_ready"] is True
    active.assert_awaited_once_with(db, company_id=7, jurisdiction_ids={99: 0})


@pytest.mark.asyncio
async def test_preview_calls_existing_calculator_with_server_context_and_exact_results():
    work = NS(route=NS(id=55), session=NS(commercial_context_id=66))
    resolved = NS(calculation=calculation())
    with patch.object(invoice, "assigned_visit", AsyncMock(return_value=(
            NS(id=11), NS(id=22, tax_jurisdiction_id=99), work))), \
         patch.object(invoice, "shop_commercial_state", AsyncMock(return_value={"sale_ready": True})), \
         patch.object(invoice, "require_route_commercial_context", AsyncMock(return_value=NS(id=66))), \
         patch.object(invoice, "resolve_driver_sale", AsyncMock(return_value=resolved)) as calculator:
        response = await invoice.preview_invoice(
            None, context=CTX, driver_id=303, visit_id=11,
            request=InvoicePreviewRequest(cart_items=[{"product_variant_id": 44, "packs_quantity": 2}]))
    call = calculator.await_args.kwargs
    assert (call["company_id"], call["dispatch_route_id"], call["customer_id"],
            call["jurisdiction_id"], call["expected_commercial_context_id"]) == (7, 55, 22, 99, 66)
    assert call["inputs"][0].pack_quantity == 2
    assert response["invoice"]["totals"]["final_amount"] == "10.261"
    assert response["invoice"]["totals"]["gross_amount"] == "10.123456"
    assert response["invoice"]["totals"]["rounding_adjustment"] == "0.001"
    assert response["invoice"]["currency_code"] == "JOD"
    assert response["invoice"]["rewards"] == [{"product_variant_id": 45, "base_quantity": "0.500000"}]
    assert response["commit_required"] is True
    assert not any(word in str(response).lower() for word in ("cogs", "profit", "unit_cost"))


@pytest.mark.asyncio
async def test_preview_missing_tax_is_actionable_before_calculation():
    state = field_context.pending_shop_commercial_state()
    with patch.object(invoice, "assigned_visit", AsyncMock(return_value=(NS(), NS(), NS()))), \
         patch.object(invoice, "shop_commercial_state", AsyncMock(return_value=state)), \
         patch.object(invoice, "resolve_driver_sale", AsyncMock()) as calculator:
        with pytest.raises(FieldContractError) as failure:
            await invoice.preview_invoice(
                None, context=CTX, driver_id=303, visit_id=11,
                request=InvoicePreviewRequest(cart_items=[{"product_variant_id": 44, "packs_quantity": 1}]))
    assert failure.value.code == "SHOP_TAX_JURISDICTION_REQUIRED"
    assert failure.value.context["required_action"] == "BACKOFFICE_SET_SHOP_TAX_JURISDICTION"
    calculator.assert_not_awaited()


@pytest.mark.asyncio
async def test_committed_invoice_reads_immutable_revision_without_repricing_cancelled_historical_lines():
    calc = calculation()
    revision = NS(id=88, revision_number=2, transaction_currency_code="JOD",
                  rounding_precision=3, rounding_mode="HALF_UP", commercial_calculated_at=NOW,
                  **vars(calc.totals))
    item = NS(product_variant_id=44, gross_amount=calc.totals.gross_amount,
              discount_amount=calc.totals.discount_amount, tax_amount=calc.totals.tax_amount,
              net_amount=calc.totals.final_amount)
    db = NS(execute=AsyncMock(side_effect=[
        result(revision), result(rows=[item]), result(rows=calc.rewards),
    ]))
    with patch.object(invoice, "owned_visit", AsyncMock(return_value=(
            NS(id=11, status="Completed", outcome="Sale", current_sales_revision_id=88), NS()))), \
         patch.object(invoice, "resolve_driver_sale", AsyncMock(side_effect=AssertionError("Never reprice"))):
        response = await invoice.read_invoice(db, context=CTX, driver_id=303, visit_id=11)
    assert response["invoice"]["totals"]["final_amount"] == "10.261"
    assert response["invoice"]["revision_number"] == 2
    for call in db.execute.await_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert "company_id = 7" in sql
    item_sql = str(db.execute.await_args_list[1].args[0])
    assert "sales_revision_id" in item_sql and "is_cancelled" not in item_sql.split("WHERE")[1]


@pytest.mark.asyncio
async def test_non_sellable_custody_is_scoped_paginated_and_has_no_batch_id():
    work = NS(session=NS(id=33), vehicle_location_id=77)
    db = NS(execute=AsyncMock(return_value=result(rows=[
        (44, "Juice", "DAMAGED", "EACH", Decimal("1.125")),
        (45, "Milk", "QUARANTINED", "EACH", Decimal("2")),
    ])))
    with patch.object(custody, "active_work", AsyncMock(return_value=work)):
        response = await custody.read_custody(db, context=CTX, driver_id=303, limit=1)
    assert response["items"] == [{
        "product_variant_id": 44, "product_name": "Juice", "stock_status": "DAMAGED",
        "uom_code": "EACH", "quantity": "1.125",
    }]
    assert response["next_cursor"]
    assert "batch" not in str(response["items"])
    sql = str(db.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for fragment in ("inventory_balances.company_id = 7", "inventory_balances.location_id = 77",
                     "product_variants.company_id = 7", "GROUP BY", "LIMIT 2"):
        assert fragment in sql
    assert "'AVAILABLE'" not in sql
    db.execute.reset_mock()
    with patch.object(custody, "active_work", AsyncMock(return_value=NS(session=NS(id=34), vehicle_location_id=77))):
        with pytest.raises(FieldContractError) as failure:
            await custody.read_custody(db, context=CTX, driver_id=303, cursor=response["next_cursor"])
    assert failure.value.code == "FIELD_REFERENCE_SCOPE_MISMATCH"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_shop_uuid_uses_existing_atomic_operation_authority_and_legacy_remains_supported():
    db = NS(rollback=AsyncMock())
    payload = AddShopRequest(name="Shop", phone_number="12345", location_link="https://maps.example")
    assert await begin_field_shop_command(db, payload=payload, company_id=7, driver_id=303) == (None, None)
    command = payload.model_copy(update={"request_id": uuid4()})
    with patch("api.field_visit_contracts.begin_idempotent_operation", AsyncMock(return_value=("record", None))) as begin:
        assert await begin_field_shop_command(db, payload=command, company_id=7, driver_id=303) == ("record", None)
    assert begin.await_args.kwargs["operation"] == "FIELD_CREATE_SHOP"
    assert begin.await_args.kwargs["request_id"] == str(command.request_id)
    assert len(begin.await_args.kwargs["request_hash"]) == 64
    with patch("api.field_visit_contracts.complete_idempotent_operation") as complete:
        complete_field_shop_command("record", {"shop": {"id": 1}})
    complete.assert_called_once()


@pytest.mark.asyncio
async def test_new_field_routes_reject_dashboard_channel_before_business_reads():
    app = FastAPI()
    app.include_router(field_contracts.router)
    app.dependency_overrides[get_current_principal_context] = lambda: DashboardRequestContext(principal_id=101, company_id=7, backoffice_user_id=202, auth_revision=1, is_company_owner=True)
    never = AsyncMock(side_effect=AssertionError("No business read before FIELD authentication"))
    app.dependency_overrides[get_db] = lambda: NS(execute=never)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path, body in [
            ("POST", "/visits/11/return-resolution", {"product_variant_id": 44, "packs_quantity": 1}),
            ("POST", "/visits/11/invoice-preview", {"cart_items": []}),
            ("GET", "/visits/11/invoice", None),
            ("GET", "/visits/11/commercial-state", None),
            ("GET", "/driver/custody", None),
        ]:
            response = await client.request(method, path, json=body)
            assert response.status_code == 401, response.text
    never.assert_not_awaited()


@pytest.mark.asyncio
async def test_actionable_error_preserves_canonical_code_context_and_correlation_id():
    app = FastAPI()
    app.add_middleware(WanasahRawASGIMiddleware)
    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    app.include_router(field_contracts.router)
    app.dependency_overrides[get_current_field_context] = lambda: CTX
    app.dependency_overrides[get_current_field_legacy_driver] = lambda: NS(id=303)
    app.dependency_overrides[get_db] = lambda: NS()
    with patch.object(field_contracts, "resolve_return", AsyncMock(side_effect=FieldContractError(
            "FIELD_RETURN_EVIDENCE_REQUIRED", "Printed evidence required.",
            context={"required_evidence": ["expiry_date"]}))):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/visits/11/return-resolution", json={
                "product_variant_id": 44, "packs_quantity": 1})
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "FIELD_RETURN_EVIDENCE_REQUIRED"
    assert body["error"]["context"] == {"required_evidence": ["expiry_date"]}
    assert body["error"]["request_id"] == body["request_id"] == response.headers["x-request-id"]


def test_added_revalidation_retains_replay_and_original_lock_order():
    source = (Path(__file__).resolve().parents[1] / "api/driver.py").read_text()
    visit = source[source.index("async def update_visit("):source.index("async def _load_vehicle_inventory_projection(")]
    assert visit.index("if replay_response is not None:") < visit.index("await revalidate_return_provenance(")
    assert visit.index("await revalidate_return_provenance(") < visit.index("await reverse_previous_visit_state(")
    assert visit.index("await acquire_product_lifecycle_guards(") < visit.index("await revalidate_return_batch_metadata(")
    assert visit.index("await revalidate_return_batch_metadata(") < visit.index("await allocate_fefo_inventory_batch(")
    assert visit.index('response_payload["invoice"]') < visit.index("complete_idempotent_operation(") < visit.index("await db.commit()")
