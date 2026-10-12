import ast
import re
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "api"
    / "warehouse"
    / "locations.py"
)
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNCTIONS = {
    node.name: node
    for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}


def _function_source(name: str) -> str:
    return ast.get_source_segment(SOURCE, FUNCTIONS[name]) or ""


def test_runtime_has_no_legacy_request_authority() -> None:
    forbidden = (
        "get_current_driver",
        "InventoryAccess",
        "current_admin",
        ".is_admin",
        "legacy_actor.company_id",
    )
    for token in forbidden:
        assert token not in SOURCE


def test_runtime_uses_only_exact_warehouse_location_capabilities() -> None:
    capability_codes = set(re.findall(r"['\"](location\.[a-z]+)['\"]", SOURCE))
    assert capability_codes == {
        "location.read",
        "location.create",
        "location.update",
        "location.state",
    }


def test_read_routes_use_canonical_access_without_loading_legacy_driver() -> None:
    for name in (
        "get_warehouse_setup_status",
        "manage_warehouse_locations",
    ):
        source = _function_source(name)
        assert "get_current_backoffice_capability_access" in source
        assert "get_current_backoffice_legacy_driver" not in source
        assert "legacy_actor" not in source
        assert "company_id = access.company_id" in source


def test_write_routes_use_legacy_driver_only_for_existing_driver_id_provenance() -> None:
    for name in (
        "create_warehouse_location",
        "update_warehouse_location",
        "activate_warehouse_location",
        "deactivate_warehouse_location",
    ):
        source = _function_source(name)
        assert "get_current_backoffice_capability_access" in source
        assert "get_current_backoffice_legacy_driver" in source
        assert "company_id = access.company_id" in source
        assert "legacy_actor.id" in source
        assert "legacy_actor.company_id" not in source


def test_location_filter_stays_before_cursor_pagination_and_allows_stays_sql() -> None:
    list_source = _function_source("manage_warehouse_locations")
    filter_index = list_source.index("access.location_filter('location.read')")
    pagination_index = list_source.index(".limit(limit + 1)")
    assert filter_index < pagination_index

    setup_source = _function_source("get_warehouse_setup_status")
    assert "select(access.allows('location.create'))" in setup_source
    assert "await access.location_filter" not in SOURCE
    assert "await access.allows" not in SOURCE


def test_canonical_require_adapter_preserves_location_http_contract() -> None:
    source = _function_source("_require_location_capability")
    assert "await access.require" in source
    assert "BackofficeCapabilityAccessRejected" in source
    assert "الموقع غير موجود أو غير متاح." in source
    assert "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد." in source
