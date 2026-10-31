#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
import subprocess
from typing import Callable

HELPER = ".github/scripts/live_stock_ci_ownership.py"
UX_WORKFLOW = ".github/workflows/live-stock-v1-ux-closure.yml"
R3_WORKFLOW = ".github/workflows/live-stock-v1-r3-physical-location-truth.yml"
OP_WORKFLOW = ".github/workflows/live-stock-v1-operational-browser.yml"
PHYSICAL_CALLER = ".github/workflows/live-stock-physical-custody-consumers.yml"

POLICY_FILES = {HELPER, UX_WORKFLOW, R3_WORKFLOW, OP_WORKFLOW, PHYSICAL_CALLER}

SHARED_RESOURCES = "dashboard/src/i18n/resources.ts"
SHARED_SCHEMA = "wa_backend/schemas.py"
SHARED_DISPATCH = "wa_backend/api/dispatch.py"

UX_ALLOWED = {
    ".github/workflows/live-stock-v1-browser-acceptance.yml",
    ".github/workflows/inventory-cp13-shell-polish.yml",
    ".github/workflows/inventory-cp6-minimum-stock-dashboard-acceptance.yml",
    PHYSICAL_CALLER,
    OP_WORKFLOW,
    UX_WORKFLOW,
    HELPER,
    "dashboard/e2e/inventory-cp14-device-ux.spec.ts",
    "dashboard/e2e/live-stock-physical-custody.config.ts",
    "dashboard/e2e/live-stock-physical-custody.fixture.py",
    "dashboard/e2e/live-stock-physical-custody.spec.ts",
    "dashboard/e2e/live-stock-ux-closure.config.ts",
    "dashboard/e2e/live-stock-ux-closure.fixtures.ts",
    "dashboard/e2e/live-stock-ux-closure.spec.ts",
    "dashboard/e2e/live-stock-v1.fixtures.ts",
    SHARED_RESOURCES,
    "dashboard/src/components/dashboard/WorkspaceTopBar.css",
    "dashboard/src/pages/inventory/InventoryTopDock.tsx",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/StockMinimumManager.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/Tab2Inbound.tsx",
    "dashboard/src/pages/inventory/TabWarehouseLocations.tsx",
    "dashboard/src/pages/inventory/inventory.css",
    "dashboard/src/pages/inventory/inventoryShellPolish.css",
    "dashboard/src/pages/inventory/inventoryTopDockController.ts",
    "dashboard/src/pages/inventory/liveStock/BatchDetailPanel.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockFilters.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx",
    "dashboard/src/pages/inventory/liveStock/VehicleCustodyQuantity.tsx",
    "dashboard/src/pages/inventory/liveStock/contracts.ts",
    "dashboard/src/pages/inventory/liveStock/i18n.ts",
    "dashboard/src/pages/inventory/liveStock/useLiveStockBatchDetail.ts",
    "dashboard/src/pages/inventory/warehouse-locations/presentation/i18n.ts",
    "dashboard/src/test/inventory-access.test.ts",
    "dashboard/src/test/inventory-cp12-responsive-contract.test.ts",
    "dashboard/src/test/inventory-cp13-shell-polish.test.tsx",
    "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx",
    "dashboard/src/test/inventory-cp7-live-stock-parity.test.tsx",
    "dashboard/src/test/inventory-cp7-live-stock.test.tsx",
    "dashboard/src/test/live-stock-batch-detail-freshness.test.tsx",
    "dashboard/src/test/live-stock-family-cursor.test.tsx",
    "dashboard/src/test/live-stock-local-failure.test.tsx",
    "dashboard/src/test/live-stock-render-performance.benchmark.test.tsx",
    "dashboard/src/test/live-stock-render-windowing.test.tsx",
    "dashboard/src/test/live-stock-ui-stability.test.ts",
    "dashboard/src/test/live-stock-ui01-canonical-alert.test.tsx",
    "dashboard/src/test/live-stock-warm-authority.test.tsx",
    "docs/operations/LIVE_STOCK_OPERATIONAL_BROWSER_EVIDENCE.md",
    "wa_backend/tests/live_stock_operational_browser_support.py",
}

