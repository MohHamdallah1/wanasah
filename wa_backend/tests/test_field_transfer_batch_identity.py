"""Current production batch body + actual FIELD validation/envelope contracts."""
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.field_transfer_contracts import field_transfer_batch_route
from main import custom_http_exception_handler, validation_exception_handler
from schemas import BatchTransferResponseRequest
from tests.test_driver_session_field_context_cutover import (
    CONTEXT, NOW, OperationalLocator, load_custody_routes, result, custody_db,
)


def setup_batch(count=3):
    db, _ = custody_db()
    headers = [NS(id=i, work_session_id=601, source_location_id=901,
        destination_location_id=501, status="PENDING", received_by=None,
        decision_reason=None) for i in range(1, count + 1)]
    session = NS(id=601, end_time=None, is_settled=False)
    header_result = result()
    header_result.scalars.return_value.all.return_value = headers
    variants = result()
    variants.scalars.return_value.all.return_value = [
        NS(id=100+i, lifecycle_status="ACTIVE", operational_hold="NONE", variant_name="Fixture")
        for i in range(1, count + 1)]
    db.execute.side_effect = [header_result, result(session), variants]
    namespace = load_custody_routes(
        _load_handshake_lines_for_update=AsyncMock(return_value={
            h.id: [NS(product_variant_id=100+h.id)] for h in headers}),
        _load_active_driver_route_and_vehicle_location=AsyncMock(return_value=(NS(vehicle_id=801), 501)),
        _validate_handshake_locations=AsyncMock(),
        _driver_vehicle_custody_location_id=AsyncMock(return_value=501),
        acquire_product_lifecycle_guards=AsyncMock(),
        acquire_inventory_location_guards=AsyncMock(),
        evaluate_product_capability=Mock(return_value=NS(allowed=True)),
        INBOUND_COMPLETE="INBOUND_COMPLETE",
        _resolve_handshake_destination_statuses=AsyncMock(return_value={}),
        _build_handshake_movement_specs=Mock(return_value=[{"synthetic": True}]),
        apply_inventory_movements_batch=AsyncMock(), get_utc_now=Mock(return_value=NOW),
    )
    namespace.update(
        _load_active_driver_route_and_vehicle_location=AsyncMock(return_value=(NS(vehicle_id=801), 501)),
        _validate_handshake_locations=AsyncMock(),
        _driver_vehicle_custody_location_id=AsyncMock(return_value=501),
    )
    payload = NS(transfers=[NS(transfer_id=h.id, status="rejected", reason="reason") for h in headers])
    return NS(db=db, headers=headers, session=session, namespace=namespace, payload=payload)


async def invoke(setup):
    return await setup.namespace["batch_respond_to_transfers"](
        payload=setup.payload, db=setup.db, field_context=CONTEXT, legacy_actor=OperationalLocator())


def assert_atomic_refusal(setup):
    setup.db.commit.assert_not_awaited()
    setup.db.rollback.assert_awaited_once()
    setup.namespace["apply_inventory_movements_batch"].assert_not_awaited()
    assert all(h.status == "PENDING" for h in (setup.headers[0], setup.headers[-1]))


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected_code,status", [
    ("conflict", "FIELD_TRANSFER_DECISION_CONFLICT", 409),
    ("processed", "FIELD_TRANSFER_ALREADY_PROCESSED", 409),
    ("reason", "FIELD_TRANSFER_REJECTION_REASON_REQUIRED", 400),
    ("missing", "FIELD_TRANSFER_NOT_FOUND", 404),
    ("product", "FIELD_TRANSFER_PRODUCT_MISSING", 409),
    ("capability", "PRODUCT_NOT_RECEIVABLE", 409),
    ("destination", "FIELD_TRANSFER_DESTINATION_INVALID", 403),
])
async def test_middle_item_structured_identity_zero_new_decisions(reason, expected_code, status):
    setup = setup_batch()
    if reason == "conflict":
        setup.headers[1].status = "REJECTED"
        setup.headers[1].received_by = 303
        setup.headers[1].decision_reason = "old reason"
    elif reason == "processed":
        setup.headers[1].status = "POSTED"
    elif reason == "reason":
        setup.payload.transfers[1].reason = None
    elif reason == "missing":
        responses = list(setup.db.execute.side_effect)
        responses[0].scalars.return_value.all.return_value = [setup.headers[0], setup.headers[2]]
        setup.db.execute.side_effect = responses
    elif reason == "product":
        responses = list(setup.db.execute.side_effect)
        responses[-1].scalars.return_value.all.return_value = [NS(id=101), NS(id=103)]
        setup.db.execute.side_effect = responses
    elif reason == "capability":
        for item in setup.payload.transfers:
            item.status = "accepted"
        setup.namespace["evaluate_product_capability"].side_effect = [
            NS(allowed=True), NS(allowed=False, code="PRODUCT_NOT_RECEIVABLE")]
    elif reason == "destination":
        for item in setup.payload.transfers:
            item.status = "accepted"
        setup.namespace["_validate_handshake_locations"].side_effect = [
            None, HTTPException(403, "Anything Arabic or English; never parsed")]
    with pytest.raises(HTTPException) as rejected:
        await invoke(setup)
    assert rejected.value.status_code == status
    assert rejected.value.detail["code"] == expected_code
    assert rejected.value.detail["context"] == {"transfer_id": 2}
    assert "batch_id" not in json.dumps(rejected.value.detail)
    assert_atomic_refusal(setup)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,code", [
    ("mixed", "FIELD_TRANSFER_BATCH_MIXED_SESSIONS"),
    ("session", "FIELD_TRANSFER_BATCH_SESSION_INVALID"),
])
async def test_global_refusal_has_no_fake_item_identity(reason, code):
    setup = setup_batch()
    if reason == "mixed":
        setup.headers[1].work_session_id = 999
    else:
        setup.session.is_settled = True
    with pytest.raises(HTTPException) as rejected:
        await invoke(setup)
    assert rejected.value.detail["code"] == code
    assert rejected.value.detail["context"] == {}
    assert_atomic_refusal(setup)


