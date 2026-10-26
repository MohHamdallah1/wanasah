"""Checkpoint 1 lot/expiry and anonymous ProductBatch contract gates."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

os.environ.setdefault(
    "SECRET_KEY",
    "Checkpoint1UnitSecretABC123456789xyz",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/wanasah_unit",
)

import api.warehouse.inbound as inbound
from models import OperationIdempotency
from tests.test_inbound_no_lot_frozen_contract import AS_OF, ReceiptHarness
from domains.product_tracking import (
    INTERNAL_NO_LOT_PREFIX,
    build_internal_no_lot_batch_number,
    is_reserved_internal_batch_number,
    public_batch_number,
)
from schemas import (
    BatchDispositionMutationResponse,
    InboundBatchItem,
    StocktakeCycleBatchItem,
    UnifiedTransferSourceBatchItem,
    UpgradedInboundRequest,
    WarehouseBatchStockSourcesResponse,
    WarehouseInventoryBatchItem,
    WarehouseQualityBatchCandidateItem,
    WarehouseTransferLineItem,
)


def _error_code(exc: HTTPException) -> str:
    assert isinstance(exc.detail, dict)
    return str(exc.detail["code"])


def _resolve(
    mode: str,
    batch_number: str | None,
    *,
    request_id: UUID | None = None,
    production_date: date | None = None,
    expiry_date: date | None = None,
    uom_id: int = 10,
):
    return inbound._resolve_inbound_lot_identity(
        request_id=request_id or uuid4(),
        product_variant_id=7,
        uom_id=uom_id,
        lot_control_mode=mode,
        supplied_batch_number=batch_number,
        production_date=production_date,
        expiry_date=expiry_date,
    )


@pytest.mark.parametrize("mode", ["NONE", "OPTIONAL"])
def test_missing_lot_is_anonymous_for_none_and_optional(mode: str):
    resolved, anonymous = _resolve(mode, None)
    assert anonymous is True
    assert is_reserved_internal_batch_number(resolved)
    assert public_batch_number(resolved) is None
    assert len(resolved) <= 100


def test_none_rejects_supplied_lot_without_silently_discarding_it():
    with pytest.raises(HTTPException) as caught:
        _resolve("NONE", "REAL-LOT")
    assert _error_code(caught.value) == "INBOUND_LOT_NOT_ALLOWED"
    assert caught.value.detail["context"]["batch_number"] == "REAL-LOT"


def test_optional_accepts_real_lot_unchanged():
    assert _resolve("OPTIONAL", "LOT-77") == ("LOT-77", False)


def test_required_rejects_missing_lot():
    with pytest.raises(HTTPException) as caught:
        _resolve("REQUIRED", None)
    assert _error_code(caught.value) == "INBOUND_LOT_REQUIRED"


def test_required_accepts_real_lot_unchanged():
    assert _resolve("REQUIRED", "LOT-88") == ("LOT-88", False)


@pytest.mark.parametrize("mode", ["REQUIRED", "OPTIONAL"])
def test_reserved_prefix_spoof_is_rejected_without_leaking_internal_value(mode: str):
    spoof = INTERNAL_NO_LOT_PREFIX + "CLIENT-SPOOF"
    with pytest.raises(HTTPException) as caught:
        _resolve(mode, spoof)
    assert _error_code(caught.value) == "INBOUND_LOT_RESERVED"
    assert INTERNAL_NO_LOT_PREFIX not in repr(caught.value.detail)


def test_none_reserved_input_uses_not_allowed_code_and_never_leaks_value():
    spoof = INTERNAL_NO_LOT_PREFIX + "CLIENT-SPOOF"
    with pytest.raises(HTTPException) as caught:
        _resolve("NONE", spoof)
    assert _error_code(caught.value) == "INBOUND_LOT_NOT_ALLOWED"
    assert INTERNAL_NO_LOT_PREFIX not in repr(caught.value.detail)


def test_anonymous_identity_is_scoped_by_request_and_metadata_not_uom():
    request_a = uuid4()
    request_b = uuid4()
    production = date(2026, 10, 1)
    expiry = date(2027, 10, 1)

    a_uom_1, _ = _resolve(
        "OPTIONAL", None, request_id=request_a,
        production_date=production, expiry_date=expiry, uom_id=1,
    )
    a_uom_2, _ = _resolve(
        "OPTIONAL", None, request_id=request_a,
        production_date=production, expiry_date=expiry, uom_id=2,
    )
    b_same_dates, _ = _resolve(
        "OPTIONAL", None, request_id=request_b,
        production_date=production, expiry_date=expiry, uom_id=1,
    )
    a_other_expiry, _ = _resolve(
        "OPTIONAL", None, request_id=request_a,
        production_date=production, expiry_date=date(2027, 11, 1), uom_id=1,
    )

    assert a_uom_1 == a_uom_2
    assert b_same_dates != a_uom_1
    assert a_other_expiry != a_uom_1
    assert len({a_uom_1, b_same_dates, a_other_expiry}) == 3


def test_duplicate_key_uses_resolved_batch_identity_plus_uom():
    source = Path(inbound.__file__).read_text(encoding="utf-8")
    assert "line_key = (variant_id, str(resolved_batch_number), int(item.uom_id))" in source
    assert '"INBOUND_DUPLICATE_BATCH_UOM_LINE"' in source


def test_internal_identity_builder_requires_durable_uuid_and_fits_storage():
    request_id = uuid4()
    value = build_internal_no_lot_batch_number(
        request_id=request_id,
        production_date=date(2026, 10, 15),
        expiry_date=date(2099, 12, 31),
    )
    assert request_id.hex.upper() in value
    assert value.startswith(INTERNAL_NO_LOT_PREFIX)
    assert len(value) <= 100


def test_inbound_batch_number_missing_null_and_blank_normalize_to_none():
    common = dict(
        product_variant_id=1,
        quantity="1",
        uom_id=1,
        unit_cost="1",
    )
    assert InboundBatchItem(**common).batch_number is None
    assert InboundBatchItem(**common, batch_number=None).batch_number is None
    assert InboundBatchItem(**common, batch_number="   ").batch_number is None
    assert InboundBatchItem(**common, batch_number="  LOT-A  ").batch_number == "LOT-A"


def test_inbound_batch_number_max_length_preserved():
    common = dict(product_variant_id=1, quantity="1", uom_id=1, unit_cost="1")
    assert len(InboundBatchItem(**common, batch_number="A" * 100).batch_number) == 100
    with pytest.raises(ValidationError):
        InboundBatchItem(**common, batch_number="A" * 101)


def _validate_dates(
    mode: str,
    *,
    production: date | None,
    expiry: date | None,
    as_of: date = date(2026, 10, 15),
):
    return inbound._validate_inbound_dates(
        product_variant_id=7,
        uom_id=10,
        expiry_control_mode=mode,
        production_date=production,
        expiry_date=expiry,
        as_of_date=as_of,
        batch_number="REAL-LOT",
    )


def test_expiry_modes_and_company_local_today_boundary():
    today = date(2026, 10, 15)
    assert _validate_dates("NONE", production=None, expiry=None, as_of=today) is None
    with pytest.raises(HTTPException) as none_supplied:
        _validate_dates("NONE", production=None, expiry=today, as_of=today)
    assert _error_code(none_supplied.value) == "INBOUND_EXPIRY_NOT_ALLOWED"

    assert _validate_dates("OPTIONAL", production=None, expiry=None, as_of=today) is None
    assert _validate_dates("OPTIONAL", production=today, expiry=today, as_of=today) is None

    with pytest.raises(HTTPException) as required_missing:
        _validate_dates("REQUIRED", production=None, expiry=None, as_of=today)
    assert _error_code(required_missing.value) == "INBOUND_EXPIRY_REQUIRED"
    assert _validate_dates("REQUIRED", production=today, expiry=today, as_of=today) is None


def test_expired_and_future_production_are_rejected():
    today = date(2026, 10, 15)
    with pytest.raises(HTTPException) as expired:
        _validate_dates("OPTIONAL", production=None, expiry=today - timedelta(days=1), as_of=today)
    assert _error_code(expired.value) == "INBOUND_BATCH_EXPIRED"

    with pytest.raises(HTTPException) as future:
        _validate_dates("OPTIONAL", production=today + timedelta(days=1), expiry=None, as_of=today)
    assert _error_code(future.value) == "INBOUND_PRODUCTION_DATE_FUTURE"


@pytest.mark.asyncio
async def test_production_after_expiry_reaches_endpoint_stable_business_code():
    receipt = ReceiptHarness()
    try:
        body = receipt.body(item={
            "production_date": AS_OF + timedelta(days=1),
            "expiry_date": AS_OF,
        })
        # Pydantic parses dates; the real handler owns the business rejection.
        payload = UpgradedInboundRequest.model_validate(body)
        assert payload.items[0].production_date > payload.items[0].expiry_date
        pending_query = select(OperationIdempotency).where(
            OperationIdempotency.company_id == 1,
            OperationIdempotency.operation == "WAREHOUSE_INBOUND",
            OperationIdempotency.request_id == str(payload.request_id),
        )
        rollback = receipt.db.rollback

        async def observe_pending_then_rollback():
            pending = receipt.session.scalar(pending_query)
            assert pending is not None
            assert pending.completed_at is None and pending.response_json is None
            await rollback()

        with patch.object(receipt.db, "rollback",
                          AsyncMock(side_effect=observe_pending_then_rollback)) as rolled_back:
            with pytest.raises(HTTPException) as caught:
                await receipt.post(body)

        assert caught.value.status_code == 422
        assert _error_code(caught.value) == "INBOUND_BATCH_DATES_INVALID"
        rolled_back.assert_awaited_once()
        receipt.movement.assert_not_awaited()
        assert receipt.posted == []
        assert receipt.batches() == []
        assert receipt.session.scalar(pending_query) is None
    finally:
        receipt.close()


def _batch(*, production, expiry, number="REAL-LOT"):
    return SimpleNamespace(
        product_variant_id=7,
        batch_number=number,
        production_date=production,
        expiry_date=expiry,
    )


def test_existing_real_lot_identical_metadata_is_reused():
    batch = _batch(production=date(2026, 10, 1), expiry=date(2027, 10, 1))
    assert inbound._ensure_named_batch_metadata_matches(
        batch,
        production_date=date(2026, 10, 1),
        expiry_date=date(2027, 10, 1),
    ) is None


@pytest.mark.parametrize(
    ("persisted_production", "persisted_expiry", "requested_production", "requested_expiry"),
    [
        (None, None, None, date(2027, 10, 1)),
        (None, date(2027, 10, 1), None, None),
        (None, date(2027, 10, 1), date(2026, 10, 1), date(2027, 10, 1)),
        (date(2026, 10, 1), date(2027, 10, 1), None, date(2027, 10, 1)),
        (date(2026, 10, 1), date(2027, 10, 1), date(2026, 10, 2), date(2027, 10, 1)),
    ],
)
def test_existing_real_lot_metadata_mismatch_fails_closed(
    persisted_production, persisted_expiry, requested_production, requested_expiry,
):
    batch = _batch(production=persisted_production, expiry=persisted_expiry)
    with pytest.raises(HTTPException) as caught:
        inbound._ensure_named_batch_metadata_matches(
            batch,
            production_date=requested_production,
            expiry_date=requested_expiry,
        )
    assert _error_code(caught.value) == "INBOUND_BATCH_METADATA_CONFLICT"
    assert caught.value.detail["context"]["batch_number"] == "REAL-LOT"


@pytest.mark.asyncio
async def test_committed_replay_returns_before_anonymous_identity_or_any_posting():
    payload = UpgradedInboundRequest(
        request_id=uuid4(),
        supplier_id=1,
        location_id=2,
        items=[{
            "product_variant_id": 7,
            "quantity": "1",
            "uom_id": 10,
            "unit_cost": "2",
            "batch_number": None,
        }],
    )
    db = SimpleNamespace(rollback=AsyncMock(), execute=AsyncMock())
    access = SimpleNamespace(company_id=3)
    legacy_actor = SimpleNamespace(id=4)
    replay = {"message": "INBOUND_POSTED"}

    with patch.object(inbound, "_require_inbound_access", AsyncMock()), \
         patch.object(inbound, "_require_active_warehouse_setup", AsyncMock()), \
         patch.object(inbound, "require_supplier_permission", AsyncMock()), \
         patch.object(inbound, "begin_idempotent_operation", AsyncMock(return_value=(object(), replay))), \
         patch.object(inbound, "_resolve_inbound_lot_identity") as resolve_lot, \
         patch.object(inbound, "apply_inventory_movements_batch", AsyncMock()) as movements, \
         patch.object(inbound, "activate_costing_for_first_receipt", AsyncMock()) as costing:
        assert await inbound.warehouse_inbound(payload, db, access, legacy_actor) == replay

    db.rollback.assert_awaited_once()
    db.execute.assert_not_awaited()
    resolve_lot.assert_not_called()
    movements.assert_not_awaited()
    costing.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_preexisting_anonymous_identity_fails_closed_without_leak():
    request_id = uuid4()
    key = (
        7,
        build_internal_no_lot_batch_number(
            request_id=request_id, production_date=None, expiry_date=None,
        ),
    )

    class _Result:
        def first(self):
            return SimpleNamespace(product_variant_id=key[0], batch_number=key[1])

    db = SimpleNamespace(execute=AsyncMock(return_value=_Result()))
    with pytest.raises(HTTPException) as caught:
        await inbound._ensure_anonymous_batch_keys_unused(
            db,
            company_id=3,
            anonymous_batch_keys={key},
            requested_batches={key: (None, None)},
        )
    assert _error_code(caught.value) == "INBOUND_ANONYMOUS_BATCH_COLLISION"
    assert INTERNAL_NO_LOT_PREFIX not in repr(caught.value.detail)


def test_concurrent_anonymous_insert_collision_fails_closed_without_leak():
    key = (
        7,
        build_internal_no_lot_batch_number(
            request_id=uuid4(), production_date=None, expiry_date=None,
        ),
    )
    with pytest.raises(HTTPException) as caught:
        inbound._ensure_anonymous_batch_keys_created(
            anonymous_batch_keys={key},
            created_batch_keys=set(),
            requested_batches={key: (None, None)},
        )
    assert _error_code(caught.value) == "INBOUND_ANONYMOUS_BATCH_COLLISION"
    assert INTERNAL_NO_LOT_PREFIX not in repr(caught.value.detail)


def test_anonymous_insert_uses_returning_to_distinguish_real_lot_reuse_from_collision():
    source = Path(inbound.__file__).read_text(encoding="utf-8")
    assert ".returning(\n                    ProductBatch.product_variant_id,\n                    ProductBatch.batch_number," in source
    assert "_ensure_anonymous_batch_keys_created(" in source
    assert INTERNAL_NO_LOT_PREFIX not in source


def test_inbound_options_expose_authoritative_lot_and_expiry_modes():
    source = Path(inbound.__file__).read_text(encoding="utf-8")
    assert "ProductVariant.lot_control_mode" in source
    assert '"lot_control_mode": lot_control_mode' in source
    assert '"expiry_control_mode": expiry_control_mode' in source


def test_user_facing_batch_response_contracts_allow_null():
    response_models = (
        WarehouseInventoryBatchItem,
        WarehouseBatchStockSourcesResponse,
        WarehouseQualityBatchCandidateItem,
        BatchDispositionMutationResponse,
        UnifiedTransferSourceBatchItem,
        WarehouseTransferLineItem,
        StocktakeCycleBatchItem,
    )
    for model in response_models:
        field = model.model_fields["batch_number"]
        assert type(None) in get_args(field.annotation), model.__name__


def test_public_batch_number_masks_internal_and_preserves_real_lot():
    internal = build_internal_no_lot_batch_number(
        request_id=uuid4(), production_date=None, expiry_date=None,
    )
    assert public_batch_number(internal) is None
    assert public_batch_number("REAL-LOT-1") == "REAL-LOT-1"
    assert public_batch_number(None) is None


def test_operator_facing_serializers_use_central_public_batch_helper():
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "api/warehouse/live_stock.py",
        root / "domains/ledger/read.py",
        root / "api/warehouse/transfers.py",
        root / "api/warehouse/stocktake.py",
        root / "api/warehouse/whole_product_quality_preview.py",
        root / "domains/inventory_quality_reads.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "public_batch_number" in source, path.name
        assert '"batch_number": str(' not in source, path.name
    stocktake_source = (root / "api/warehouse/stocktake.py").read_text(encoding="utf-8")
    assert '"scope_batch_number": row.scope_batch_number' not in stocktake_source


def test_internal_namespace_literal_is_confined_to_product_tracking_authority():
    root = Path(__file__).resolve().parents[1]
    runtime_paths = (
        root / "api/warehouse/inbound.py",
        root / "api/warehouse/live_stock.py",
        root / "api/warehouse/ledger.py",
        root / "api/warehouse/transfers.py",
        root / "api/warehouse/stocktake.py",
        root / "api/warehouse/whole_product_quality_preview.py",
        root / "domains/inventory_quality_reads.py",
    )
    for path in runtime_paths:
        assert INTERNAL_NO_LOT_PREFIX not in path.read_text(encoding="utf-8"), path.name