R3_ALLOWED = {
    R3_WORKFLOW,
    HELPER,
    ".github/workflows/flutter-v1-backend-field-contracts.yml",
    "docs/operations/LIVE_STOCK_V1_R3_PHYSICAL_LOCATION_TRUTH.md",
    SHARED_DISPATCH,
    "wa_backend/api/warehouse/live_stock.py",
    "wa_backend/domains/live_stock_projection/service.py",
    SHARED_SCHEMA,
    "wa_backend/scripts/gate_stage821_live_stock_projector_core.py",
    "wa_backend/scripts/gate_r2_live_stock_perf_50k.py",
    "wa_backend/tests/test_live_stock_canonical_cutover.py",
    "wa_backend/tests/test_live_stock_r4_negative_filter_contract.py",
    "wa_backend/tests/test_live_stock_r4_query_contract.py",
    "wa_backend/tests/test_live_stock_v1_r4_query_optimization_postgres.py",
    "wa_backend/tests/live_stock_r4_negative_filter_postgres_acceptance.py",
    "wa_backend/tests/test_live_stock_r1_http_postgres.py",
    "wa_backend/tests/test_live_stock_r1_sql_postgres.py",
    "wa_backend/tests/test_live_stock_r1_snapshot_postgres.py",
    "wa_backend/tests/test_live_stock_v1_quantity_reconciliation_postgres.py",
    "wa_backend/tests/test_live_stock_v1_remaining_consistency_postgres.py",
    "wa_backend/tests/test_live_stock_v1_route_sale_unload_postgres.py",
    "wa_backend/tests/test_live_stock_v1_r3_physical_location_truth_postgres.py",
}

OP_ALLOWED = {
    ".github/workflows/inventory-cp13-shell-polish.yml",
    ".github/workflows/inventory-cp6-minimum-stock-dashboard-acceptance.yml",
    PHYSICAL_CALLER,
    ".github/workflows/live-stock-v1-browser-acceptance.yml",
    OP_WORKFLOW,
    UX_WORKFLOW,
    HELPER,
    "dashboard/e2e/inventory-cp14-device-ux.spec.ts",
    "dashboard/e2e/live-stock-operational.config.ts",
    "dashboard/e2e/live-stock-operational.journey.ts",
    "dashboard/e2e/live-stock-operational-workflow.test.py",
    "dashboard/e2e/live-stock-operational.spec.ts",
    "dashboard/e2e/live-stock-operational.support.ts",
    "dashboard/e2e/live-stock-physical-custody.config.ts",
    "dashboard/e2e/live-stock-physical-custody.fixture.py",
    "dashboard/e2e/live-stock-physical-custody.spec.ts",
    "dashboard/e2e/live-stock-ux-closure.fixtures.ts",
    "dashboard/e2e/live-stock-ux-closure.spec.ts",
    "dashboard/e2e/live-stock-v1.fixtures.ts",
    "dashboard/src/components/dashboard/WorkspaceTopBar.css",
    SHARED_RESOURCES,
    "dashboard/src/pages/inventory/InventoryTopDock.tsx",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/StockMinimumManager.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/inventoryShellPolish.css",
    "dashboard/src/pages/inventory/inventoryTopDockController.ts",
    "dashboard/src/pages/inventory/liveStock/BatchDetailPanel.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx",
    "dashboard/src/pages/inventory/liveStock/VehicleCustodyQuantity.tsx",
    "dashboard/src/pages/inventory/liveStock/contracts.ts",
    "dashboard/src/pages/inventory/liveStock/useLiveStockBatchDetail.ts",
    "dashboard/src/test/inventory-access.test.ts",
    "dashboard/src/test/inventory-cp13-shell-polish.test.tsx",
    "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx",
    "dashboard/src/test/inventory-cp7-live-stock-parity.test.tsx",
    "dashboard/src/test/inventory-cp7-live-stock.test.tsx",
    "dashboard/src/test/live-stock-batch-detail-freshness.test.tsx",
    "dashboard/src/test/live-stock-local-failure.test.tsx",
    "dashboard/src/test/live-stock-render-performance.benchmark.test.tsx",
    "dashboard/src/test/live-stock-render-windowing.test.tsx",
    "dashboard/src/test/live-stock-ui01-canonical-alert.test.tsx",
    "dashboard/src/test/live-stock-warm-authority.test.tsx",
    "docs/operations/LIVE_STOCK_OPERATIONAL_BROWSER_EVIDENCE.md",
    "wa_backend/tests/live_stock_operational_browser_support.py",
}

