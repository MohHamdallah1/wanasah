from __future__ import annotations

import ast
import base64
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import and_
from sqlalchemy.dialects import postgresql

os.environ.setdefault(
    "SECRET_KEY",
    "Cp2BatchIndexSyntheticKeyAbc123456789012345678901234567890",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://cp2@127.0.0.1:1/cp2",
)

from api.warehouse import batch_index
from domains.inventory_rules import batch_metadata_is_sellable
from domains.product_tracking import INTERNAL_NO_LOT_PREFIX, public_batch_number
from schemas import (
    WarehouseInventoryBatchIndexCursorPage,
    WarehouseInventoryBatchIndexItem,
    WarehouseInventoryBatchIndexSummaryResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BATCH_INDEX = REPO_ROOT / "wa_backend" / "api" / "warehouse" / "batch_index.py"
LIVE_STOCK = REPO_ROOT / "wa_backend" / "api" / "warehouse" / "live_stock.py"


def _scope(**overrides) -> str:
    values = dict(
        company_id=7,
        location_id=11,
        search_tokens=("milk", "lot"),
        expiry_state="ALL",
        expiry_warning_days=None,
        sellability="ALL",
        disposition=None,
        has_unavailable=None,
        has_damaged=None,
        has_disposal_pending=None,
        family_id=None,
        product_variant_id=None,
        sort="EXPIRY_ASC",
        limit=50,
    )
    values.update(overrides)
    return batch_index._scope_hash(**values)


def _reasons(**overrides):
    values = dict(
        as_of_date=date(2026, 10, 16),
        expiry_control_mode="OPTIONAL",
        production_date=None,
        expiry_date=None,
        minimum_remaining_shelf_life_days=0,
        is_active=True,
        disposition="RELEASED",
    )
    values.update(overrides)
    return batch_index._reason_codes(**values)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"is_active": False}, ("BATCH_INACTIVE",)),
        ({"disposition": "BLOCKED"}, ("DISPOSITION_NOT_RELEASED",)),
        (
            {"production_date": date(2026, 10, 17)},
            ("PRODUCTION_DATE_IN_FUTURE",),
        ),
        (
            {"expiry_control_mode": "REQUIRED"},
            ("EXPIRY_REQUIRED_MISSING",),
        ),
        (
            {
                "expiry_control_mode": "NONE",
                "expiry_date": date(2026, 10, 20),
            },
            ("EXPIRY_NOT_ALLOWED",),
        ),
        (
            {
                "expiry_date": date(2026, 10, 15),
                "minimum_remaining_shelf_life_days": 20,
            },
            ("EXPIRED",),
        ),
        (
            {"minimum_remaining_shelf_life_days": 1},
            ("MINIMUM_REMAINING_SHELF_LIFE_NOT_MET",),
        ),
    ],
)
def test_sellability_reasons_are_deterministic_and_nonredundant(overrides, expected):
    assert _reasons(**overrides) == expected


def test_sellability_reason_order_and_canonical_parity():
    values = dict(
        as_of_date=date(2026, 10, 16),
        expiry_control_mode="REQUIRED",
        production_date=date(2026, 10, 17),
        expiry_date=date(2026, 10, 15),
        minimum_remaining_shelf_life_days=10,
        is_active=False,
        disposition="RECALLED",
    )
    reasons = batch_index._reason_codes(**values)
    assert reasons == (
        "BATCH_INACTIVE",
        "DISPOSITION_NOT_RELEASED",
        "PRODUCTION_DATE_IN_FUTURE",
        "EXPIRED",
    )
    assert batch_metadata_is_sellable(**values) is False


def test_shelf_life_boundary_matches_canonical_authority():
    base = dict(
        as_of_date=date(2026, 10, 16),
        expiry_control_mode="OPTIONAL",
        production_date=None,
        minimum_remaining_shelf_life_days=5,
        is_active=True,
        disposition="RELEASED",
    )
    exact = {**base, "expiry_date": date(2026, 10, 21)}
    short = {**base, "expiry_date": date(2026, 10, 20)}
    assert batch_metadata_is_sellable(**exact) is True
    assert batch_index._reason_codes(**exact) == ()
    assert batch_metadata_is_sellable(**short) is False
    assert batch_index._reason_codes(**short) == (
        "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET",
    )


def test_public_anonymous_lot_is_nullable_and_internal_identity_never_public():
    raw = INTERNAL_NO_LOT_PREFIX + "R0123456789ABCDEF"
    assert public_batch_number(raw) is None
    fields = WarehouseInventoryBatchIndexItem.model_fields
    assert fields["batch_number"].is_required() is False
    assert fields["production_date"].is_required() is False
    assert fields["expiry_date"].is_required() is False


