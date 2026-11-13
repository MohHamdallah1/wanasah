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
# A P0 ownership policy edit is only compatible with a verified,
# specifically owned inventory minimum UX + test + AR/EN copy change.
MINIMUM_UX_CROSSOVER = {".github/workflows/dispatch-p0-route-stock-safety.yml"}

SHARED_RESOURCES = "dashboard/src/i18n/resources.ts"
SHARED_SCHEMA = "wa_backend/schemas.py"
SHARED_DISPATCH = "wa_backend/api/dispatch.py"

UX_ALLOWED = {
    # The dedicated in-flight workflow validates this view's freshness state.
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
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
    "dashboard/e2e/live-stock-operational.spec.ts",
    "dashboard/e2e/live-stock-v1.fixtures.ts",
    SHARED_RESOURCES,
    "dashboard/src/components/dashboard/WorkspaceTopBar.css",
    "dashboard/src/pages/inventory/InventoryTopDock.tsx",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/StockMinimumManager.tsx",
    "dashboard/src/pages/inventory/StockMinimumManager.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/Tab2Inbound.tsx",
    # G06 inventory-page loading geometry: exact owner-reviewed presentation surfaces.
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexTable.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerTable.tsx",
    "dashboard/src/test/inventory-cp13-operations-consistency.test.tsx",
    "dashboard/src/pages/inventory/TabWarehouseLocations.tsx",
    "dashboard/src/pages/inventory/inventory.css",
    "dashboard/src/pages/inventory/inventoryShellPolish.css",
    "dashboard/src/pages/inventory/inventoryTopDockController.ts",
    "dashboard/src/pages/inventory/liveStock/BatchDetailPanel.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockFilters.tsx",
    "dashboard/src/pages/inventory/liveStock/CommercialQuantityDisplay.tsx",
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
    # Exact migration-owned search artifacts; RLS/cost/UI/plan remain excluded.
    "wa_backend/alembic/env.py",
    "wa_backend/alembic/versions/c9a1e4d7b630_live_stock_arabic_exact_name_search.py",
    "wa_backend/tests/test_live_stock_arabic_exact_search.py",
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
    # Keep the exact UI authority evidence workflow in combined browser scope.
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
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
    "dashboard/src/pages/inventory/StockMinimumManager.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/TabWarehouseLocations.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexTable.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerTable.tsx",
    "dashboard/src/test/inventory-cp13-operations-consistency.test.tsx",
    "dashboard/src/pages/inventory/inventory.css",
    "dashboard/src/pages/inventory/inventoryShellPolish.css",
    "dashboard/src/pages/inventory/inventoryTopDockController.ts",
    "dashboard/src/pages/inventory/liveStock/BatchDetailPanel.tsx",
    "dashboard/src/pages/inventory/liveStock/CommercialQuantityDisplay.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx",
    "dashboard/src/pages/inventory/liveStock/i18n.ts",
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
# Worker 1 may intentionally combine the Live Stock consumer/copy correction with
# the existing operational Chromium proof in one PR. This crossover admits only
# the exact CI policy workflow plus the bounded Worker1 frontend/test evidence.
WORKER1_COMBINED_CLOSURE = {
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/live-stock-operational.journey.ts",
    "dashboard/e2e/live-stock-operational.spec.ts",
    "dashboard/e2e/live-stock-operational.support.ts",
    "dashboard/src/pages/inventory/liveStock/i18n.ts",
}

SESSION_ISOLATION_ALLOWED = {
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/inventory-cp6-minimum-stock-dashboard-acceptance.yml",
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
    "dashboard/src/test/auth-session-page-boundary.test.tsx",
    "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx",
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

# PR #710: bounded backend SQL/performance work may legitimately accompany
# live_stock.py without becoming an R3 physical-custody implementation wave.
# Keep this allowlist intentionally exact; movement/cost/security/UI/plan files
# remain forbidden and are covered by negative self-tests below.
PERFORMANCE_ACCEPTANCE_ROOTS = {
    ".github/workflows/live-stock-r4-final-performance.yml",
    "wa_backend/scripts/gate_live_stock_r4_final.py",
    "wa_backend/scripts/live_stock_r4_final_fixture.py",
    "wa_backend/scripts/live_stock_r4_final_profile.py",
}
PERFORMANCE_ACCEPTANCE_ALLOWED = PERFORMANCE_ACCEPTANCE_ROOTS | {
    HELPER,
    # Exact migration-owned search artifacts; RLS/cost/UI/plan remain excluded.
    "wa_backend/alembic/env.py",
    "wa_backend/alembic/versions/c9a1e4d7b630_live_stock_arabic_exact_name_search.py",
    "wa_backend/tests/test_live_stock_arabic_exact_search.py",
    "wa_backend/api/warehouse/live_stock.py",
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
    # Minimum-stock UX is an inventory-owned surface too. Whitelist only its
    # exact AR/EN object sections; unrelated shared i18n remains unowned.
    entries.extend(
        f"inventoryMinimum[{index}]={section}"
        for index, section in enumerate(_object_sections(source, "inventoryMinimum"))
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

# A single owner-approved cross-domain change couples minimum policy and
# Live Stock membership, with narrow frontend and real-PG acceptance.
# Existing UX/R3/operational ownership gates stay strict for every other PR.
WAREHOUSE_VIEW_REQUIRED = {
    "wa_backend/api/inventory_stock_policy.py",
    "wa_backend/api/warehouse/live_stock.py",
    "wa_backend/tests/test_inventory_minimum_stock_capability_parity.py",
    "wa_backend/tests/test_live_stock_r1_sql_postgres.py",
    "dashboard/src/pages/inventory/StockMinimumManager.tsx",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockFilters.tsx",
    "dashboard/src/test/live-stock-filter-state-recovery.test.tsx",
}

# Owner-approved seamless Live Stock re-entry + exact unavailable-cause repair.
# This is intentionally a one-contract crossover: it must include the route
# lifetime boundary, the Live Stock explanation surface, and the canonical
# batch-detail response together. It does not authorize unrelated dashboard,
# movement, costing, dispatch, or backend work.
SEAMLESS_REENTRY_EXPLANATION_REQUIRED = {
    "dashboard/src/App.tsx",
    "dashboard/src/components/operations/DashboardLayout.tsx",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/liveStock/BatchDetailPanel.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx",
    "dashboard/src/pages/inventory/liveStock/i18n.ts",
    "dashboard/src/pages/inventory/liveStock/sourceContract.ts",
    "dashboard/src/pages/inventory/liveStock/useLiveStockBatchDetail.ts",
    "wa_backend/api/warehouse/live_stock_source_detail.py",
}
SEAMLESS_REENTRY_EXPLANATION_ALLOWED = (
    SEAMLESS_REENTRY_EXPLANATION_REQUIRED
    | {
        HELPER,
        ".github/workflows/live-stock-r4-final-performance.yml",
        ".github/workflows/inventory-cp2-batch-index-acceptance.yml",
        ".github/workflows/live-stock-inflight-authority-acceptance.yml",
        ".github/workflows/live-stock-v1-browser-acceptance.yml",
        "dashboard/e2e/live-stock-v1.spec.ts",
        "dashboard/src/test/auth-session-page-boundary.test.tsx",
        "dashboard/src/test/inventory-cp7-live-stock.test.tsx",
        "dashboard/src/test/live-stock-warm-authority.test.tsx",
        "dashboard/src/test/live-stock-ui-stability.test.ts",
        "dashboard/src/test/live-stock-warehouse-discovery.test.tsx",
        "wa_backend/scripts/warehouse_route_manifest_extensions.json",
        "wa_backend/tests/test_cp7_live_stock_postgres.py",
    }
)

WAREHOUSE_VIEW_ALLOWED = WAREHOUSE_VIEW_REQUIRED | {
    ".github/workflows/inventory-cp13-shell-polish.yml",
    "wa_backend/scripts/live_stock_r4_final_profile.py",
    "dashboard/e2e/live-stock-operational.journey.ts",
    "dashboard/e2e/live-stock-operational.spec.ts",
    HELPER,
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/inventory-cp6-minimum-stock-acceptance.yml",
    ".github/workflows/inventory-cp6-minimum-stock-dashboard-acceptance.yml",
    ".github/workflows/live-stock-r4-final-performance.yml",
    "dashboard/src/i18n/resources.ts",
    "dashboard/src/pages/inventory/liveStock/contracts.ts",
    "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx",
    "dashboard/src/test/live-stock-batch-refresh-integration.test.tsx",
    "dashboard/src/test/live-stock-count-freshness-semantics.test.tsx",
    "dashboard/src/test/live-stock-family-cursor.test.tsx",
    "dashboard/src/test/live-stock-local-failure.test.tsx",
    "dashboard/src/test/live-stock-render-performance.benchmark.test.tsx",
    "dashboard/src/test/live-stock-render-windowing.test.tsx",
}


# PR #746 / #740: exact, bounded V1 Batches reentry acceptance.
# A shared Inventory shell file triggers both Live Stock ownership workflows.
# Only this complete, independently tested eight-file correction (plus this
# owning policy file) is admitted. A partial or combined foreign scope still
# takes the unchanged standard ownership checks.
IT03_IT04_REENTRY_REQUIRED = {
    ".github/workflows/inventory-it03-it04-v1-acceptance.yml",
    "dashboard/e2e/inventory-batch-reentry.config.ts",
    "dashboard/e2e/inventory-batch-reentry.spec.ts",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/TabBatches.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexTable.tsx",
    "dashboard/src/pages/inventory/batches/batch-reentry.test.tsx",
    "dashboard/src/pages/inventory/batches/useBatchIndex.ts",
}
IT03_IT04_REENTRY_ALLOWED = IT03_IT04_REENTRY_REQUIRED | {HELPER}


# IT-03 remaining Dashboard V1: only the full, independently tested
# five-tab reentry correction is allowed through shared Live Stock gates.
# This is an exact-file scope, NOT a wildcard for inventory components.
IT03_REMAINING_REQUIRED = {
    ".github/workflows/inventory-it03-remaining-v1-acceptance.yml",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab2Inbound.tsx",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/TabTransfers.tsx",
    "dashboard/src/pages/inventory/TabWarehouseLocations.tsx",
    "dashboard/src/pages/inventory/it03-remaining-reentry.test.tsx",
    "dashboard/src/pages/inventory/ledger/useLedgerQuery.ts",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeLifecycle.ts",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeSessions.ts",
    "dashboard/src/pages/inventory/transfers/TransferRowActions.tsx",
    "dashboard/src/pages/inventory/transfers/TransferTable.tsx",
    "dashboard/src/pages/inventory/transfers/hooks/useTransferCreate.ts",
    "dashboard/src/pages/inventory/transfers/hooks/useTransferList.ts",
    "dashboard/src/pages/inventory/transfers/types.ts",
    "dashboard/src/test/inventory-cp13-warehouse-presentation.test.tsx",
}
IT03_REMAINING_ALLOWED = {
    ".github/workflows/inventory-it03-remaining-v1-acceptance.yml",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab2Inbound.tsx",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/TabTransfers.tsx",
    "dashboard/src/pages/inventory/TabWarehouseLocations.tsx",
    "dashboard/src/pages/inventory/it03-remaining-reentry.test.tsx",
    "dashboard/src/pages/inventory/ledger/useLedgerQuery.ts",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeLifecycle.ts",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeSessions.ts",
    "dashboard/src/pages/inventory/transfers/TransferRowActions.tsx",
    "dashboard/src/pages/inventory/transfers/TransferTable.tsx",
    "dashboard/src/pages/inventory/transfers/hooks/useTransferCreate.ts",
    "dashboard/src/pages/inventory/transfers/hooks/useTransferList.ts",
    "dashboard/src/pages/inventory/transfers/types.ts",
    "dashboard/src/test/inventory-cp13-warehouse-presentation.test.tsx",
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/inventory-cp13-shell-polish.yml",
    ".github/workflows/inventory-cp6-minimum-stock-dashboard-acceptance.yml",
}


# Owner-approved, read-only V1 Live Stock detail visual closure. Exact files;
# security/stock/cost/dispatch backend edits are forbidden, including in tests.
OWNER_VISUAL_REQUIRED = {
    "ARCHITECTURE.md",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
    "dashboard/src/pages/inventory/liveStock/BatchDetailPanel.tsx",
    "dashboard/src/test/inventory-cp7-live-stock.test.tsx",
}
OWNER_VISUAL_ALLOWED = OWNER_VISUAL_REQUIRED | {
    HELPER,
    ".github/workflows/inventory-it03-remaining-v1-acceptance.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    "dashboard/e2e/live-stock-operational.journey.ts",
    "dashboard/e2e/live-stock-operational.spec.ts",
    "dashboard/e2e/live-stock-ux-closure.spec.ts",
    "dashboard/src/i18n/resources.ts",
    "dashboard/src/pages/inventory/liveStock/CommercialQuantityDisplay.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx",
    "dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx",
    "dashboard/src/pages/inventory/liveStock/VehicleCustodyQuantity.tsx",
    "dashboard/src/pages/inventory/liveStock/i18n.ts",
    "dashboard/src/test/live-stock-batch-detail-freshness.test.tsx",
}


# PR #758: a complete, specifically owned Batches selector/summary/UOM fix.
# Shared BatchIndexTable triggers UX/operational gates; admit this exact
# acceptance set only. No broad inventory wildcard or bypass of the gates.
BATCH_SELECTOR_OWNER_REQUIRED = {
    ".github/workflows/batches-selector-owner-acceptance.yml",
    "dashboard/e2e/batches-selector-owner.config.ts",
    "dashboard/e2e/batches-selector-owner.spec.ts",
    "dashboard/src/pages/inventory/TabBatches.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexFilters.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexSummary.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexTable.tsx",
    "dashboard/src/pages/inventory/batches/batchUiNotes.ts",
    "dashboard/src/pages/inventory/batches/useBatchSelectorDiscovery.ts",
    "dashboard/src/test/inventory-cp13-batches-browser.mjs",
    "dashboard/src/test/inventory-cp13-batches-presentation.test.tsx",
    "dashboard/src/test/inventory-cp2-batches-dashboard.test.tsx",
}
BATCH_SELECTOR_OWNER_ALLOWED = BATCH_SELECTOR_OWNER_REQUIRED | {HELPER}


# PR #769: one verified Batches full-width correction, plus the real
# AR/EN browser geometry acceptance. No other inventory, auth or Backend files.
BATCHES_LAYOUT_769_REQUIRED = {
    "dashboard/src/pages/inventory/inventory.css",
    "dashboard/e2e/batches-selector-owner.spec.ts",
}
BATCHES_LAYOUT_769_ALLOWED = BATCHES_LAYOUT_769_REQUIRED | {HELPER}


# V1 Batches compact toolbar: exact UI/authorized chooser and admission tests.
# This cannot bypass stock, cost, auth, Flutter or other inventory controls.
BATCHES_COMPACT_V1_REQUIRED = {
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/TabBatches.tsx",
    "dashboard/src/pages/inventory/batches/BatchIndexFilters.tsx",
    "dashboard/src/pages/inventory/batches/BatchSearchSelect.tsx",
    "dashboard/src/pages/inventory/batches/useBatchSelectorDiscovery.ts",
    "dashboard/src/pages/inventory/batches/batchIndexI18n.ts",
    "dashboard/src/pages/inventory/batches/batchUiNotes.ts",
    "dashboard/e2e/batches-selector-owner.spec.ts",
    "dashboard/e2e/inventory-batch-reentry.spec.ts",
    "dashboard/src/test/inventory-cp2-batches-dashboard.test.tsx",
}
BATCHES_COMPACT_V1_ALLOWED = BATCHES_COMPACT_V1_REQUIRED | {HELPER}


# Issue #762: exact Ledger reference revocation and physical evidence ownership.
# Both operational and UX modes must recognize this entire bounded scope,
# never arbitrary inventory/backend/test files.
LEDGER_762_REQUIRED = {
    ".github/workflows/inventory-ledger-762-acceptance.yml",
    "dashboard/e2e/ledger-762.config.ts",
    "dashboard/e2e/ledger-762.spec.ts",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerMobileCards.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerReferenceModal.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerTable.tsx",
    "dashboard/src/pages/inventory/ledger/contracts.ts",
    "dashboard/src/pages/inventory/ledger/ledgerI18n.ts",
    "dashboard/src/pages/inventory/ledger/ledgerPresentation.ts",
    "dashboard/src/pages/inventory/ledger/useLedgerReference.ts",
    "dashboard/src/test/inventory-cp10-ledger-contract.test.ts",
    "dashboard/src/test/inventory-access.test.ts",
    "dashboard/src/test/inventory-cp10-ledger-revocation.test.tsx",
    "wa_backend/api/warehouse/ledger.py",
    "wa_backend/domains/ledger/read.py",
    "wa_backend/tests/test_cp10_ledger_postgres.py",
    "wa_backend/tests/test_inbound_no_lot_frozen_contract.py",
}
LEDGER_762_ALLOWED = LEDGER_762_REQUIRED | {HELPER}


# Owner-approved Stocktake operator UX PR #784. MainInventory is a shared
# entrypoint that triggers both Live Stock browser gates. Admit only the FULL,
# independently tested ten-file PR #784 diff, never a generic Stocktake
# directory/prefix or a subset combined with unrelated code/CI changes.
STOCKTAKE_784_EXACT = frozenset({
    ".github/workflows/stocktake-v1-operator-782.yml",
    "dashboard/e2e/stocktake-v1-ux-776.spec.ts",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeCountingPanel.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeCycleStartModal.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeOperatorUx782.test.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeReviewPanel.tsx",
    "dashboard/src/pages/inventory/stocktake/hooks/useCycleCountStart.ts",
    "dashboard/src/pages/inventory/stocktake/uiCopy.ts",
})


# Isolated, owner-approved final single-toolbar UX PR #789. No broad
# directory allowlist; MainInventory is shared with Live Stock consumers.
STOCKTAKE_789_SHELL_EXACT = frozenset({
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeSessionCenter.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeShellLayout.test.tsx",
    "dashboard/e2e/stocktake-shell-782/stocktake-v1-ux-776.spec.ts",
})
# Exactly the four independently reviewed CI policy files in this PR.
STOCKTAKE_FINAL_CI_782_EXACT = frozenset({
    ".github/workflows/stocktake-v1-operator-782.yml",
    ".github/workflows/stocktake-v1-discovered-pg16-ui.yml",
    ".github/workflows/stocktake-v1-review-779.yml",
    HELPER,
})


# Final owner-approved screenshot density PR #792 changes shared MainInventory.
# Only the exact five-file set is admitted to Live Stock UX/operational checks.
STOCKTAKE_792_DIALOG_EXACT = STOCKTAKE_789_SHELL_EXACT
# Separate history-preserving CI and Chromium test compatibility bridge.
STOCKTAKE_793_BRIDGE_EXACT = frozenset(
    set(STOCKTAKE_FINAL_CI_782_EXACT) | {"dashboard/e2e/stocktake-v1-ux-776.spec.ts"}
)


# #804: Ledger reference navigation, reviewed as one nine-file bounded PR.
# It touches the shared Ledger tab but is NOT the historical #762 full scope.
# No subset, extra file, or mixed ownership scope inherits this exception.
LEDGER_804_EXACT = frozenset({
    ".github/workflows/inventory-ledger-762-acceptance.yml",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/buildLedgerCursorUrl.ts",
    "dashboard/src/pages/inventory/ledger/ledgerI18n.ts",
    "dashboard/src/pages/inventory/ledger/stocktakeLedgerNavigation.ts",
    "dashboard/src/pages/inventory/ledger/useLedgerQuery.ts",
    "dashboard/src/pages/inventory/ledger/useLedgerReference.ts",
    "dashboard/src/test/inventory-cp10-ledger-contract.test.ts",
    "dashboard/src/test/inventory-cp10-ledger-dashboard.test.tsx",
})


# #811: exact owner-approved Ledger V1 functional-parity and test fixture diff.
# This is only the complete thirteen-file set; mixed scopes, partial diffs,
# unrelated Backend/Flutter files and the policy helper cannot hitchhike.
LEDGER_811_EXACT = frozenset({
    "dashboard/e2e/ledger-762.spec.ts",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerAdjustmentModal.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerCostEvidence.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerMobileCards.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerReferenceModal.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerTable.tsx",
    "dashboard/src/pages/inventory/ledger/contracts.ts",
    "dashboard/src/pages/inventory/ledger/ledgerI18n.ts",
    "dashboard/src/pages/inventory/ledger/useLedgerAdjustment.ts",
    "dashboard/src/test/inventory-cp10-ledger-contract.test.ts",
    "dashboard/src/test/inventory-cp10-ledger-dashboard.test.tsx",
    "dashboard/src/test/inventory-cp10-ledger-keyboard.test.tsx",
})


# Reused for Ledger V1 visual-only white selectors / movement count polish.
# Exact Ledger owner visual toolbar polish: move the existing authorized
# warehouse selector into LedgerFilters and label the real movement count.
# Do not admit partial or mixed scopes or change Live Stock ownership.
LEDGER_TOOLBAR_EXACT = frozenset({
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerFilters.tsx",
    "dashboard/src/pages/inventory/ledger/ledgerI18n.ts",
    "dashboard/src/test/inventory-cp10-ledger-dashboard.test.tsx",
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/inventory-ledger-762-acceptance.yml",
})


# #818 exact owner-approved two-stage Ledger frontend scope. No prefixes or
# mixed-domain exemptions. Stage B's stacked PR can be based on main temporarily
# for independent CI; after Stage A merge, only the B-only exact set matches.
LEDGER_818_STAGE_A_EXACT = frozenset({
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerMobileCards.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerTable.tsx",
    "dashboard/src/pages/inventory/ledger/useLedgerQuery.ts",
    "dashboard/src/pages/inventory/ledger/useLedgerWindow.ts",
    "dashboard/src/test/inventory-cp10-ledger-dashboard.test.tsx",
})
LEDGER_818_STAGE_B_EXACT = frozenset({
    ".github/workflows/inventory-ledger-762-acceptance.yml",
    "dashboard/e2e/ledger-762.spec.ts",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerOperationDetails.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerOperationRows.tsx",
    "dashboard/src/pages/inventory/ledger/operationContracts.ts",
    "dashboard/src/pages/inventory/ledger/operationI18n.ts",
    "dashboard/src/pages/inventory/ledger/useLedgerOperations.ts",
    "dashboard/src/test/inventory-cp10-ledger-dashboard.test.tsx",
    "dashboard/src/test/inventory-cp10-ledger-operations.test.tsx",
})
LEDGER_818_STACKED_EXACT = LEDGER_818_STAGE_A_EXACT | LEDGER_818_STAGE_B_EXACT


# #825: exact owner-reviewed Ledger visual gate only; does not grant Ledger
# or Live Stock authority to unrelated test, runtime, backend, or Flutter paths.
LEDGER_825_VISUAL_EXACT = frozenset({
    "dashboard/e2e/ledger-762.spec.ts",
    "dashboard/src/pages/inventory/Tab4Ledger.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerOperationDetails.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerOperationRows.tsx",
    "dashboard/src/pages/inventory/ledger/LedgerReferenceModal.tsx",
    "dashboard/src/pages/inventory/ledger/operationI18n.ts",
    "dashboard/src/test/inventory-cp10-ledger-operations.test.tsx",
})

# #881: one commercial-preflight implementation plus its precise strict CI
# owner gates; never a wildcard for new Dispatch, Inventory or Backend files.
DISPATCH_D11_881_EXACT = frozenset({
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/dispatch-d11-commercial-preflight.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-shortage-group-d05-acceptance.yml",
    ".github/workflows/live-stock-g04-outage-recovery.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
    "dashboard/src/features/dispatch/commercialPreflight/contract.ts",
    "dashboard/src/features/dispatch/commercialPreflight/useCommercialPreflight.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-d11-commercial-preflight.test.tsx",
    "dashboard/src/test/dispatch-route-launch-d07.test.tsx",
    "wa_backend/api/dispatch_commercial_preflight.py",
    "wa_backend/main.py",
    "wa_backend/tests/test_dispatch_commercial_preflight_d11_postgres.py",
})
assert len(DISPATCH_D11_881_EXACT) == 16

# #877: the complete, single-PR D13 AR/EN, currency and keyboard closure.
# Match the entire literal diff (including both ownership gates). It cannot
# authorize new DispatchBoard, auth storage, backend, stock, or other work.
DISPATCH_D13_877_EXACT = frozenset({
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/dispatch-d13-accessibility.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/src/components/dispatch/ShopBulkImportModal.tsx",
    "dashboard/src/components/dispatch/ShopFormModal.tsx",
    "dashboard/src/components/dispatch/ShopTable.tsx",
    "dashboard/src/components/dispatch/ShortageModal.tsx",
    "dashboard/src/components/dispatch/ZoneModal.tsx",
    "dashboard/src/features/dispatch/dispatchUiText.ts",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
    "dashboard/src/test/dispatch-d10-import.test.tsx",
    "dashboard/src/test/dispatch-d13-accessibility.test.tsx",
    "dashboard/src/test/dispatch-load-context.test.tsx",
    "dashboard/src/test/dispatch-shop-metadata-finance-v1.test.tsx",
    "dashboard/src/test/dispatch-shop-reorder-scope-v1.test.tsx",
    "dashboard/src/test/dispatch-shortage-group-recovery-v1.test.tsx",
})
assert len(DISPATCH_D13_877_EXACT) == 16

# #847: #846 is Dispatch ShopOrder ownership, not a grant to modify
# Live Stock, inventory, auth/session, or unrelated Dispatch files. Freeze
# all nine actual PR paths, including the shared DispatchBoard consumer.
SHOP_ORDER_843_EXACT = frozenset({
    "dashboard/src/components/dispatch/ShopTable.tsx",
    "dashboard/src/features/dispatch/shopOrder/ShopOrderScopeNotice.tsx",
    "dashboard/src/features/dispatch/shopOrder/messages.ts",
    "dashboard/src/features/dispatch/shopOrder/persist.ts",
    "dashboard/src/features/dispatch/shopOrder/scope.ts",
    "dashboard/src/features/dispatch/shopOrder/useShopOrderCommit.ts",
    "dashboard/src/features/dispatch/shopOrder/useShopOrderDraft.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-shop-reorder-scope-v1.test.tsx",
})
SHOP_ORDER_843_NEW = SHOP_ORDER_843_EXACT - {"dashboard/src/pages/DispatchBoard.tsx"}
assert len(SHOP_ORDER_843_EXACT) == 9 and len(SHOP_ORDER_843_NEW) == 8

# #872: exact all eleven D10 business/test paths + three shared CI gates.
DISPATCH_D10_872_EXACT = frozenset({
    '.github/scripts/live_stock_ci_ownership.py',
    '.github/workflows/dispatch-d10-session-acceptance.yml',
    '.github/workflows/dispatch-p0-route-stock-safety.yml',
    '.github/workflows/live-stock-inflight-authority-acceptance.yml',
    'dashboard/src/components/dispatch/ShopBulkImportModal.tsx',
    'dashboard/src/features/dispatch/dispatchDrafts.ts',
    'dashboard/src/features/dispatch/sessionScope.ts',
    'dashboard/src/lib/authStorage.ts',
    'dashboard/src/pages/DispatchBoard.tsx',
    'dashboard/src/test/auth-session-consumer-isolation.test.tsx',
    'dashboard/src/test/dispatch-d10-drafts.test.ts',
    'dashboard/src/test/dispatch-d10-import.test.tsx',
    'dashboard/src/test/dispatch-d10-session-scope.test.ts',
    'dashboard/src/test/dispatch-load-context.test.tsx',
})
DISPATCH_D10_872_NEW = frozenset({
    '.github/workflows/dispatch-d10-session-acceptance.yml',
    'dashboard/src/components/dispatch/ShopBulkImportModal.tsx',
    'dashboard/src/features/dispatch/dispatchDrafts.ts',
    'dashboard/src/features/dispatch/sessionScope.ts',
    'dashboard/src/test/dispatch-d10-drafts.test.ts',
    'dashboard/src/test/dispatch-d10-import.test.tsx',
    'dashboard/src/test/dispatch-d10-session-scope.test.ts',
})
assert len(DISPATCH_D10_872_EXACT) == 14 and len(DISPATCH_D10_872_NEW) == 7

# #867: only complete D09 capability/navigation UI may cross shared DispatchBoard.
DISPATCH_D09_867_EXACT = frozenset({
    "dashboard/src/components/dispatch/ShortageModal.tsx",
    "dashboard/src/features/dispatch/DispatchAccessNotice.tsx",
    "dashboard/src/features/dispatch/dispatchAccess.ts",
    "dashboard/src/features/dispatch/loadDispatchRead.ts",
    "dashboard/src/features/dispatch/useDispatchAccessGate.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
    "dashboard/src/test/dispatch-access-notice-v1.test.tsx",
    "dashboard/src/test/dispatch-capability-denied-v1.test.ts",
    "dashboard/src/test/dispatch-load-context.test.tsx",
    "dashboard/src/test/dispatch-scale-containment.test.ts",
    "dashboard/src/test/dispatch-shortage-group-recovery-v1.test.tsx",
})
DISPATCH_D09_867_NEW = frozenset({
    "dashboard/src/features/dispatch/DispatchAccessNotice.tsx",
    "dashboard/src/features/dispatch/dispatchAccess.ts",
    "dashboard/src/features/dispatch/loadDispatchRead.ts",
    "dashboard/src/features/dispatch/useDispatchAccessGate.ts",
    "dashboard/src/test/dispatch-access-notice-v1.test.tsx",
    "dashboard/src/test/dispatch-capability-denied-v1.test.ts",
})
assert len(DISPATCH_D09_867_EXACT) == 12 and len(DISPATCH_D09_867_NEW) == 6

# #847 is a maintenance-only PR. It changes exactly the three policy
# surfaces and has no right to modify Dispatch, Stock, Driver or auth runtime.
# Do not add these paths to broad UX/R3/operational allowed unions.
CI_POLICY_847_EXACT = frozenset({
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
})

# #856: only the six actual #855 ShopForm paths may cross the shared
# DispatchBoard consumer. Neither new form files nor mixed workers are allowed.
SHOP_FORM_850_EXACT = frozenset({
    "dashboard/src/components/dispatch/ShopFormModal.tsx",
    "dashboard/src/features/dispatch/shopForm/contract.ts",
    "dashboard/src/features/dispatch/shopForm/messages.ts",
    "dashboard/src/features/dispatch/shopForm/useShopFormCommit.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-shop-metadata-finance-v1.test.tsx",
})
SHOP_FORM_850_NEW = SHOP_FORM_850_EXACT - {"dashboard/src/pages/DispatchBoard.tsx"}
assert len(SHOP_FORM_850_EXACT) == 6 and len(SHOP_FORM_850_NEW) == 5

# #859: minimum isolated grouped-shortage recovery UI scope, exact file set.
# This is NOT a wildcard for Dispatch, authentication, inventory or Backend.
SHORTAGE_GROUP_859_EXACT = frozenset({
    "dashboard/src/components/dispatch/ShortageModal.tsx",
    "dashboard/src/features/dispatch/shortageGroup/contract.ts",
    "dashboard/src/features/dispatch/shortageGroup/useShortageGroupCommit.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-shortage-group-recovery-v1.test.tsx",
})
SHORTAGE_GROUP_859_NEW = SHORTAGE_GROUP_859_EXACT - {"dashboard/src/pages/DispatchBoard.tsx"}
assert len(SHORTAGE_GROUP_859_EXACT) == 5 and len(SHORTAGE_GROUP_859_NEW) == 4

# Independent four-file CI maintenance: #847 three-file mode remains accepted.
CI_POLICY_856_EXACT = frozenset({
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    ".github/workflows/live-stock-g04-outage-recovery.yml",
})
assert CI_POLICY_847_EXACT < CI_POLICY_856_EXACT and len(CI_POLICY_856_EXACT) == 4

# #870 full D07 original route-launch recovery. Never promote partial
# Backend/DispatchBoard/CI source edits into Live Stock or D10 authority.
DISPATCH_D07_COMPLETE_EXACT = frozenset({
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-shop-create-f06-acceptance.yml",
    ".github/workflows/dispatch-shop-finance-p0-acceptance.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/src/features/dispatch/routeLaunch/contract.ts",
    "dashboard/src/features/dispatch/routeLaunch/useRouteLaunchRecovery.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-route-launch-d07.test.tsx",
    "wa_backend/api/dispatch.py",
    "wa_backend/domains/dispatch_route_launch_receipt.py",
    "wa_backend/schemas.py",
    "wa_backend/tests/test_dispatch_route_launch_d07_postgres.py",
})
DISPATCH_D07_NEW = frozenset({
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    "dashboard/src/features/dispatch/routeLaunch/contract.ts",
    "dashboard/src/features/dispatch/routeLaunch/useRouteLaunchRecovery.ts",
    "dashboard/src/test/dispatch-route-launch-d07.test.tsx",
    "wa_backend/domains/dispatch_route_launch_receipt.py",
    "wa_backend/tests/test_dispatch_route_launch_d07_postgres.py",
})
assert len(DISPATCH_D07_COMPLETE_EXACT) == 14 and len(DISPATCH_D07_NEW) == 6

def classify(mode: str, changed: set[str], semantic: dict[str, bool]) -> tuple[str, list[str]]:
    # M05 contains a complete independently audited literal path set.
    # Admit it BEFORE D07's distinct historic anchors; partial M05 and
    # foreign files are rejected by the dedicated negative ownership gate.
    if __import__("runpy").run_path(".github/scripts/m05_ci_scope.py")["m05_mode"](changed):
        return ("not-applicable", []) if mode == "r3" else ("m05-945-exact", [])
    # D06 is an exact audited crossover. Do not weaken older D09/D10/F06
    # ownership rules or permit partial D06 or unrelated Flutter/source paths.
    d06 = __import__("runpy").run_path(".github/scripts/dispatch_d06_ci_scope.py")["d06_mode"]
    if d06(changed):
        return ("dispatch-d06-889-exact", []) if mode in {"ux", "operational"} else ("not-applicable", [])
    if changed == DISPATCH_D11_881_EXACT:
        return ("dispatch-d11-881-exact", []) if mode in {"ux", "operational"} else ("not-applicable", [])
    # Exact D13 only; no partial/mixed crossover can steal the old owners.
    if changed == DISPATCH_D13_877_EXACT:
        return ("dispatch-d13-877-exact", []) if mode in {"ux", "operational"} else ("not-applicable", [])
    if changed == CI_POLICY_847_EXACT:
        return "ci-policy-847-exact", []
    if changed == CI_POLICY_856_EXACT:
        return "ci-policy-856-exact", []
    # A fourth G04 governance file cannot be piggybacked onto the older
    # three-file policy approval. The old #847 mode remains unchanged.
    if CI_POLICY_847_EXACT <= changed and (
        ".github/workflows/live-stock-g04-outage-recovery.yml" in changed
    ):
        return "fail", [
            f"CI_POLICY_856_EXACT=FAIL missing={sorted(CI_POLICY_856_EXACT - changed)} "
            f"extra={sorted(changed - CI_POLICY_856_EXACT)}"
        ]
    if changed & DISPATCH_D07_NEW:
        if changed != DISPATCH_D07_COMPLETE_EXACT:
            return "fail", [
                f"DISPATCH_D07_COMPLETE_EXACT=FAIL missing={sorted(DISPATCH_D07_COMPLETE_EXACT - changed)} "
                f"extra={sorted(changed - DISPATCH_D07_COMPLETE_EXACT)}"
            ]
        if mode in {"ux", "operational"}:
            return "dispatch-d07-complete-exact", []
        return "not-applicable", []

    if changed & DISPATCH_D10_872_NEW:
        if changed != DISPATCH_D10_872_EXACT:
            return "fail", [
                f"DISPATCH_D10_872_EXACT=FAIL missing={sorted(DISPATCH_D10_872_EXACT - changed)} "
                f"extra={sorted(changed - DISPATCH_D10_872_EXACT)}"
            ]
        if mode in {"ux", "operational"}:
            return "dispatch-d10-872-exact", []
        return "not-applicable", []

    if changed & DISPATCH_D09_867_NEW:
        if changed != DISPATCH_D09_867_EXACT:
            return "fail", [
                f"DISPATCH_D09_867_EXACT=FAIL missing={sorted(DISPATCH_D09_867_EXACT - changed)} "
                f"extra={sorted(changed - DISPATCH_D09_867_EXACT)}"
            ]
        if mode in {"ux", "operational"}:
            return "dispatch-d09-867-exact", []
        return "not-applicable", []

    # Exact #846 ShopOrder change is outside Live Stock owner scope.
    # A partial set, even with the shared DispatchBoard, or any hitchhiker
    # is REJECTED whenever one of its eight newly extracted files appears.
    if changed & SHOP_ORDER_843_NEW:
        if changed != SHOP_ORDER_843_EXACT:
            return "fail", [
                f"SHOP_ORDER_843_EXACT=FAIL missing={sorted(SHOP_ORDER_843_EXACT - changed)} "
                f"extra={sorted(changed - SHOP_ORDER_843_EXACT)}"
            ]
        if mode in {"ux", "operational"}:
            return "shop-order-843-exact", []
        return "not-applicable", []

    # #859 independent UI-only group-shortage operation. Reject every
    # partial, mixed or hitchhiking edit touching one of its four NEW files.
    if changed & SHORTAGE_GROUP_859_NEW:
        if changed != SHORTAGE_GROUP_859_EXACT:
            return "fail", [
                f"SHORTAGE_GROUP_859_EXACT=FAIL missing={sorted(SHORTAGE_GROUP_859_EXACT - changed)} "
                f"extra={sorted(changed - SHORTAGE_GROUP_859_EXACT)}"
            ]
        if mode in {"ux", "operational"}:
            return "shortage-group-859-exact", []
        return "not-applicable", []

    # New ShopForm sources are not covered by existing generic Dispatch/Auth
    # scopes. An exact six-file edit alone can cross the shared UI trigger.
    if changed & SHOP_FORM_850_NEW:
        if changed != SHOP_FORM_850_EXACT:
            return "fail", [
                f"SHOP_FORM_850_EXACT=FAIL missing={sorted(SHOP_FORM_850_EXACT - changed)} "
                f"extra={sorted(changed - SHOP_FORM_850_EXACT)}"
            ]
        if mode in {"ux", "operational"}:
            return "shop-form-850-exact", []
        return "not-applicable", []

    # Exact membership only; all previous classifying/negative protections
    # remain unchanged for every other PR, including cross-domain combinations.
    if changed == STOCKTAKE_FINAL_CI_782_EXACT:
        return "policy-maintenance", []
    if changed == STOCKTAKE_793_BRIDGE_EXACT:
        return "policy-maintenance", []

    if mode in {"ux", "operational"}:
        if changed == LEDGER_825_VISUAL_EXACT:
            return "ledger-825-visual-exact", []
        if changed == LEDGER_818_STAGE_A_EXACT:
            return "ledger-818-stage-a-exact", []
        if changed == LEDGER_818_STAGE_B_EXACT:
            return "ledger-818-stage-b-exact", []
        if changed == LEDGER_818_STACKED_EXACT:
            return "ledger-818-stacked-exact", []

    if mode in {"ux", "operational"} and changed == LEDGER_TOOLBAR_EXACT:
        return "ledger-toolbar-exact", []

    if mode in {"ux", "operational"} and changed == LEDGER_811_EXACT:
        return "ledger-811-exact", []

    if mode in {"ux", "operational"} and changed == LEDGER_804_EXACT:
        return "ledger-804-exact", []

    if mode in {"ux", "operational"} and changed == STOCKTAKE_789_SHELL_EXACT:
        return "stocktake-789-shell-exact", []
    if mode in {"ux", "operational"} and changed == STOCKTAKE_784_EXACT:
        return "stocktake-784-exact", []
    if mode in {"ux", "operational"} and BATCHES_COMPACT_V1_REQUIRED <= changed:
        extra = sorted(changed - BATCHES_COMPACT_V1_ALLOWED)
        if extra:
            return "fail", [f"BATCHES_COMPACT_V1_SCOPE=FAIL extra={extra}"]
        return "batches-compact-v1", []

    if mode in {"ux", "operational"} and BATCHES_LAYOUT_769_REQUIRED <= changed:
        extra = sorted(changed - BATCHES_LAYOUT_769_ALLOWED)
        if extra:
            return "fail", [f"BATCHES_LAYOUT_769_SCOPE=FAIL extra={extra}"]
        return "batches-layout-769", []

    if mode in {"ux", "operational"} and LEDGER_762_REQUIRED <= changed:
        extra = sorted(changed - LEDGER_762_ALLOWED)
        if extra:
            return "fail", [f"LEDGER_762_SCOPE=FAIL extra={extra}"]
        return "ledger-762", []

    if mode in {"ux", "operational"} and BATCH_SELECTOR_OWNER_REQUIRED <= changed:
        extra = sorted(changed - BATCH_SELECTOR_OWNER_ALLOWED)
        if extra:
            return "fail", [f"BATCH_SELECTOR_OWNER_SCOPE=FAIL extra={extra}"]
        return "batch-selector-owner", []

    if mode in {"ux", "operational"} and OWNER_VISUAL_REQUIRED <= changed:
        extra = sorted(changed - OWNER_VISUAL_ALLOWED)
        if extra:
            return "fail", [f"OWNER_VISUAL_V1_SCOPE=FAIL extra={extra}"]
        return "owner-visual-v1", []

    if mode in {"ux", "operational"} and IT03_REMAINING_REQUIRED <= changed:
        extra = sorted(changed - IT03_REMAINING_ALLOWED)
        if extra:
            return "fail", [f"IT03_REMAINING_SCOPE=FAIL extra={extra}"]
        return "it03-remaining-v1", []

    if mode in {"ux", "operational"} and IT03_IT04_REENTRY_REQUIRED <= changed:
        extra = sorted(changed - IT03_IT04_REENTRY_ALLOWED)
        if extra:
            return "fail", [f"IT03_IT04_REENTRY_SCOPE=FAIL extra={extra}"]
        return "it03-it04-batch-reentry", []

    if SEAMLESS_REENTRY_EXPLANATION_REQUIRED <= changed:
        extra = sorted(changed - SEAMLESS_REENTRY_EXPLANATION_ALLOWED)
        if extra:
            return "fail", [f"LIVE_STOCK_REENTRY_EXPLANATION_SCOPE=FAIL extra={extra}"]
        return "seamless-reentry-explanation", []

    if WAREHOUSE_VIEW_REQUIRED <= changed:
        extra = sorted(changed - WAREHOUSE_VIEW_ALLOWED)
        if extra:
            return "fail", [f"WAREHOUSE_MINIMUM_VIEW_SCOPE=FAIL extra={extra}"]
        return "warehouse-minimum-view", []

    if changed & SESSION_ISOLATION_ROOTS:
        extra = sorted(changed - SESSION_ISOLATION_ALLOWED)
        if extra:
            return "fail", [f"AUTH_SESSION_SCOPE=FAIL extra={extra}"]
        return "session-isolation-repair", []
    if mode == "r3" and changed & PERFORMANCE_ACCEPTANCE_ROOTS:
        extra = sorted(changed - PERFORMANCE_ACCEPTANCE_ALLOWED)
        if extra:
            return "fail", [f"LIVE_STOCK_PERFORMANCE_SCOPE=FAIL extra={extra}"]
        return "performance-acceptance", []
    # A shared CI policy helper can accompany an inventory-only UX correction
    # without claiming the R3 physical-stock backend as an owner. Never use
    # this exception for actual R3-owned paths, session roots, or foreign files.
    if (
        mode == "r3"
        and HELPER in changed
        and "dashboard/src/pages/inventory/StockMinimumManager.tsx" in changed
        and "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx" in changed
    ):
        # Whitelist this exact inventory UI crossover only; any backend or
        # unrelated presentation file fails instead of being silently ignored.
        extras = sorted(changed - (UX_ALLOWED | POLICY_FILES | MINIMUM_UX_CROSSOVER))
        if extras:
            return "fail", [f"P0_R3_SCOPE=FAIL extra={extras}"]
        if not changed & (R3_ALLOWED - POLICY_FILES):
            return "not-applicable", []
    allowed, shared, hard_owned, forbidden, label = _spec(mode)
    if changed and changed <= POLICY_FILES:
        return "policy-maintenance", []
    relevant_shared = {path for path in shared if semantic.get(path, False)}
    owned = (changed & hard_owned) | relevant_shared
    if not owned:
        return "not-applicable", []
    effective_allowed = set(allowed)
    if (
        mode in {"ux", "operational"}
        and "dashboard/src/pages/inventory/StockMinimumManager.tsx" in changed
        and "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx" in changed
        and SHARED_RESOURCES in relevant_shared
    ):
        effective_allowed |= MINIMUM_UX_CROSSOVER
    if OP_WORKFLOW in changed and mode in {"ux", "operational"}:
        effective_allowed |= WORKER1_COMBINED_CLOSURE
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
    # The exact #847 three-file policy PR must pass unrelated Live Stock
    # entrypoints without granting any general Dispatch CI workflow bypass.
    policy_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for mode in ("ux", "r3", "operational"):
        assert classify(mode, set(CI_POLICY_847_EXACT), policy_sem) == (
            "ci-policy-847-exact", []
        )
        for missing in CI_POLICY_847_EXACT:
            assert classify(mode, set(CI_POLICY_847_EXACT) - {missing}, policy_sem)[0] != (
                "ci-policy-847-exact"
            )
        for foreign in (
            "wa_backend/api/dispatch.py",
            "wa_backend/api/driver.py",
            "wa_backend/models.py",
            "wa_backend/domains/inventory/services.py",
            "dashboard/src/pages/DispatchBoard.tsx",
            "dashboard/src/lib/authStorage.ts",
            "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
            "wanasah_frontend/lib/main.dart",
        ):
            assert classify(mode, set(CI_POLICY_847_EXACT) | {foreign}, policy_sem)[0] != (
                "ci-policy-847-exact"
            )
    print("CI_POLICY_847_LIVE_STOCK_SELFTEST=PASS exact=3 partial=3 foreign=8")

    # #856: keep the old three-file policy set and all established owner
    # modes; admit ONLY the four-file governance diff as its own new mode.
    # New G04 workflow path may never be used as a wildcard for business code.
    assert len(CI_POLICY_856_EXACT) == 4
    assert len(SHOP_FORM_850_EXACT) == 6
    for mode in ("ux", "r3", "operational"):
        assert classify(mode, set(CI_POLICY_856_EXACT), policy_sem) == (
            "ci-policy-856-exact", []
        )
        for missing in CI_POLICY_856_EXACT:
            partial = set(CI_POLICY_856_EXACT) - {missing}
            assert classify(mode, partial, policy_sem)[0] != "ci-policy-856-exact"
        for foreign in (
            "dashboard/src/pages/DispatchBoard.tsx",
            "dashboard/src/components/dispatch/ShopFormModal.tsx",
            "dashboard/src/features/dispatch/shopOrder/messages.ts",
            "wa_backend/main.py",
            "wa_backend/api/driver.py",
            "wa_backend/api/warehouse/live_stock.py",
            "dashboard/src/hooks/useAuthFetch.ts",
            "wanasah_frontend/lib/main.dart",
        ):
            _expect_fail(mode, set(CI_POLICY_856_EXACT) | {foreign}, policy_sem)
    assert classify("ux", set(CI_POLICY_847_EXACT), policy_sem) == (
        "ci-policy-847-exact", []
    )
    print("CI_POLICY_856_LIVE_STOCK_SELFTEST=PASS exact=4 partial=4 foreign=8 prior847=PASS")

    for mode in ("ux", "operational"):
        assert classify(mode, set(DISPATCH_D11_881_EXACT), policy_sem) == (
            "dispatch-d11-881-exact", [])
    assert classify("r3", set(DISPATCH_D11_881_EXACT), policy_sem) == (
        "not-applicable", [])
    for missing in DISPATCH_D11_881_EXACT:
        for mode in ("ux", "operational"):
            assert classify(mode, set(DISPATCH_D11_881_EXACT) - {missing}, policy_sem)[0] != "dispatch-d11-881-exact"
    for foreign in ("dashboard/src/lib/authStorage.ts", "wa_backend/models.py",
                    "wa_backend/api/dispatch.py", "wanasah_frontend/lib/main.dart"):
        for mode in ("ux", "operational"):
            _expect_fail(mode, set(DISPATCH_D11_881_EXACT) | {foreign}, policy_sem)
    print("DISPATCH_D11_881_LIVE_STOCK_SELFTEST=PASS exact=16 missing=16 foreign=4")

    # D13 admits exactly its 16 files; old D09/D10/ShopOrder/Form/Shortage
    # owner checks continue to reject every partial or added unrelated path.
    for mode in ("ux", "operational"):
        assert classify(mode, set(DISPATCH_D13_877_EXACT), policy_sem) == (
            "dispatch-d13-877-exact", []
        )
    assert classify("r3", set(DISPATCH_D13_877_EXACT), policy_sem) == (
        "not-applicable", []
    )
    for missing in DISPATCH_D13_877_EXACT:
        partial = set(DISPATCH_D13_877_EXACT) - {missing}
        for mode in ("ux", "operational"):
            assert classify(mode, partial, policy_sem)[0] != "dispatch-d13-877-exact"
    for foreign in ("dashboard/src/pages/DispatchBoard.tsx", "dashboard/src/lib/authStorage.ts",
                    "wa_backend/api/dispatch.py", "dashboard/src/pages/inventory/Tab1LiveStock.tsx"):
        for mode in ("ux", "operational"):
            _expect_fail(mode, set(DISPATCH_D13_877_EXACT) | {foreign}, policy_sem)
    print("DISPATCH_D13_877_LIVE_STOCK_SELFTEST=PASS exact=16 missing=16 foreign=4")

    # Every candidate touching one of the *five new* #855 paths must
    # contain the whole immutable six-file set; no cross-owner combination.
    for mode in ("ux", "operational"):
        assert classify(mode, set(SHOP_FORM_850_EXACT), policy_sem) == (
            "shop-form-850-exact", []
        )
    assert classify("r3", set(SHOP_FORM_850_EXACT), policy_sem) == (
        "not-applicable", []
    )
    for missing in SHOP_FORM_850_EXACT:
        partial = set(SHOP_FORM_850_EXACT) - {missing}
        if partial & SHOP_FORM_850_NEW:
            for mode in ("ux", "r3", "operational"):
                _expect_fail(mode, partial, policy_sem)
        else:
            for mode in ("ux", "r3", "operational"):
                assert classify(mode, partial, policy_sem)[0] != "shop-form-850-exact"
    for foreign in (
        HELPER, "wa_backend/main.py", "wa_backend/api/dispatch.py",
        "wa_backend/api/driver.py", "wa_backend/models.py",
        "dashboard/src/features/dispatch/shopForm/unreviewed.ts",
        "dashboard/src/features/dispatch/shopOrder/scope.ts",
        "dashboard/src/hooks/useAuthFetch.ts",
        "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
        ".github/workflows/dispatch-p0-route-stock-safety.yml",
        ".github/workflows/live-stock-g04-outage-recovery.yml",
        "wanasah_frontend/lib/main.dart",
    ):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, set(SHOP_FORM_850_EXACT) | {foreign}, policy_sem)
    for mixed in (
        set(SHOP_FORM_850_EXACT) | SHOP_ORDER_843_EXACT,
        set(SHOP_FORM_850_EXACT) | CI_POLICY_847_EXACT,
        set(SHOP_FORM_850_EXACT) | CI_POLICY_856_EXACT,
    ):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, mixed, policy_sem)
    assert classify("ux", {"dashboard/src/pages/DispatchBoard.tsx"}, policy_sem)[0] != (
        "shop-form-850-exact"
    )
    print("SHOP_FORM_850_LIVE_STOCK_SELFTEST=PASS exact=6 partial=6 foreign=12 mixed=3")

    # D07 #870: only complete fourteen-file route-launch diff admitted.
    for mode in ("ux", "operational"):
        assert classify(mode, set(DISPATCH_D07_COMPLETE_EXACT), policy_sem) == (
            "dispatch-d07-complete-exact", []
        )
    assert classify("r3", set(DISPATCH_D07_COMPLETE_EXACT), policy_sem) == (
        "not-applicable", []
    )
    for missing in DISPATCH_D07_COMPLETE_EXACT:
        partial = set(DISPATCH_D07_COMPLETE_EXACT) - {missing}
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, partial, policy_sem)
    for foreign in ("wa_backend/models.py", "wa_backend/main.py",
                    "dashboard/src/features/dispatch/sessionScope.ts",
                    "dashboard/src/components/dispatch/ShortageModal.tsx"):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, set(DISPATCH_D07_COMPLETE_EXACT) | {foreign}, policy_sem)
    print("DISPATCH_D07_LIVE_STOCK_SELFTEST=PASS exact=14 partial=14 foreign=4")

    # Strict D10 acceptance: both supported owner modes, every missing file,
    # unrelated/Backend file denied, original D09 policy unchanged.
    for mode in ("ux", "operational"):
        assert classify(mode, set(DISPATCH_D10_872_EXACT), policy_sem) == ("dispatch-d10-872-exact", [])
    assert classify("r3", set(DISPATCH_D10_872_EXACT), policy_sem) == ("not-applicable", [])
    for missing in DISPATCH_D10_872_EXACT:
        partial = set(DISPATCH_D10_872_EXACT) - {missing}
        if partial & DISPATCH_D10_872_NEW:
            for mode in ("ux", "r3", "operational"):
                _expect_fail(mode, partial, policy_sem)
        else:
            assert classify("ux", partial, policy_sem)[0] != "dispatch-d10-872-exact"
    for foreign in ("wa_backend/api/driver.py", "wa_backend/models.py",
                    "dashboard/src/pages/inventory/Tab1LiveStock.tsx"):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, set(DISPATCH_D10_872_EXACT) | {foreign}, policy_sem)
    print("DISPATCH_D10_872_LIVE_STOCK_SELFTEST=PASS exact=14 missing=14 foreign=4")

    # #867 D09 strict 12-file admission: no partial/extra/foreign changes.
    for mode in ("ux", "operational"):
        assert classify(mode, set(DISPATCH_D09_867_EXACT), policy_sem) == ("dispatch-d09-867-exact", [])
    assert classify("r3", set(DISPATCH_D09_867_EXACT), policy_sem) == ("not-applicable", [])
    for missing in DISPATCH_D09_867_EXACT:
        subset = set(DISPATCH_D09_867_EXACT) - {missing}
        if subset & DISPATCH_D09_867_NEW:
            for mode in ("ux", "r3", "operational"):
                _expect_fail(mode, subset, policy_sem)
        else:
            assert classify("ux", subset, policy_sem)[0] != "dispatch-d09-867-exact"
    for foreign in ("wa_backend/api/driver.py", "wa_backend/models.py",
                    "dashboard/src/lib/authStorage.ts", "dashboard/src/pages/inventory/Tab1LiveStock.tsx"):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, set(DISPATCH_D09_867_EXACT) | {foreign}, policy_sem)
    print("DISPATCH_D09_867_LIVE_STOCK_SELFTEST=PASS exact=12 missing=12 foreign=5")

    # #859 exact five-file acceptance and negative regression probes.
    # Never admit a subset, a backend path, an auth/session path, a finance
    # path, a ShopForm/ShopOrder change or any CI policy path alongside it.
    for mode in ("ux", "operational"):
        assert classify(mode, set(SHORTAGE_GROUP_859_EXACT), policy_sem) == (
            "shortage-group-859-exact", []
        )
    assert classify("r3", set(SHORTAGE_GROUP_859_EXACT), policy_sem) == (
        "not-applicable", []
    )
    # #865: cover all 31 strict subsets, not just five missing-one probes.
    shortage_items = sorted(SHORTAGE_GROUP_859_EXACT)
    shortage_partials_rejected = 0
    for bits in range(1 << len(shortage_items)):
        subset = {
            path for i, path in enumerate(shortage_items) if bits & (1 << i)
        }
        if subset == set(SHORTAGE_GROUP_859_EXACT):
            continue
        if subset & SHORTAGE_GROUP_859_NEW:
            for mode in ("ux", "r3", "operational"):
                _expect_fail(mode, subset, policy_sem)
            shortage_partials_rejected += 1
        else:
            assert classify("ux", subset, policy_sem)[0] != "shortage-group-859-exact"
    assert shortage_partials_rejected == 29
    for foreign in (
        HELPER, "wa_backend/main.py", "wa_backend/api/dispatch_shortages_group.py",
        "wa_backend/api/dispatch.py", "wa_backend/domains/dispatch_shop_create.py",
        "wa_backend/tests/test_dispatch_shop_create_f06_postgres.py",
        ".github/workflows/dispatch-shop-create-f06-acceptance.yml",
        "dashboard/src/lib/authStorage.ts",
        "dashboard/src/features/dispatch/shopOrder/scope.ts",
        "dashboard/src/features/dispatch/shopForm/contract.ts",
        "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
        ".github/workflows/dispatch-p0-route-stock-safety.yml",
        ".github/workflows/live-stock-inflight-authority-acceptance.yml",
        "wanasah_frontend/lib/main.dart",
    ):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, set(SHORTAGE_GROUP_859_EXACT) | {foreign}, policy_sem)
    # The F06 exact shop-create policy is independent from the D05 UI.
    f06_shop_create_exact = {
        ".github/workflows/dispatch-shop-create-f06-acceptance.yml",
        "wa_backend/api/dispatch.py",
        "wa_backend/domains/dispatch_shop_create.py",
        "wa_backend/schemas.py",
        "wa_backend/tests/test_dispatch_shop_create_f06_postgres.py",
    }
    assert len(f06_shop_create_exact) == 5
    for mixed in (
        set(SHORTAGE_GROUP_859_EXACT) | SHOP_FORM_850_EXACT,
        set(SHORTAGE_GROUP_859_EXACT) | SHOP_ORDER_843_EXACT,
        set(SHORTAGE_GROUP_859_EXACT) | CI_POLICY_847_EXACT,
        set(SHORTAGE_GROUP_859_EXACT) | CI_POLICY_856_EXACT,
        set(SHORTAGE_GROUP_859_EXACT) | f06_shop_create_exact,
    ):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, mixed, policy_sem)
    print(
        "SHORTAGE_GROUP_859_LIVE_STOCK_SELFTEST=PASS "
        "exact=5 partial_with_new=29 foreign=14 mixed=5 f06_cross=DENIED"
    )

    # #847: real #846 payload passes only as its literal nine-file set.
    # Every partial-with-new-file and every foreign/mixed-domain path fails.
    shop_order_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for mode in ("ux", "operational"):
        assert classify(mode, set(SHOP_ORDER_843_EXACT), shop_order_sem) == (
            "shop-order-843-exact", []
        )
    assert classify("r3", set(SHOP_ORDER_843_EXACT), shop_order_sem) == (
        "not-applicable", []
    )
    for missing in SHOP_ORDER_843_EXACT:
        partial = set(SHOP_ORDER_843_EXACT) - {missing}
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, partial, shop_order_sem)
    for foreign in (
        HELPER,
        ".github/workflows/dispatch-p0-route-stock-safety.yml",
        "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
        "dashboard/src/hooks/useAuthFetch.ts",
        "dashboard/src/lib/authStorage.ts",
        SHARED_RESOURCES,
        "wa_backend/api/dispatch.py",
        "wa_backend/api/driver.py",
        "wa_backend/models.py",
        "wa_backend/domains/inventory/services.py",
        "dashboard/src/features/dispatch/shopOrder/extra.ts",
        "wanasah_frontend/lib/main.dart",
    ):
        for mode in ("ux", "r3", "operational"):
            _expect_fail(mode, set(SHOP_ORDER_843_EXACT) | {foreign}, shop_order_sem)
    assert classify("ux", {"dashboard/src/pages/DispatchBoard.tsx"}, shop_order_sem)[0] != "shop-order-843-exact"
    print("SHOP_ORDER_843_LIVE_STOCK_SELFTEST=PASS exact=9 partial=9 foreign=12")

    ledger_818_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    assert len(LEDGER_818_STAGE_A_EXACT) == 6
    assert len(LEDGER_818_STAGE_B_EXACT) == 10
    assert len(LEDGER_818_STACKED_EXACT) == 14
    for ledger_mode in ("ux", "operational"):
        for item_set, label in (
            (LEDGER_818_STAGE_A_EXACT, "ledger-818-stage-a-exact"),
            (LEDGER_818_STAGE_B_EXACT, "ledger-818-stage-b-exact"),
            (LEDGER_818_STACKED_EXACT, "ledger-818-stacked-exact"),
        ):
            assert classify(ledger_mode, set(item_set), ledger_818_sem) == (label, [])
            for missing in item_set:
                assert classify(ledger_mode, set(item_set) - {missing}, ledger_818_sem)[0] != label
            for foreign in (
                HELPER,
                "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
                "wa_backend/domains/ledger/read.py",
                "wa_backend/api/warehouse/stocktake.py",
                "flutter_app/lib/main.dart",
            ):
                combined = set(item_set) | {foreign}
                assert classify(ledger_mode, combined, ledger_818_sem)[0] != label
                if foreign != HELPER:
                    _expect_fail(ledger_mode, combined, ledger_818_sem)
        _expect_fail(ledger_mode, set(LEDGER_818_STAGE_A_EXACT) | LEDGER_811_EXACT, ledger_818_sem)
    assert classify("r3", set(LEDGER_818_STAGE_A_EXACT), ledger_818_sem) == ("not-applicable", [])
    assert classify("r3", set(LEDGER_818_STAGE_B_EXACT), ledger_818_sem) == ("not-applicable", [])

    # #825 is an exact seven-file Ledger-only UI change. All subsets and
    # mixed domains remain rejected; policy changes must be their own PR.
    assert len(LEDGER_825_VISUAL_EXACT) == 7
    for ledger_mode in ("ux", "operational"):
        assert classify(ledger_mode, set(LEDGER_825_VISUAL_EXACT), ledger_818_sem) == (
            "ledger-825-visual-exact", []
        )
        for missing in LEDGER_825_VISUAL_EXACT:
            partial = set(LEDGER_825_VISUAL_EXACT) - {missing}
            assert classify(ledger_mode, partial, ledger_818_sem)[0] != "ledger-825-visual-exact"
            if "dashboard/src/pages/inventory/Tab4Ledger.tsx" in partial:
                _expect_fail(ledger_mode, partial, ledger_818_sem)
        for foreign in (HELPER, "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
                        "wa_backend/domains/ledger/read.py", "flutter_app/lib/main.dart"):
            candidate = set(LEDGER_825_VISUAL_EXACT) | {foreign}
            assert classify(ledger_mode, candidate, ledger_818_sem)[0] != "ledger-825-visual-exact"
            if foreign != HELPER:
                _expect_fail(ledger_mode, candidate, ledger_818_sem)
        _expect_fail(ledger_mode, set(LEDGER_825_VISUAL_EXACT) |
                     {"dashboard/src/pages/inventory/ledger/LedgerFilters.tsx"}, ledger_818_sem)
    assert classify("r3", set(LEDGER_825_VISUAL_EXACT), ledger_818_sem) == (
        "not-applicable", []
    )

    ledger_toolbar_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    assert len(LEDGER_TOOLBAR_EXACT) == 7
    for mode in ("ux", "operational"):
        assert classify(mode, set(LEDGER_TOOLBAR_EXACT), ledger_toolbar_sem) == (
            "ledger-toolbar-exact", []
        )
        for missing in LEDGER_TOOLBAR_EXACT:
            partial = set(LEDGER_TOOLBAR_EXACT) - {missing}
            assert classify(mode, partial, ledger_toolbar_sem)[0] != "ledger-toolbar-exact"
            _expect_fail(mode, partial, ledger_toolbar_sem)
        for foreign in (
            "wa_backend/domains/ledger/read.py",
            "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
            "dashboard/src/pages/inventory/ledger/useLedgerQuery.ts",
            "flutter_app/lib/main.dart",
        ):
            _expect_fail(mode, set(LEDGER_TOOLBAR_EXACT) | {foreign}, ledger_toolbar_sem)
        _expect_fail(mode, set(LEDGER_TOOLBAR_EXACT) | LEDGER_811_EXACT, ledger_toolbar_sem)
    assert classify("r3", set(LEDGER_TOOLBAR_EXACT), ledger_toolbar_sem) == (
        "not-applicable", []
    )

    ledger_811_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    assert len(LEDGER_811_EXACT) == 13
    assert "dashboard/src/pages/inventory/Tab4Ledger.tsx" in LEDGER_811_EXACT
    assert "dashboard/src/test/inventory-cp10-ledger-keyboard.test.tsx" in LEDGER_811_EXACT
    for ledger_mode in ("ux", "operational"):
        assert classify(ledger_mode, set(LEDGER_811_EXACT), ledger_811_sem) == (
            "ledger-811-exact", []
        )
        for missing in LEDGER_811_EXACT:
            partial = set(LEDGER_811_EXACT) - {missing}
            assert classify(ledger_mode, partial, ledger_811_sem)[0] != "ledger-811-exact"
            if "dashboard/src/pages/inventory/Tab4Ledger.tsx" in partial:
                _expect_fail(ledger_mode, partial, ledger_811_sem)
        for foreign in (
            HELPER,
            "dashboard/src/pages/inventory/MainInventory.tsx",
            "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
            "dashboard/src/pages/inventory/ledger/useLedgerReference.ts",
            "wa_backend/domains/ledger/read.py",
            "wa_backend/api/warehouse/stocktake.py",
            "flutter_app/lib/main.dart",
            "LIVE_STOCK_V1_CLOSURE_PLAN.md",
        ):
            _expect_fail(ledger_mode, set(LEDGER_811_EXACT) | {foreign}, ledger_811_sem)
        _expect_fail(ledger_mode, set(LEDGER_811_EXACT) | LEDGER_804_EXACT, ledger_811_sem)
        _expect_fail(ledger_mode, set(LEDGER_811_EXACT) | STOCKTAKE_784_EXACT, ledger_811_sem)
    assert classify("r3", set(LEDGER_811_EXACT), ledger_811_sem) == ("not-applicable", [])

    # Verify exact #804 file set in both shared Live Stock browser guards.
    ledger_804_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    assert len(LEDGER_804_EXACT) == 9
    assert "dashboard/src/pages/inventory/Tab4Ledger.tsx" in LEDGER_804_EXACT
    for mode in ("ux", "operational"):
        assert classify(mode, set(LEDGER_804_EXACT), ledger_804_sem) == (
            "ledger-804-exact", []
        )
        for missing in LEDGER_804_EXACT:
            partial = set(LEDGER_804_EXACT) - {missing}
            assert classify(mode, partial, ledger_804_sem)[0] != "ledger-804-exact"
            if "dashboard/src/pages/inventory/Tab4Ledger.tsx" in partial:
                _expect_fail(mode, partial, ledger_804_sem)
        for foreign in (
            HELPER,
            "dashboard/src/pages/inventory/MainInventory.tsx",
            "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
            "dashboard/src/pages/inventory/ledger/LedgerTable.tsx",
            "wa_backend/api/warehouse/stocktake.py",
            "wa_backend/domains/ledger/read.py",
            "flutter_app/lib/main.dart",
            "LIVE_STOCK_V1_CLOSURE_PLAN.md",
        ):
            _expect_fail(mode, set(LEDGER_804_EXACT) | {foreign}, ledger_804_sem)
        _expect_fail(mode, set(LEDGER_804_EXACT) | STOCKTAKE_784_EXACT, ledger_804_sem)
    assert classify("r3", set(LEDGER_804_EXACT), ledger_804_sem) == (
        "not-applicable", []
    )

    # The two Live Stock gates must accept the complete approved #784 diff,
    # yet reject partial Stocktake scope, foreign files, and combinations with
    # other otherwise approved Live Stock or backend scopes.
    stocktake_sem = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    assert len(STOCKTAKE_784_EXACT) == 10
    assert "dashboard/src/pages/inventory/MainInventory.tsx" in STOCKTAKE_784_EXACT
    for mode in ("ux", "operational"):
        assert classify(mode, set(STOCKTAKE_784_EXACT), stocktake_sem) == (
            "stocktake-784-exact", []
        )
        for missing in STOCKTAKE_784_EXACT:
            partial = set(STOCKTAKE_784_EXACT) - {missing}
            assert classify(mode, partial, stocktake_sem)[0] != "stocktake-784-exact"
            # Without MainInventory, Live Stock's normal no-owner outcome is
            # deliberately preserved; with the shared owner present, reject.
            if "dashboard/src/pages/inventory/MainInventory.tsx" in partial:
                _expect_fail(mode, partial, stocktake_sem)
        for foreign in (
            HELPER,  # The policy-fix PR itself must not inflate #784's diff.
            "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
            "dashboard/src/pages/DispatchBoard.tsx",
            "dashboard/src/pages/inventory/Tab4Ledger.tsx",
            "wa_backend/services.py",
            "flutter_app/lib/main.dart",
            "LIVE_STOCK_V1_CLOSURE_PLAN.md",
        ):
            _expect_fail(mode, set(STOCKTAKE_784_EXACT) | {foreign}, stocktake_sem)
        _expect_fail(
            mode, set(STOCKTAKE_784_EXACT) | BATCHES_COMPACT_V1_REQUIRED,
            stocktake_sem,
        )
    assert classify("r3", set(STOCKTAKE_784_EXACT), stocktake_sem) == (
        "not-applicable", []
    )
    assert len(STOCKTAKE_792_DIALOG_EXACT) == 5
    assert len(STOCKTAKE_793_BRIDGE_EXACT) == 5
    for mode in ("ux", "operational"):
        assert STOCKTAKE_792_DIALOG_EXACT == STOCKTAKE_789_SHELL_EXACT
        assert classify(mode, set(STOCKTAKE_792_DIALOG_EXACT), stocktake_sem) == (
            "stocktake-789-shell-exact", []
        )
        assert classify(mode, set(STOCKTAKE_793_BRIDGE_EXACT), stocktake_sem) == (
            "policy-maintenance", []
        )
        for missing in STOCKTAKE_792_DIALOG_EXACT:
            partial = set(STOCKTAKE_792_DIALOG_EXACT) - {missing}
            assert classify(mode, partial, stocktake_sem)[0] != "stocktake-789-shell-exact"
            if "dashboard/src/pages/inventory/MainInventory.tsx" in partial:
                _expect_fail(mode, partial, stocktake_sem)
        for foreign in (HELPER, "dashboard/src/pages/inventory/Tab4Ledger.tsx",
                        "wa_backend/api/warehouse/stocktake.py"):
            _expect_fail(mode, set(STOCKTAKE_792_DIALOG_EXACT) | {foreign}, stocktake_sem)
        for missing in STOCKTAKE_793_BRIDGE_EXACT:
            partial = set(STOCKTAKE_793_BRIDGE_EXACT) - {missing}
            if partial == STOCKTAKE_FINAL_CI_782_EXACT:
                # An earlier, independent exact four-file CI maintenance
                # scope was already approved and must remain valid.
                assert classify(mode, partial, stocktake_sem) == ("policy-maintenance", [])
            else:
                assert classify(mode, partial, stocktake_sem)[0] != "policy-maintenance"
        _expect_fail(mode, set(STOCKTAKE_793_BRIDGE_EXACT) | {
            "dashboard/src/pages/inventory/MainInventory.tsx"
        }, stocktake_sem)
    assert classify("r3", set(STOCKTAKE_792_DIALOG_EXACT), stocktake_sem) == (
        "not-applicable", []
    )
    assert classify("r3", set(STOCKTAKE_793_BRIDGE_EXACT), stocktake_sem) == (
        "policy-maintenance", []
    )
    assert len(STOCKTAKE_789_SHELL_EXACT) == 5
    assert len(STOCKTAKE_FINAL_CI_782_EXACT) == 4
    for mode in ("ux", "operational"):
        assert classify(mode, set(STOCKTAKE_789_SHELL_EXACT), stocktake_sem) == (
            "stocktake-789-shell-exact", []
        )
        for missing in STOCKTAKE_789_SHELL_EXACT:
            partial = set(STOCKTAKE_789_SHELL_EXACT) - {missing}
            assert classify(mode, partial, stocktake_sem)[0] != "stocktake-789-shell-exact"
            if "dashboard/src/pages/inventory/MainInventory.tsx" in partial:
                _expect_fail(mode, partial, stocktake_sem)
        for foreign in (HELPER, "dashboard/src/pages/inventory/Tab4Ledger.tsx",
                        "wa_backend/api/warehouse/stocktake.py"):
            _expect_fail(mode, set(STOCKTAKE_789_SHELL_EXACT) | {foreign}, stocktake_sem)
        assert classify(mode, set(STOCKTAKE_FINAL_CI_782_EXACT), stocktake_sem) == (
            "policy-maintenance", []
        )
        for missing in STOCKTAKE_FINAL_CI_782_EXACT:
            assert classify(mode, set(STOCKTAKE_FINAL_CI_782_EXACT) - {missing}, stocktake_sem)[0] != "policy-maintenance"
        _expect_fail(mode, set(STOCKTAKE_FINAL_CI_782_EXACT) | {
            "dashboard/src/pages/inventory/MainInventory.tsx"
        }, stocktake_sem)
    assert classify("r3", set(STOCKTAKE_789_SHELL_EXACT), stocktake_sem) == (
        "not-applicable", []
    )
    assert classify("r3", set(STOCKTAKE_FINAL_CI_782_EXACT), stocktake_sem) == (
        "policy-maintenance", []
    )

    batch_compact_none = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for mode in ("ux", "operational"):
        assert classify(mode, BATCHES_COMPACT_V1_REQUIRED, batch_compact_none)[0] == "batches-compact-v1"
        assert classify(mode, BATCHES_COMPACT_V1_ALLOWED, batch_compact_none)[0] == "batches-compact-v1"
        for foreign in (
            "wa_backend/services.py",
            "dashboard/src/pages/DispatchBoard.tsx",
            "wanasah_frontend/lib/main.dart",
            "dashboard/src/pages/inventory/Tab4Ledger.tsx",
        ):
            _expect_fail(mode, BATCHES_COMPACT_V1_ALLOWED | {foreign}, batch_compact_none)

    batch_layout_none = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for mode in ("ux", "operational"):
        assert classify(mode, BATCHES_LAYOUT_769_REQUIRED, batch_layout_none)[0] == "batches-layout-769"
        assert classify(mode, BATCHES_LAYOUT_769_ALLOWED, batch_layout_none)[0] == "batches-layout-769"
        for foreign in (
            "dashboard/src/pages/inventory/TabBatches.tsx",
            "dashboard/src/pages/DispatchBoard.tsx",
            "wa_backend/services.py",
            "wanasah_frontend/lib/main.dart",
        ):
            _expect_fail(mode, BATCHES_LAYOUT_769_ALLOWED | {foreign}, batch_layout_none)

    ledger_none = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for ledger_mode in ("ux", "operational"):
        assert classify(ledger_mode, LEDGER_762_REQUIRED, ledger_none)[0] == "ledger-762"
        assert classify(ledger_mode, LEDGER_762_ALLOWED, ledger_none)[0] == "ledger-762"
        for forbidden in ("dashboard/src/pages/inventory/batches/BatchIndexTable.tsx",
                          "dashboard/src/pages/inventory/stocktake/StocktakeTable.tsx",
                          "wa_backend/services.py", "flutter/lib/main.dart",
                          "dashboard/src/pages/DispatchBoard.tsx", "LIVE_STOCK_V1_CLOSURE_PLAN.md"):
            _expect_fail(ledger_mode, LEDGER_762_ALLOWED | {forbidden}, ledger_none)

    selector_none = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for selector_mode in ("ux", "operational"):
        assert classify(selector_mode, BATCH_SELECTOR_OWNER_REQUIRED, selector_none)[0] == "batch-selector-owner"
        assert classify(selector_mode, BATCH_SELECTOR_OWNER_ALLOWED, selector_none)[0] == "batch-selector-owner"
        for foreign_path in ("wa_backend/services.py", "dashboard/src/pages/DispatchBoard.tsx",
                             "LIVE_STOCK_V1_CLOSURE_PLAN.md", "dashboard/src/pages/inventory/batches/batchIndexI18n.ts"):
            _expect_fail(selector_mode, BATCH_SELECTOR_OWNER_ALLOWED | {foreign_path}, selector_none)

    no_semantics = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for owner_mode in ("ux", "operational"):
        assert classify(owner_mode, OWNER_VISUAL_REQUIRED, no_semantics)[0] == "owner-visual-v1"
        assert classify(owner_mode, OWNER_VISUAL_ALLOWED, no_semantics)[0] == "owner-visual-v1"
        for rejected in ("wa_backend/services.py", "dashboard/src/lib/authStorage.ts",
                         "wa_backend/api/warehouse/live_stock.py",
                         "dashboard/src/pages/DispatchBoard.tsx"):
            _expect_fail(owner_mode, OWNER_VISUAL_ALLOWED | {rejected}, no_semantics)
    none = {SHARED_RESOURCES: False, SHARED_SCHEMA: False, SHARED_DISPATCH: False}
    for mode in ("ux", "operational"):
        assert classify(mode, set(IT03_REMAINING_REQUIRED), none)[0] == "it03-remaining-v1"
        assert classify(mode, set(IT03_REMAINING_ALLOWED), none)[0] == "it03-remaining-v1"
        for foreign in ("dashboard/src/pages/DispatchBoard.tsx",
                        "wa_backend/services.py", "LIVE_STOCK_V1_CLOSURE_PLAN.md"):
            _expect_fail(mode, IT03_REMAINING_ALLOWED | {foreign}, none)
    for mode in ("ux", "operational"):
        assert classify(mode, set(IT03_IT04_REENTRY_REQUIRED), none)[0] == "it03-it04-batch-reentry"
        assert classify(mode, set(IT03_IT04_REENTRY_ALLOWED), none)[0] == "it03-it04-batch-reentry"
        for foreign in ("dashboard/src/pages/DispatchBoard.tsx",
                        "wa_backend/services.py",
                        "LIVE_STOCK_V1_CLOSURE_PLAN.md",
                        "dashboard/src/pages/inventory/Tab2Inbound.tsx"):
            _expect_fail(mode, IT03_IT04_REENTRY_ALLOWED | {foreign}, none)
    seamless_scope = set(SEAMLESS_REENTRY_EXPLANATION_ALLOWED)
    for mode in ("ux", "r3", "operational"):
        assert classify(mode, seamless_scope, none)[0] == "seamless-reentry-explanation"
        for foreign in (
            "dashboard/src/pages/DispatchBoard.tsx",
            "wa_backend/services.py",
            "wa_backend/domains/inventory_costing/service.py",
            "flutter_app/lib/main.dart",
            "LIVE_STOCK_V1_CLOSURE_PLAN.md",
        ):
            _expect_fail(mode, seamless_scope | {foreign}, none)

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
    combined_worker1 = {
        OP_WORKFLOW,
        ".github/workflows/dispatch-p0-route-stock-safety.yml",
        "dashboard/e2e/live-stock-operational.spec.ts",
        "dashboard/src/pages/inventory/liveStock/i18n.ts",
    }
    for mode in ("ux", "operational"):
        assert classify(mode, combined_worker1, none)[0] == "owned"
        for foreign in (
            "wa_backend/api/dispatch.py",
            "wa_backend/domains/inventory_costing/service.py",
            "wa_backend/services.py",
            "dashboard/src/hooks/useAuthFetch.ts",
            "dashboard/src/features/dispatch/adjustLoad.ts",
        ):
            _expect_fail(mode, combined_worker1 | {foreign}, none)

    for mode in ("ux", "r3", "operational"):
        assert classify(mode, set(WAREHOUSE_VIEW_ALLOWED), none)[0] == "warehouse-minimum-view"
        for forbidden in (
            "wa_backend/services.py",
            "wa_backend/domains/inventory_costing/service.py",
            "dashboard/src/pages/DispatchBoard.tsx",
        ):
            _expect_fail(mode, set(WAREHOUSE_VIEW_ALLOWED) | {forbidden}, none)

    for mode in ("ux", "r3", "operational"):
        state, messages = classify(mode, false_positive, none)
        assert state == "not-applicable" and not messages, (mode, state, messages)

    assert classify("ux", {"dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx"}, none)[0] == "owned"
    _expect_fail("ux", {"dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx", "dashboard/src/pages/DispatchBoard.tsx"}, none)
    minimum_ux_scope = {
        HELPER,
        ".github/workflows/dispatch-p0-route-stock-safety.yml",
        "dashboard/src/pages/inventory/StockMinimumManager.tsx",
        "dashboard/src/test/inventory-cp6-minimum-stock-dashboard.test.tsx",
        SHARED_RESOURCES,
    }
    assert classify("r3", minimum_ux_scope, none)[0] == "not-applicable"
    _expect_fail("r3", minimum_ux_scope | {"wa_backend/api/dispatch.py"}, none)
    assert classify("r3", {"wa_backend/domains/live_stock_projection/service.py"}, none)[0] == "owned"
    _expect_fail("r3", {"wa_backend/domains/live_stock_projection/service.py", "dashboard/src/pages/DispatchBoard.tsx"}, none)

    perf_scope = set(PERFORMANCE_ACCEPTANCE_ALLOWED)
    assert classify("r3", perf_scope, none)[0] == "performance-acceptance"
    for foreign in (
        "wa_backend/services.py",
        "wa_backend/domains/inventory_costing/service.py",
        "dashboard/src/pages/inventory/MainInventory.tsx",
        "LIVE_STOCK_V1_CLOSURE_PLAN.md",
    ):
        _expect_fail("r3", perf_scope | {foreign}, none)

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
    minimum_resources = (
        base_resources
        + 'inventoryMinimum: { scopeAll: "AR assigned products" },\n'
        + 'inventoryMinimum: { scopeAll: "EN assigned products" },\n'
    )
    updated_minimum_resources = minimum_resources.replace(
        "AR assigned products", "AR warehouse-assigned products"
    )
    assert len(_object_sections(minimum_resources, "inventoryMinimum")) == 2
    assert _resource_signature(minimum_resources) != _resource_signature(updated_minimum_resources)
    live_sem = {**none, SHARED_RESOURCES: True}
    assert classify("ux", minimum_ux_scope, live_sem)[0] == "owned"
    assert classify("operational", minimum_ux_scope, live_sem)[0] == "owned"
    _expect_fail("ux", minimum_ux_scope | {"dashboard/src/pages/DispatchBoard.tsx"}, live_sem)
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
    # D10 #872 is the ONLY exact vetted exception for actor-scoped Dispatch UI
    # plus authStorage; all other socket-only session-boundary edits remain frozen.
    if (changed & SESSION_ISOLATION_ROOTS and "dashboard/src/pages/DispatchBoard.tsx" in changed
            and changed != DISPATCH_D10_872_EXACT):
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