@pytest.mark.asyncio
async def test_runtime_duplicate_guard_prevents_map_collapse_before_query():
    setup = setup_batch()
    setup.payload.transfers[1].transfer_id = 1
    with pytest.raises(HTTPException) as rejected:
        await invoke(setup)
    assert rejected.value.detail == {"code": "FIELD_TRANSFER_DUPLICATE_ID",
        "message": "Duplicate transfer decision.", "context": {"transfer_id": 1}}
    setup.db.execute.assert_not_awaited()
    setup.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["accepted", "rejected"])
async def test_one_hundred_exact_replays_succeed_without_new_movements(decision):
    setup = setup_batch(100)
    for header, item in zip(setup.headers, setup.payload.transfers):
        item.status = decision
        header.status = "POSTED" if decision == "accepted" else "REJECTED"
        header.received_by = 303
        header.decision_reason = "reason" if decision == "rejected" else None
    await invoke(setup)
    setup.db.commit.assert_awaited_once()
    setup.namespace["apply_inventory_movements_batch"].assert_not_awaited()
    setup.db.add.assert_not_called()


@pytest.mark.asyncio
async def test_one_hundred_and_one_rejected_before_query():
    setup = setup_batch(101)
    with pytest.raises(HTTPException) as rejected:
        await invoke(setup)
    assert rejected.value.status_code == 413
    assert rejected.value.detail["code"] == "FIELD_TRANSFER_BATCH_TOO_LARGE"
    assert rejected.value.detail["context"] == {}
    setup.db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,code,identity", [
    ({"transfers": [{"transfer_id": 1, "status": "accepted"},
                   {"transfer_id": 1, "status": "accepted"}]}, "FIELD_TRANSFER_DUPLICATE_ID", 1),
    ({"transfers": [{"transfer_id": 1, "status": "accepted"},
                   {"transfer_id": 2, "status": "rejected"}]}, "FIELD_TRANSFER_REJECTION_REASON_REQUIRED", 2),
])
async def test_actual_batch_schema_adapter_preserves_canonical_envelope(payload, code, identity):
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    router = APIRouter()
    calls = []
    @field_transfer_batch_route(router)
    async def endpoint(payload: BatchTransferResponseRequest):
        calls.append(payload)
        return {"ok": True}
    app.include_router(router)
    @app.middleware("http")
    async def correlation(request, call_next):
        request.state.request_id = "batch-correlation-id"
        return await call_next(request)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://field.test") as client:
        response = await client.put("/driver/transfers/batch_respond", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == code
    assert error["context"] == {"transfer_id": identity}
    assert error["request_id"] == "batch-correlation-id"
    assert "batch_id" not in json.dumps(response.json())
    assert not calls
    # The public route and typed request body remain present in OpenAPI.
    assert "requestBody" in app.openapi()["paths"]["/driver/transfers/batch_respond"]["put"]