def test_quantity_contract_is_string_only_and_cost_fields_do_not_exist():
    fields = WarehouseInventoryBatchIndexItem.model_fields
    quantity_fields = {
        "display_factor_to_base",
        "quantity_step",
        "on_hand_quantity",
        "reserved_quantity",
        "available_for_sale_quantity",
        "unavailable_quantity",
        "available_status_quantity",
        "quarantined_quantity",
        "blocked_quantity",
        "recalled_quantity",
        "damaged_quantity",
        "disposal_pending_quantity",
    }
    assert all(fields[name].annotation is str for name in quantity_fields)
    assert not ({"latest_purchase_cost", "last_purchase_cost", "purchase_event_count"} & set(fields))
    assert "items" in WarehouseInventoryBatchIndexCursorPage.model_fields
    assert "expiring_soon_count" in WarehouseInventoryBatchIndexSummaryResponse.model_fields


def test_cursor_is_signed_scope_bound_and_contains_no_anonymous_lot_value():
    scope = _scope()
    cursor = batch_index._encode_cursor(
        scope=scope,
        sort="EXPIRY_ASC",
        batch_id=123,
        key="2026-12-01",
    )
    decoded = batch_index._decode_cursor(
        cursor,
        expected_scope=scope,
        expected_sort="EXPIRY_ASC",
    )
    assert decoded["batch_id"] == 123
    payload = base64.urlsafe_b64decode(cursor.split(".", 1)[0] + "==")
    assert INTERNAL_NO_LOT_PREFIX.encode() not in payload

    with pytest.raises(HTTPException) as mismatch:
        batch_index._decode_cursor(
            cursor,
            expected_scope=_scope(family_id=99),
            expected_sort="EXPIRY_ASC",
        )
    assert mismatch.value.status_code == 400

    with pytest.raises(HTTPException) as sort_mismatch:
        batch_index._decode_cursor(
            cursor,
            expected_scope=scope,
            expected_sort="PRODUCT_ASC",
        )
    assert sort_mismatch.value.status_code == 400


