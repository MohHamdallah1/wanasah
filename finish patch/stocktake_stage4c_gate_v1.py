from __future__ import annotations

from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
STOCK = INV / "stocktake"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"

FILES = {
    "tab": INV / "Tab3Stocktake.tsx",
    "types": STOCK / "types.ts",
    "parsers": STOCK / "parsers.ts",
    "center": STOCK / "StocktakeSessionCenter.tsx",
    "vehicle_modal":
        STOCK / "StocktakeVehicleReconModal.tsx",
    "state":
        STOCK / "hooks" / "useStocktakeState.ts",
    "counting":
        STOCK / "hooks" / "useStocktakeCounting.ts",
    "review":
        STOCK / "hooks" / "useStocktakeReview.ts",
    "actions":
        STOCK / "hooks" / "useStocktakeActions.ts",
    "lifecycle":
        STOCK / "hooks" / "useStocktakeLifecycle.ts",
    "cycle":
        STOCK / "hooks" / "useCycleCountStart.ts",
    "vehicle":
        STOCK / "hooks" / "useVehicleReconStart.ts",
    "sessions":
        STOCK / "hooks" / "useStocktakeSessions.ts",
}


def fail(label: str) -> None:
    raise SystemExit(
        f"STOCKTAKE_STAGE4C_GATE=FAIL\n{label}=FAIL"
    )


def require(ok: bool, label: str) -> None:
    if not ok:
        fail(label)
    print(f"{label}=OK")


for name, path in FILES.items():
    require(
        path.exists(),
        f"FILE_{name.upper()}",
    )
for path in (WAREHOUSE, SCHEMAS):
    require(
        path.exists(),
        f"FILE_{path.name}",
    )

text = {
    name: path.read_text(
        encoding="utf-8"
    ).replace("\r\n", "\n")
    for name, path in FILES.items()
}
warehouse = WAREHOUSE.read_text(
    encoding="utf-8"
).replace("\r\n", "\n")
schemas = SCHEMAS.read_text(
    encoding="utf-8"
).replace("\r\n", "\n")
combined = "\n".join(text.values())

# Backend response contracts.
require(
    "class StocktakeSessionContextResponse(BaseModel):"
    in schemas,
    "BACKEND_CONTEXT_SCHEMA",
)
require(
    "class VehicleReconCandidateCursorPage(BaseModel):"
    in schemas,
    "BACKEND_VEHICLE_CANDIDATE_SCHEMA",
)

# Route uniqueness through AST.
tree = ast.parse(warehouse)
routes: list[str] = []
for node in ast.walk(tree):
    if not isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        continue
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            continue
        if (
            not isinstance(func.value, ast.Name)
            or func.value.id != "router"
        ):
            continue
        if func.attr not in {
            "get",
            "post",
            "patch",
            "delete",
            "put",
        }:
            continue
        if not decorator.args:
            continue
        arg = decorator.args[0]
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
        ):
            routes.append(
                f"{func.attr.upper()} {arg.value}"
            )

require(
    routes.count(
        "GET /warehouse/unified/stocktake/vehicle-recon-candidates"
    ) == 1,
    "BACKEND_VEHICLE_CANDIDATE_ROUTE_UNIQUE",
)
require(
    routes.count(
        "GET /warehouse/unified/stocktake/{session_id}/context"
    ) == 1,
    "BACKEND_CONTEXT_ROUTE_UNIQUE",
)
require(
    routes.count(
        "POST /warehouse/unified/stocktake/start"
    ) == 1,
    "BACKEND_START_ROUTE_UNIQUE",
)

# Candidate eligibility: ended, financially unsettled, unreconciled.
require(
    "WorkSession.end_time.is_not(None)"
    in warehouse,
    "VEHICLE_WORK_SESSION_ENDED_ONLY",
)
require(
    "WorkSession.is_settled.is_(False)"
    in warehouse,
    "VEHICLE_WORK_SESSION_FINANCIALLY_UNSETTLED",
)
require(
    "WorkSession.inventory_reconciled_at"
    in warehouse
    and ".is_(None)" in warehouse,
    "VEHICLE_WORK_SESSION_INVENTORY_UNRECONCILED",
)

# Source warehouse and same-vehicle linkage.
require(
    "DispatchRoute.source_location_id"
    in warehouse
    and "== source_location_id"
    in warehouse,
    "VEHICLE_SOURCE_WAREHOUSE_SCOPE",
)
require(
    "InventoryLocation.location_type"
    in warehouse
    and '== "VEHICLE"' in warehouse
    and "InventoryLocation.vehicle_id"
    in warehouse,
    "VEHICLE_LOCATION_SCOPE",
)
require(
    "DispatchRoute.work_session_id"
    in warehouse
    and "DispatchRoute.vehicle_id"
    in warehouse,
    "VEHICLE_WORK_SESSION_ROUTE_LINK",
)

