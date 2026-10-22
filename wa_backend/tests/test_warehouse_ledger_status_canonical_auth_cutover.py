import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "api" / "warehouse" / "ledger.py"
STATUS_PATH = ROOT / "api" / "warehouse" / "status.py"
ACCESS_PATH = ROOT / "domains" / "authorization" / "backoffice_access.py"

LEDGER = LEDGER_PATH.read_text(encoding="utf-8")
STATUS = STATUS_PATH.read_text(encoding="utf-8")
ACCESS = ACCESS_PATH.read_text(encoding="utf-8")

LEDGER_TREE = ast.parse(LEDGER)
STATUS_TREE = ast.parse(STATUS)


def _function_source(source: str, tree: ast.Module, name: str) -> str:
    node = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    return ast.get_source_segment(source, node) or ""


def test_both_read_families_use_only_canonical_backoffice_request_authority() -> None:
    combined = LEDGER + "\n" + STATUS
    for forbidden in (
        "get_current_driver",
        "get_current_admin",
        "InventoryAccess",
        ".is_admin",
        "current_admin.company_id",
        "actor.company_id",
        "legacy_actor.company_id",
        "get_current_backoffice_legacy_driver",
    ):
        assert forbidden not in combined

    for source in (LEDGER, STATUS):
        assert "BackofficeCapabilityAccess" in source
        assert "get_current_backoffice_capability_access" in source
        assert "access.company_id" in source


def test_company_owner_and_ordinary_users_are_resolved_by_canonical_access_only() -> None:
    assert "if self.subject.is_company_owner:" in ACCESS
    assert "return true()" in ACCESS
    assert "legacy_grant_driver_id" in ACCESS
    assert "assignment.driver_id == legacy_driver_id" in ACCESS

    ledger_route = _function_source(
        LEDGER, LEDGER_TREE, "get_warehouse_ledger_cursor"
    )
    status_route = _function_source(
        STATUS, STATUS_TREE, "get_warehouse_status"
    )
    for source in (ledger_route, status_route):
        assert "Depends(get_current_backoffice_capability_access)" in source
        assert "principal_id" not in source
        assert "backoffice_user_id" not in source
        assert "driver_id" not in source


def test_ledger_exact_location_any_location_and_missing_permission_contracts() -> None:
    helper = _function_source(LEDGER, LEDGER_TREE, "_require_ledger_access")
    assert "await access.require(" in helper
    assert "'ledger.read'" in helper
    assert "location_id," in helper
    assert "any_location=location_id is None" in helper
    assert "BackofficeCapabilityAccessRejected" in helper
    assert "InventoryLocation.company_id == access.company_id" in helper
    assert "InventoryLocation.id == location_id" in helper
    assert "403," in helper
    assert "HTTPException(404" in helper

    route = _function_source(LEDGER, LEDGER_TREE, "get_warehouse_ledger_cursor")
    assert "await _require_ledger_access(access, location_id=location_id)" in route
    assert "company_id = access.company_id" in route


def test_ledger_unauthorized_locations_are_filtered_before_count_and_pagination() -> None:
    route = _function_source(LEDGER, LEDGER_TREE, "get_warehouse_ledger_cursor")
    visibility = (
        "or_(access.allows('ledger.read', InventoryMovement.source_location_id),\n"
        "                access.allows('ledger.read', InventoryMovement.destination_location_id))"
    )
    assert route.count(visibility) == 2
    assert route.index(visibility) < route.index("count_stmt = select(func.count())")
    assert route.index(visibility) < route.index(".limit(limit + 1)")

    impact_visibility = "access.allows('ledger.read', InventoryBalance.location_id)"
    assert impact_visibility in route
    assert route.index(impact_visibility) < route.index("for impact, balance in")


def test_ledger_cross_company_filters_and_historical_driver_join_are_data_only() -> None:
    route = _function_source(LEDGER, LEDGER_TREE, "get_warehouse_ledger_cursor")
    assert "InventoryMovement.company_id == company_id" in route
    assert "InventoryMovementImpact.company_id == company_id" in route
    assert "InventoryBalance.company_id == company_id" in route
    assert "ProductBatch.company_id == company_id" in route
    assert "InventoryCostEvent.company_id == company_id" in route
    assert "InventorySupplierEvidence.company_id == company_id" in route
    assert "select(Company.currency_code).where(Company.id == company_id)" in route

    assert "Driver.full_name" in route
    assert "Driver.company_id == InventoryMovement.company_id" in route
    assert "Driver.id == InventoryMovement.performed_by" in route
    assert "Depends(get_current_driver)" not in route
    assert "Driver.is_admin" not in route