def test_cursor_tampering_is_rejected():
    cursor = batch_index._encode_cursor(
        scope=_scope(),
        sort="EXPIRY_ASC",
        batch_id=9,
        key=None,
    )
    index = max(0, len(cursor) // 3)
    replacement = "A" if cursor[index] != "A" else "B"
    tampered = cursor[:index] + replacement + cursor[index + 1 :]
    with pytest.raises(HTTPException) as exc:
        batch_index._decode_cursor(
            tampered,
            expected_scope=_scope(),
            expected_sort="EXPIRY_ASC",
        )
    assert exc.value.status_code == 400


def test_search_tokens_are_same_row_and_escape_percent_underscore_backslash():
    tokens = batch_index._search_tokens(r"  Milk  100% lot_ a\\b  ")
    assert tokens == ("milk", "100%", "lot_", r"a\\b")
    predicates = batch_index._search_predicates(tokens)
    assert len(predicates) == len(tokens)
    assert batch_index._escape_like("100%") == r"100\%"
    assert batch_index._escape_like("lot_") == r"lot\_"
    assert batch_index._escape_like(r"a\b") == r"a\\b"
    compiled = str(
        and_(*predicates).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "product_barcodes" not in compiled.lower()
    assert "NOT LIKE" in compiled
    assert "WANASAH" in compiled


def test_all_expiry_states_are_sql_owned_and_company_date_is_explicit():
    today = date(2026, 10, 16)
    for state in ("ALL", "EXPIRED", "EXPIRES_TODAY", "NO_EXPIRY"):
        predicate = batch_index._expiry_filter(
            expiry_state=state,
            as_of_date=today,
            expiry_warning_days=None,
        )
        assert predicate is not None
    soon = batch_index._expiry_filter(
        expiry_state="EXPIRING_SOON",
        as_of_date=today,
        expiry_warning_days=7,
    )
    compiled = str(
        soon.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "2026-10-16" in compiled and "2026-10-23" in compiled
    with pytest.raises(HTTPException):
        batch_index._expiry_filter(
            expiry_state="EXPIRING_SOON",
            as_of_date=today,
            expiry_warning_days=None,
        )


def test_routes_use_authoritative_sources_filters_before_keyset_and_no_n_plus_one():
    source = BATCH_INDEX.read_text(encoding="utf-8")
    assert '"/warehouse/inventory/batches/cursor"' in source
    assert '"/warehouse/inventory/batches/summary"' in source
    assert '"/warehouse/inventory/{product_variant_id}/batches"' not in source
    for required in (
        "InventoryBalance",
        "ProductBatch",
        "ProductVariant",
        "Product",
        "InventoryStockPolicy",
        "batch_sellability_predicate",
    ):
        assert required in source
    for forbidden in (
        "InventoryLiveStockProjection",
        "InventoryCostEvent",
        "latest_purchase",
        "ProductBarcode",
    ):
        assert forbidden not in source
    assert source.index(".where(*filters)") < source.index(".limit(limit + 1)")
    loop = source.index("for row in page_rows:")
    assert "await db." not in source[loop : source.index("next_cursor = None", loop)]
    assert "family_id" in source and "product_variant_id" in source
    assert "has_unavailable" in source and "has_damaged" in source
    assert "has_disposal_pending" in source


def test_existing_batch_drill_down_preserves_independent_batch_and_location_authority():
    # CP2 adds a warehouse-wide Batch Index; it does not own or freeze the
    # separate product batch drill-down. Later quality/security work may update
    # live_stock.py without changing this legacy endpoint's authority.
    source = LIVE_STOCK.read_text(encoding="utf-8")
    module = ast.parse(source)
    handlers = [
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "get_warehouse_inventory_batches"
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    decorators = [
        ast.get_source_segment(source, decorator) or ""
        for decorator in handler.decorator_list
    ]
    assert any(
        '"/warehouse/inventory/{product_variant_id}/batches"' in decorator
        and "WarehouseInventoryBatchDetailResponse" in decorator
        for decorator in decorators
    )

    read_checks = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "access"
        and node.func.attr == "allows"
    ]
    assert any(
        len(call.args) >= 2
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "inventory.read"
        and isinstance(call.args[1], ast.Name)
        and call.args[1].id == "location_id"
        for call in read_checks
    )

    body = ast.get_source_segment(source, handler)
    assert body is not None
    for required in (
        "company_id = access.company_id",
        "InventoryLocation.company_id == company_id",
        'location_access_row.location_type != "WAREHOUSE"',
        "ProductVariant.company_id == company_id",
        "ProductBatch.company_id == company_id",
        "InventoryBalance.company_id == company_id",
        "InventoryBalance.location_id == location_id",
        "InventoryBalance.product_variant_id",
        "InventoryBalance.batch_id == ProductBatch.id",
        "batch_presence",
        "batch_cursor_predicate",
        ".limit(limit + 1)",
        "ProductBatch.expiry_date.asc().nulls_last()",
        "ProductBatch.id.asc()",
        "_decode_batch_cursor(",
        "_encode_batch_cursor(",
        "batch_sellability_predicate(",
        "public_batch_number(",
    ):
        assert required in body, f"Legacy batch drill-down lost: {required}"

    # The CP2 index is additive, not a replacement projection or a second
    # stock authority for the existing drill-down.
    assert "batch_index" not in body
    assert "InventoryLiveStockProjection" not in body


def test_route_has_keyset_only_and_batch_id_tie_breaks_every_sort():
    source = BATCH_INDEX.read_text(encoding="utf-8")
    assert "offset(" not in source.lower()
    for sort in (
        "EXPIRY_ASC",
        "EXPIRY_DESC",
        "PRODUCT_ASC",
        "PRODUCT_DESC",
        "BATCH_IDENTITY_ASC",
        "UNAVAILABLE_DESC",
    ):
        assert sort in source
    assert "ProductBatch.id.asc()" in source
    assert "group_by(" in source and "InventoryBalance.batch_id" in source



def test_quantity_partitions_and_disposition_filters_are_sql_owned():
    stock = batch_index._stock_aggregate_subquery(company_id=7, location_id=11)
    compiled = str(stock.select().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for status in ("AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING"):
        assert status in compiled
    source = BATCH_INDEX.read_text(encoding="utf-8")
    for field in (
        "on_hand_quantity", "reserved_quantity", "available_for_sale_quantity",
        "unavailable_quantity", "available_status_quantity", "quarantined_quantity",
        "blocked_quantity", "recalled_quantity", "damaged_quantity", "disposal_pending_quantity",
    ):
        assert f'"{field}"' in source
    for disposition in ("RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"):
        assert disposition in source


def test_scope_hash_binds_every_filter_and_sort_dimension():
    baseline = _scope()
    variants = (
        _scope(location_id=12), _scope(search_tokens=("other",)),
        _scope(expiry_state="NO_EXPIRY"),
        _scope(expiry_state="EXPIRING_SOON", expiry_warning_days=7),
        _scope(sellability="SELLABLE"), _scope(disposition="BLOCKED"),
        _scope(has_unavailable=True), _scope(has_damaged=True),
        _scope(has_disposal_pending=True), _scope(family_id=3),
        _scope(product_variant_id=9), _scope(sort="PRODUCT_ASC"),
    )
    assert all(value != baseline for value in variants)
    assert len(set(variants)) == len(variants)


def test_cursor_default_expiry_order_is_nulls_last_and_batch_id_stable():
    stock, _, _, available_for_sale, unavailable = batch_index._batch_index_query_parts(
        company_id=7, location_id=11, as_of_date=date(2026, 10, 16)
    )
    ordering = batch_index._ordering(sort="EXPIRY_ASC", unavailable_expression=unavailable)
    rendered = " ".join(str(item) for item in ordering)
    assert "NULLS LAST" in rendered.upper()
    assert "product_batches.id ASC" in rendered
    assert stock is not None and available_for_sale is not None
