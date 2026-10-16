"""Focused CP11 Inventory access / Backoffice seam acceptance."""
from __future__ import annotations

import ast
from pathlib import Path
import re
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import FastAPI

from api import inventory_permissions
from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.capabilities import PERMISSIONS


ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = ROOT / "wa_backend/api/inventory_permissions.py"
DOMAIN_SOURCE = ROOT / "wa_backend/domains/inventory_access/administration.py"
LABEL_SOURCE = ROOT / "dashboard/src/pages/inventory/access/permissionLabels.ts"

ADMIN = {
    "permission_catalog",
    "roles",
    "create_role",
    "update_role",
    "users",
    "locations",
    "user_grants",
    "grant",
    "revoke",
}
INTROSPECTION = {"capabilities", "location_capabilities"}


def _route_functions():
    tree = ast.parse(API_SOURCE.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list
    }


def test_cp11_routes_keep_owner_only_administration_and_canonical_runtime_inputs():
    functions = _route_functions()
    assert set(functions) == ADMIN | INTROSPECTION
    for name, node in functions.items():
        defaults = dict(zip(
            [arg.arg for arg in node.args.args][-len(node.args.defaults):],
            node.args.defaults,
        ))
        dependency = ast.unparse(defaults["access"])
        if name in ADMIN:
            assert dependency == "Depends(_require_company_owner)", name
        else:
            assert dependency == "Depends(get_current_backoffice_capability_access)", name

    source = API_SOURCE.read_text(encoding="utf-8")
    assert "@router.get('/me')" in source
    assert "@router.post('/locations/capabilities')" in source
    assert ".is_admin" not in source
    assert "get_current_driver" not in source
    assert "driver_id == user_id" not in source
    assert "BackofficeUser.id == backoffice_user_id" not in source  # moved to bounded domain seam


def test_cp11_inventory_does_not_add_account_lifecycle_or_a_second_permission_system():
    paths = {(route.path, tuple(sorted(route.methods or []))) for route in inventory_permissions.router.routes}
    assert not any(
        path.startswith("/inventory/access/users") and method in {"PATCH", "PUT"}
        for path, methods in paths
        for method in methods
    )
    source = API_SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "set_password(",
        "password_hash",
        "auth_revision",
        "deactivate",
        "create_user",
        "InventoryAccess(",
        "authorization.admin",
    ):
        assert forbidden not in source


def test_cp11_permission_rows_are_migration_owned_not_created_by_role_save():
    source = API_SOURCE.read_text(encoding="utf-8")
    body = ast.unparse(
        next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "save_role"
        )
    )
    assert "permission_ids_for_codes(db, codes)" in body
    assert "insert(Permission)" not in body
    assert body.index("permission_ids_for_codes(db, codes)") < body.index("delete(role_permissions)")


def test_cp11_target_bridge_is_canonical_and_id_independent():
    source = DOMAIN_SOURCE.read_text(encoding="utf-8")
    for required in (
        "BackofficeUser.company_id == company_id",
        "BackofficeUser.id == backoffice_user_id",
        "CompanyPrincipal.company_id == company_id",
        "IdentityLegacyDriverMap.company_id == company_id",
        "IdentityLegacyDriverMap.backoffice_principal_id == target.principal_id",
        "IdentityLegacyDriverMap.backoffice_user_id == backoffice_user_id",
    ):
        assert required in source
    for forbidden in (".is_admin", "Driver.", "legacy_driver_id == backoffice_user_id"):
        assert forbidden not in source


def test_cp11_dashboard_labels_cover_the_entire_backend_registry_without_raw_fallback():
    source = LABEL_SOURCE.read_text(encoding="utf-8")
    label_codes = set(re.findall(r"^\s*'([^']+)': \{ ar:", source, flags=re.MULTILINE))
    assert label_codes == set(PERMISSIONS)
    assert "return code" not in source
    for required in (
        "ledger.read",
        "ledger.adjust",
        "inventory.minimum_stock.manage",
        "representative.read",
        "representative.manage",
        "representative.credentials.reset",
        "vehicle.read",
        "vehicle.manage",
    ):
        assert required in label_codes


@pytest.mark.asyncio
async def test_cp11_direct_http_rejects_non_owner_administration_even_with_a_truthy_actor():
    app = FastAPI()
    app.include_router(inventory_permissions.router)

    async def ordinary_access():
        return NS(subject=NS(is_company_owner=False), company_id=7)

    async def fake_db():
        yield NS()

    async def fake_legacy_actor():
        return NS(id=999)

    app.dependency_overrides[get_current_backoffice_capability_access] = ordinary_access
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_backoffice_legacy_driver] = fake_legacy_actor

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://cp11.test") as client:
        for method, path, payload in (
            ("GET", "/inventory/access/catalog", None),
            ("GET", "/inventory/access/roles", None),
            ("POST", "/inventory/access/roles", {"name": "Denied", "permissions": ["inventory.read"]}),
            ("GET", "/inventory/access/users", None),
        ):
            response = await client.request(method, path, json=payload)
            assert response.status_code == 403, (method, path, response.text)
            assert response.json() == {"detail": "Authorization denied."}