# Context endpoint verifies anchor->vehicle session relationship server-side.
require(
    "anchor_location_id"
    in warehouse
    and "source_location_id"
    in warehouse,
    "SESSION_CONTEXT_ANCHOR_SCOPE",
)
require(
    "stocktake_type == \"VEHICLE_RECON\""
    in warehouse
    or 'stocktake_type == "VEHICLE_RECON"'
    in warehouse,
    "SESSION_CONTEXT_VEHICLE_BRANCH",
)
require(
    "DispatchRoute.work_session_id"
    in warehouse
    and "related_work_session_id"
    in warehouse,
    "SESSION_CONTEXT_RELATED_WORK_SESSION",
)

# Frontend: actual session location is first-class state.
require(
    "sessionLocationId"
    in text["state"]
    and "setSessionLocationId"
    in text["state"],
    "FRONTEND_SESSION_LOCATION_STATE",
)
require(
    "wanasah_audit_draft:${companyScope}:${sessionLocationId}:${sessionId}"
    in text["state"],
    "FRONTEND_DRAFT_ACTUAL_LOCATION_SCOPE",
)
require(
    "effectiveLocationId"
    in text["counting"]
    and "wanasah_audit_draft:${companyScope}:${effectiveLocationId}:${sid}"
    in text["counting"],
    "COUNTING_ACTUAL_LOCATION_SCOPE",
)
require(
    "data.location_id !=="
    in text["review"]
    and "effectiveLocationId"
    in text["review"],
    "REVIEW_ACTUAL_LOCATION_FAIL_CLOSED",
)

# Recovery is server-driven and anchored.
require(
    "/context?"
    in text["lifecycle"]
    and "anchor_location_id"
    in text["lifecycle"],
    "LIFECYCLE_SERVER_CONTEXT",
)
require(
    "parseStocktakeSessionContext"
    in text["lifecycle"],
    "LIFECYCLE_CONTEXT_FAIL_CLOSED",
)
require(
    "openSessionById"
    in text["lifecycle"],
    "LIFECYCLE_GENERIC_SESSION_OPEN",
)

# Vehicle candidate workflow.
vehicle = text["vehicle"]
require(
    "/warehouse/unified/stocktake/vehicle-recon-candidates?"
    in vehicle,
    "FRONTEND_VEHICLE_CANDIDATE_ENDPOINT",
)
require(
    'stocktake_type:\n                "VEHICLE_RECON"'
    in vehicle
    or '"VEHICLE_RECON"' in vehicle,
    "FRONTEND_VEHICLE_RECON_START_TYPE",
)
require(
    "candidate.vehicle_location_id"
    in vehicle,
    "FRONTEND_VEHICLE_LOCATION_ID",
)
require(
    "candidate.work_session_id"
    in vehicle
    and "related_work_session_id"
    in vehicle,
    "FRONTEND_RELATED_WORK_SESSION_ID",
)
require(
    "existing_stocktake_session_id"
    in vehicle
    and "openSessionById"
    in vehicle,
    "FRONTEND_EXISTING_RECON_REUSE",
)
require(
    "productRequestSeq" not in vehicle
    and "requestSeq.current" in vehicle,
    "FRONTEND_VEHICLE_RACE_GUARD",
)

# Unified engine is reused, not duplicated.
require(
    "/count" not in vehicle
    and "/approve" not in vehicle
    and "/recount" not in vehicle
    and "/cancel" not in vehicle,
    "VEHICLE_REUSES_UNIFIED_STOCKTAKE_ENGINE",
)
require(
    "stock_status: row.stock_status"
    in text["counting"],
    "COUNTING_STOCK_STATUS_PRESERVED",
)
require(
    text["actions"].count(
        "review.latest_attempt.id"
    ) >= 2,
    "APPROVE_RECOUNT_CONCURRENCY_PRESERVED",
)
require(
    '"FULL_COUNT"' in text["lifecycle"],
    "FULL_COUNT_PRESERVED",
)
require(
    '"CYCLE_COUNT"' in combined,
    "CYCLE_COUNT_PRESERVED",
)

# UI entry points.
require(
    "onStartVehicleRecon"
    in text["center"],
    "SESSION_CENTER_VEHICLE_ENTRY",
)
require(
    "useVehicleReconStart({"
    in text["tab"]
    and "<StocktakeVehicleReconModal"
    in text["tab"],
    "TAB_VEHICLE_ORCHESTRATION",
)

# Tenant authority stays server-side.
require(
    "company_id" not in combined,
    "FRONTEND_NO_COMPANY_ID_PAYLOAD",
)
require(
    ": any" not in combined
    and "any[]" not in combined
    and "Promise<any>" not in combined,
    "FRONTEND_NO_EXPLICIT_ANY",
)

print("STOCKTAKE_STAGE4C_GATE=PASS")