# Issue #706: a bounded auth repair also retains the original Live Stock evidence.
SESSION_ISOLATION_ALLOWED = {
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    "dashboard/src/App.tsx",
    "dashboard/src/components/operations/DashboardLayout.tsx",
    "dashboard/src/hooks/useInventoryAccess.ts",
    "dashboard/src/test/live-stock-warm-authority.test.tsx",
    "dashboard/src/test/live-stock-batch-detail-freshness.test.tsx",
    "dashboard/e2e/live-stock-inflight.config.ts",
    "dashboard/e2e/live-stock-inflight-auth.test.tsx",
    "docs/operations/LIVE_STOCK_INFLIGHT_AUTHORITY_FINDINGS.md",
    "dashboard/src/hooks/useAuthFetch.ts",
    "dashboard/src/lib/authStorage.ts",
    "dashboard/src/pages/Login.tsx",
    "dashboard/src/test/auth-session-isolation.test.tsx",
    "wa_backend/tests/live_stock_inflight_security_probe.py",
    ".github/scripts/live_stock_ci_ownership.py",
    "dashboard/src/components/operations/TopBar.tsx",
    "dashboard/src/components/operations/OperationsSidebar.tsx",
    "dashboard/src/hooks/useDashboardSession.ts",
    "dashboard/src/features/tenantIdentity/useTenantIdentity.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/pages/products/import/useImportProductPolling.ts",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
    "dashboard/src/test/dispatch-load-context.test.tsx",
}
SESSION_ISOLATION_ROOTS = {
    "dashboard/src/hooks/useAuthFetch.ts",
    "dashboard/src/lib/authStorage.ts",
}

LIVE_STOCK_SCHEMA_ROOTS = {
    "WarehouseAlertItem",
    "WarehouseInventoryItem",
    "WarehouseInventoryCursorPage",
    "WarehouseInventorySummaryResponse",
    "WarehouseInventoryAlertSummaryResponse",
    "WarehouseInventoryBatchProductOption",
    "WarehouseInventoryBatchProductCursorPage",
    "WarehouseInventoryBatchItem",
    "WarehouseInventoryBatchDetailResponse",
}

def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()

def _git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True)

def _changed(base: str, head: str) -> set[str]:
    output = _git("diff", "--name-only", base, head)
    return set(output.splitlines()) if output else set()

def _object_sections(source: str, key: str) -> tuple[str, ...]:
    """Return complete TypeScript object-literal sections for one property key.

    Braces inside strings/comments are ignored so nested objects such as
    inventoryLive.vehicleScopes remain part of the same owned signature.
    """
    sections: list[str] = []
    pattern = re.compile(rf"\b{re.escape(key)}\s*:\s*{{")
    for match in pattern.finditer(source):
        start = source.find("{", match.start(), match.end())
        depth = 0
        quote: str | None = None
        escaped = False
        line_comment = False
        block_comment = False
        index = start
        while index < len(source):
            char = source[index]
            nxt = source[index + 1] if index + 1 < len(source) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
                index += 1
                continue
            if block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char in ('"', "'", chr(96)):
                quote = char
                index += 1
                continue
            if char == "/" and nxt == "/":
                line_comment = True
                index += 2
                continue
            if char == "/" and nxt == "*":
                block_comment = True
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    section = source[start:index + 1]
                    sections.append(re.sub(r"\s+", " ", section.strip()))
                    break
            index += 1
        else:
            raise ValueError(f"unterminated object section for {key}")
    return tuple(sections)


def _resource_signature(source: str) -> tuple[str, ...]:
    entries: list[str] = []
    for line in source.splitlines():
        stripped = re.sub(r"\s+", " ", line.strip())
        if re.search(r"\bLIVE_STOCK_[A-Z0-9_]+\s*:", stripped):
            entries.append(stripped)
        elif re.search(r"\bliveStockCount\s*:", stripped):
            entries.append(stripped)
    entries.extend(
        f"inventoryLive[{index}]={section}"
        for index, section in enumerate(_object_sections(source, "inventoryLive"))
    )
    return tuple(entries)