def test_ledger_cursor_filter_order_and_page_contracts_are_preserved() -> None:
    encoder = _function_source(LEDGER, LEDGER_TREE, "_encode_ledger_cursor")
    decoder = _function_source(LEDGER, LEDGER_TREE, "_decode_ledger_cursor")
    route = _function_source(LEDGER, LEDGER_TREE, "get_warehouse_ledger_cursor")

    assert '"v": 2' in encoder
    assert '"kind": "warehouse-ledger"' in encoder
    assert '"scope": _ledger_cursor_scope_hash(scope)' in encoder
    assert 'payload.get("v") != 2' in decoder
    assert 'payload.get("kind") != "warehouse-ledger"' in decoder
    assert "_ledger_cursor_scope_hash(expected_scope)" in decoder
    assert "Cursor سجل الحركات غير صالح أو لا يطابق نطاق البحث الحالي." in decoder

    for fragment in (
        'clean_search = (search or "").strip().lower()',
        'clean_type = (reference_type or "").strip()',
        'clean_reference = (reference_id or "").strip()',
        'f"ledger|{company_id}|{location_id or 0}|"',
        "InventoryMovement.reference_type == clean_type",
        "InventoryMovement.reference_id == clean_reference",
        "InventoryMovement.created_at.desc()",
        "InventoryMovement.id.desc()",
        ".limit(limit + 1)",
        "has_more = len(rows) > limit",
        "rows = rows[:limit]",
        "if cursor is None and reference_id is None:",
        '"available_types": available_types',
        '"total": total',
    ):
        assert fragment in route


def test_ledger_product_uom_balance_batch_cost_supplier_evidence_paths_remain() -> None:
    route = _function_source(LEDGER, LEDGER_TREE, "get_warehouse_ledger_cursor")
    for fragment in (
        "_ledger_product_location_snapshots(",
        "_load_inventory_display_uoms(",
        "ProductBatch.batch_number",
        "InventoryCostEvent.inventory_movement_id.in_(movement_ids)",
        "InventorySupplierEvidence.movement_id.in_(movement_ids)",
        '"balance_scope":',
        '"PRODUCT_LOCATION"',
        '"average_cost_after":',
        '"supplier_id":',
        '"supplier_name":',
        '"supplier_code":',
    ):
        assert fragment in route


def test_status_preserves_location_read_or_dispatch_read_exact_location_semantics() -> None:
    helper = _function_source(STATUS, STATUS_TREE, "_require_status_access")
    assert "await access.require(('location.read', 'dispatch.read'), location_id)" in helper
    assert "BackofficeCapabilityAccessRejected" in helper
    assert "InventoryLocation.company_id == access.company_id" in helper
    assert "InventoryLocation.id == location_id" in helper
    assert "403," in helper
    assert "HTTPException(404" in helper

    route = _function_source(STATUS, STATUS_TREE, "get_warehouse_status")
    assert "await _require_status_access(access, location_id)" in route
    assert "_active_full_warehouse_audit_lock(" in route
    assert "company_id=int(access.company_id)" in route
    assert '"status": "AUDIT_LOCK"' in route
    assert '"stocktake_reference": active_lock.stocktake_reference' in route


def test_status_cross_company_location_is_rejected_without_foreign_lock_scope() -> None:
    helper = _function_source(STATUS, STATUS_TREE, "_require_status_access")
    route = _function_source(STATUS, STATUS_TREE, "get_warehouse_status")
    assert "InventoryLocation.company_id == access.company_id" in helper
    assert "InventoryLocation.id == location_id" in helper
    assert "company_id=int(access.company_id)" in route
    assert "_active_full_warehouse_audit_lock(" in route
    assert "location_id=location_id" in route


def test_identity_ids_and_driver_admin_flags_are_irrelevant_to_these_routes() -> None:
    combined = LEDGER + "\n" + STATUS
    for forbidden in (
        "principal_id ==",
        "backoffice_user_id ==",
        "legacy_grant_driver_id ==",
        "Driver.is_admin",
        ".is_admin",
    ):
        assert forbidden not in combined

    # Driver remains in Ledger only as historical movement performer display data.
    assert "Driver.full_name" in LEDGER
    assert "InventoryMovement.performed_by" in LEDGER
    assert "Driver" not in STATUS