def _binding_nodes(tree: ast.Module) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[node.name] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                bindings[name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node
    return bindings

def _schema_signature(source: str) -> tuple[tuple[str, str], ...]:
    tree = ast.parse(source)
    bindings = _binding_nodes(tree)
    missing = sorted(LIVE_STOCK_SCHEMA_ROOTS - bindings.keys())
    if missing:
        raise ValueError(f"missing Live Stock schema roots: {missing}")
    wanted = set(LIVE_STOCK_SCHEMA_ROOTS)
    queue = list(sorted(wanted))
    while queue:
        name = queue.pop()
        node = bindings[name]
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in bindings and child.id not in wanted:
                wanted.add(child.id)
                queue.append(child.id)
    return tuple(
        (name, ast.dump(bindings[name], annotate_fields=True, include_attributes=False))
        for name in sorted(wanted)
    )

def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""

def _model_aliases(tree: ast.Module, model_name: str) -> set[str]:
    aliases = {model_name}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or (node.module or "") != "models":
            continue
        for alias in node.names:
            if alias.name == model_name:
                aliases.add(alias.asname or alias.name)
    return aliases


def _direct_route_source_sql_evidence(tree: ast.Module) -> tuple[str, ...]:
    """Detect prohibited direct SQL that attributes Vehicle balance to route source."""
    route_aliases = _model_aliases(tree, "DispatchRoute")
    balance_aliases = _model_aliases(tree, "InventoryBalance")
    evidence: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        attrs = {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
        calls = {
            _call_name(child.func).lower()
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
        }
        uses_models = bool(names & route_aliases) and bool(names & balance_aliases)
        uses_route_source = "source_location_id" in attrs and "vehicle_id" in attrs
        uses_balance_location = "location_id" in attrs
        queryish = any(
            name == "select" or name.endswith(".select") or
            name == "join" or name.endswith(".join")
            for name in calls
        )
        if uses_models and uses_route_source and uses_balance_location and queryish:
            evidence.append(
                "DIRECT_ROUTE_SOURCE_SQL:" +
                ast.dump(node, annotate_fields=True, include_attributes=False)
            )
    return tuple(sorted(evidence))


def _dispatch_r3_signature(source: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    evidence: list[str] = list(_direct_route_source_sql_evidence(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("domains.live_stock_projection"):
            evidence.append(ast.dump(node, annotate_fields=True, include_attributes=False))
        elif isinstance(node, ast.Import):
            if any(alias.name.startswith("domains.live_stock_projection") for alias in node.names):
                evidence.append(ast.dump(node, annotate_fields=True, include_attributes=False))
        elif isinstance(node, ast.Call):
            name = _call_name(node.func).lower()
            if "live_stock" in name or "vehicle_attribution" in name:
                evidence.append(ast.dump(node, annotate_fields=True, include_attributes=False))
    return tuple(sorted(evidence))


def _shared_semantics(base: str, head: str, changed: set[str]) -> dict[str, bool]:
    semantic = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    if SHARED_RESOURCES in changed:
        semantic[SHARED_RESOURCES] = (
            _resource_signature(_git_show(base, SHARED_RESOURCES))
            != _resource_signature(_git_show(head, SHARED_RESOURCES))
        )
    if SHARED_SCHEMA in changed:
        semantic[SHARED_SCHEMA] = (
            _schema_signature(_git_show(base, SHARED_SCHEMA))
            != _schema_signature(_git_show(head, SHARED_SCHEMA))
        )
    if SHARED_DISPATCH in changed:
        semantic[SHARED_DISPATCH] = (
            _dispatch_r3_signature(_git_show(base, SHARED_DISPATCH))
            != _dispatch_r3_signature(_git_show(head, SHARED_DISPATCH))
        )
    return semantic

def _spec(mode: str):
    if mode == "ux":
        allowed = UX_ALLOWED
        shared = {SHARED_RESOURCES}
        forbidden: Callable[[str], bool] = lambda p: (
            (p.startswith("wa_backend/") and p != "wa_backend/tests/live_stock_operational_browser_support.py")
            or p == "LIVE_STOCK_V1_CLOSURE_PLAN.md"
            or p.startswith(("flutter_app/", "wanasah_frontend/"))
        )
        label = "LIVE_STOCK_UX_SCOPE"
    elif mode == "r3":
        allowed = R3_ALLOWED
        shared = {SHARED_SCHEMA, SHARED_DISPATCH}
        forbidden = lambda p: (
            p == "LIVE_STOCK_V1_CLOSURE_PLAN.md"
            or p.startswith("dashboard/")
            or p.startswith("wanasah_frontend/")
        )
        label = "P0_R3_SCOPE"
    elif mode == "operational":
        allowed = OP_ALLOWED
        shared = {SHARED_RESOURCES}
        forbidden = lambda p: False
        label = "OPERATIONAL_BROWSER_OWNERSHIP"
    else:
        raise ValueError(mode)
    hard_owned = allowed - shared - POLICY_FILES
    return allowed, shared, hard_owned, forbidden, label

def classify(mode: str, changed: set[str], semantic: dict[str, bool]) -> tuple[str, list[str]]:
    if changed & SESSION_ISOLATION_ROOTS:
        extra = sorted(changed - SESSION_ISOLATION_ALLOWED)
        if extra:
            return "fail", [f"AUTH_SESSION_SCOPE=FAIL extra={extra}"]
        return "session-isolation-repair", []
    allowed, shared, hard_owned, forbidden, label = _spec(mode)
    if changed and changed <= POLICY_FILES:
        return "policy-maintenance", []
    relevant_shared = {path for path in shared if semantic.get(path, False)}
    owned = (changed & hard_owned) | relevant_shared
    if not owned:
        return "not-applicable", []
    effective_allowed = set(allowed)
    for path in shared:
        if path not in relevant_shared:
            effective_allowed.discard(path)
    extra = sorted(changed - effective_allowed)
    if extra:
        return "fail", [f"{label}=FAIL extra={extra}"]
    forbidden_paths = sorted(path for path in changed if forbidden(path))
    if forbidden_paths:
        return "fail", [f"{label}=FAIL forbidden={forbidden_paths}"]
    return "owned", []

def _expect_fail(mode: str, changed: set[str], semantic: dict[str, bool]) -> None:
    state, messages = classify(mode, changed, semantic)
    assert state == "fail" and messages, (mode, state, messages)

def selftest() -> None:
    false_positive = {
        ".github/workflows/dispatch-p0-route-stock-safety.yml",
        "dashboard/src/components/dispatch/RouteManagementModal.tsx",
        "dashboard/src/features/dispatch/routeStatusPayload.ts",
        "dashboard/src/i18n/dispatchRouteSafety.ts",
        SHARED_RESOURCES,
        "dashboard/src/pages/DispatchBoard.tsx",
        "dashboard/src/test/dispatch-p0-route-stock-safety.test.tsx",
        "dashboard/src/test/dispatch-product-discovery.test.tsx",
        SHARED_DISPATCH,
        "wa_backend/tests/test_dispatch_p0_route_stock_safety_postgres.py",
    }
    none = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for mode in ("ux", "r3", "operational"):
        state, messages = classify(mode, false_positive, none)
        assert state == "not-applicable" and not messages, (mode, state, messages)

    assert classify("ux", {"dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx"}, none)[0] == "owned"
    _expect_fail("ux", {"dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx", "dashboard/src/pages/DispatchBoard.tsx"}, none)
    assert classify("r3", {"wa_backend/domains/live_stock_projection/service.py"}, none)[0] == "owned"
    _expect_fail("r3", {"wa_backend/domains/live_stock_projection/service.py", "dashboard/src/pages/DispatchBoard.tsx"}, none)
    assert classify("operational", {"dashboard/e2e/live-stock-physical-custody.spec.ts"}, none)[0] == "owned"
    _expect_fail("operational", {"dashboard/e2e/live-stock-physical-custody.spec.ts", "dashboard/src/pages/DispatchBoard.tsx"}, none)

    base_resources = (
        'dispatchRouteSafety: { confirm: "old" },\n'
        'inventoryLive: { warehouseBalanceHint: "AR warehouse", '
        'withVehiclesHint: "AR vehicle", vehicleScopes: { NO_ACCESS: "AR hidden" } },\n'
        'x: "x",\nLIVE_STOCK_RESPONSE_INVALID: "old",\nliveStockCount: "old",\n'
        'inventoryLive: { warehouseBalanceHint: "EN warehouse", '
        'withVehiclesHint: "EN vehicle", vehicleScopes: { NO_ACCESS: "EN hidden" } },\n'
    )
    unrelated_resources = base_resources.replace(
        'dispatchRouteSafety: { confirm: "old" }',
        'dispatchRouteSafety: { confirm: "new" }',
    )
    live_resources = base_resources.replace(
        'LIVE_STOCK_RESPONSE_INVALID: "old"',
        'LIVE_STOCK_RESPONSE_INVALID: "new"',
    )
    warehouse_hint_resources = base_resources.replace("AR warehouse", "AR warehouse changed")
    vehicle_hint_resources = base_resources.replace("EN vehicle", "EN vehicle changed")
    vehicle_scope_resources = base_resources.replace("AR hidden", "AR hidden changed")
    assert len(_object_sections(base_resources, "inventoryLive")) == 2
    assert _resource_signature(base_resources) == _resource_signature(unrelated_resources)
    assert _resource_signature(base_resources) != _resource_signature(live_resources)
    assert _resource_signature(base_resources) != _resource_signature(warehouse_hint_resources)
    assert _resource_signature(base_resources) != _resource_signature(vehicle_hint_resources)
    assert _resource_signature(base_resources) != _resource_signature(vehicle_scope_resources)
    live_sem = {**none, SHARED_RESOURCES: True}
    assert classify("ux", {SHARED_RESOURCES}, live_sem)[0] == "owned"
    _expect_fail("ux", {SHARED_RESOURCES, "dashboard/src/pages/DispatchBoard.tsx"}, live_sem)
    assert classify("operational", {SHARED_RESOURCES}, live_sem)[0] == "owned"

    base_dispatch = (
        "from models import DispatchRoute, InventoryBalance\n"
        "from sqlalchemy import select, func\n"
        "async def update_route_status(db, route_id):\n"
        "    route = await db.scalar(select(DispatchRoute).where(DispatchRoute.id == route_id))\n"
        "    return route.status\n"
    )
    unrelated_dispatch = base_dispatch.replace(
        "return route.status",
        "route.status = 'active'\n    return route.status",
    )
    bad_dispatch = (
        base_dispatch +
        "from domains.live_stock_projection.service import refresh_live_stock_vehicle_attribution\n"
        "async def refresh_old_attribution():\n"
        "    return await refresh_live_stock_vehicle_attribution()\n"
    )
    direct_sql_dispatch = (
        "from models import DispatchRoute as Route, InventoryBalance as Balance\n"
        "from sqlalchemy import select, func\n"
        "async def route_source_vehicle_stock(db):\n"
        "    stmt = select(Route.source_location_id, func.sum(Balance.quantity)).join(\n"
        "        Balance, Balance.location_id == Route.vehicle_id\n"
        "    ).group_by(Route.source_location_id)\n"
        "    return await db.execute(stmt)\n"
    )
    assert _dispatch_r3_signature(base_dispatch) == _dispatch_r3_signature(unrelated_dispatch)
    assert _dispatch_r3_signature(base_dispatch) != _dispatch_r3_signature(bad_dispatch)
    assert _dispatch_r3_signature(base_dispatch) != _dispatch_r3_signature(direct_sql_dispatch)
    assert any(
        item.startswith("DIRECT_ROUTE_SOURCE_SQL:")
        for item in _dispatch_r3_signature(direct_sql_dispatch)
    )
    r3_dispatch_sem = {**none, SHARED_DISPATCH: True}
    assert classify("r3", {SHARED_DISPATCH}, r3_dispatch_sem)[0] == "owned"
    _expect_fail("r3", {SHARED_DISPATCH, "dashboard/src/pages/DispatchBoard.tsx"}, r3_dispatch_sem)

    base_schema = (
        "from pydantic import BaseModel\n"
        "PositiveDbInt = int\n"
        "class WarehouseInventoryItem(BaseModel):\n    id: PositiveDbInt\n"
        "class WarehouseInventoryCursorPage(BaseModel):\n    item: WarehouseInventoryItem\n"
        "class WarehouseInventorySummaryResponse(BaseModel):\n    total: int\n"
        "class WarehouseInventoryAlertSummaryResponse(BaseModel):\n    total: int\n"
        "class WarehouseInventoryBatchProductOption(BaseModel):\n    id: PositiveDbInt\n"
        "class WarehouseInventoryBatchProductCursorPage(BaseModel):\n    item: WarehouseInventoryBatchProductOption\n"
        "class WarehouseInventoryBatchItem(BaseModel):\n    id: PositiveDbInt\n"
        "class WarehouseInventoryBatchDetailResponse(BaseModel):\n    item: WarehouseInventoryBatchItem\n"
        "class WarehouseAlertItem(BaseModel):\n    id: PositiveDbInt\n"
        "class Unrelated(BaseModel):\n    value: int\n"
    )
    unrelated_schema = base_schema.replace("value: int", "value: str")
    root_schema = base_schema.replace("total: int", "total: str", 1)
    import_schema = base_schema.replace("from pydantic import BaseModel", "from pydantic.v1 import BaseModel")
    assert _schema_signature(base_schema) == _schema_signature(unrelated_schema)
    assert _schema_signature(base_schema) != _schema_signature(root_schema)
    assert _schema_signature(base_schema) != _schema_signature(import_schema)
    r3_schema_sem = {**none, SHARED_SCHEMA: True}
    assert classify("r3", {SHARED_SCHEMA}, r3_schema_sem)[0] == "owned"
    _expect_fail("r3", {SHARED_SCHEMA, "dashboard/src/pages/DispatchBoard.tsx"}, r3_schema_sem)

    for mode in ("ux", "r3", "operational"):
        state, messages = classify(mode, set(POLICY_FILES), none)
        assert state == "policy-maintenance" and not messages
    for mode in ("ux", "r3", "operational"):
        assert classify(mode, set(SESSION_ISOLATION_ALLOWED), none)[0] == "session-isolation-repair"
        for foreign in ("wa_backend/api/dispatch.py", "wa_backend/services.py",
                        "wanasah_frontend/lib/main.dart", "LIVE_STOCK_V1_CLOSURE_PLAN.md"):
            _expect_fail(mode, set(SESSION_ISOLATION_ALLOWED) | {foreign}, none)
    print("LIVE_STOCK_OWNERSHIP_SELFTEST=PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--mode", choices=("ux", "r3", "operational"))
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        if not args.mode:
            return 0
    if not args.mode or not args.base:
        parser.error("--mode and --base are required unless only --selftest is used")
    head = _git("rev-parse", args.head)
    base_ref = _git("rev-parse", args.base)
    if not re.fullmatch(r"[0-9a-f]{40}", head) or not re.fullmatch(r"[0-9a-f]{40}", base_ref):
        raise SystemExit("invalid ownership base/head")
    base = _git("merge-base", base_ref, head)
    subprocess.run(["git", "diff", "--check", base, head], check=True)
    changed = _changed(base, head)
    if changed & SESSION_ISOLATION_ROOTS and "dashboard/src/pages/DispatchBoard.tsx" in changed:
        before = _git_show(base, "dashboard/src/pages/DispatchBoard.tsx")
        after = _git_show(head, "dashboard/src/pages/DispatchBoard.tsx")
        def without_socket(source: str) -> str:
            source = re.sub(r'^import .* from "@/lib/authStorage";\n', "", source, flags=re.M)
            source = source.replace('import { useDashboardSession } from "@/hooks/useDashboardSession";\n', "")
            boundary = """export default function DispatchBoard() {
  const session = useDashboardSession();
  return session ? <DispatchSession key={JSON.stringify(session)} /> : null;
}

function DispatchSession() {"""
            source = source.replace(boundary, "export default function DispatchBoard() {")
            start = source.index("  // Realtime dispatch updates:")
            end = source.index("\n  useEffect(() => {\n    if (!selectedVehicleId)", start)
            return source[:start] + source[end:]
        if without_socket(before) != without_socket(after):
            raise SystemExit("AUTH_SESSION_SCOPE=FAIL Dispatch outside socket lifetime")
    semantic = _shared_semantics(base, head, changed)
    state, messages = classify(args.mode, changed, semantic)
    if messages:
        raise SystemExit("\n".join(messages))
    label = _spec(args.mode)[4]
    print(f"{label}=PASS mode={state} files={len(changed)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
