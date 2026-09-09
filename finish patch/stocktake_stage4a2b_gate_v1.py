from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
TAB = INV / "Tab3Stocktake.tsx"
STOCKTAKE = INV / "stocktake"

FILES = {
    "state": STOCKTAKE / "hooks" / "useStocktakeState.ts",
    "lifecycle": STOCKTAKE / "hooks" / "useStocktakeLifecycle.ts",
    "sessions": STOCKTAKE / "hooks" / "useStocktakeSessions.ts",
    "counting": STOCKTAKE / "hooks" / "useStocktakeCounting.ts",
    "review": STOCKTAKE / "hooks" / "useStocktakeReview.ts",
    "actions": STOCKTAKE / "hooks" / "useStocktakeActions.ts",
    "counting_panel": STOCKTAKE / "StocktakeCountingPanel.tsx",
    "review_panel": STOCKTAKE / "StocktakeReviewPanel.tsx",
    "count_modals": STOCKTAKE / "StocktakeCountModals.tsx",
    "decision_modals": STOCKTAKE / "StocktakeDecisionModals.tsx",
    "session_center": STOCKTAKE / "StocktakeSessionCenter.tsx",
    "types": STOCKTAKE / "types.ts",
    "parsers": STOCKTAKE / "parsers.ts",
}


def fail(label: str) -> None:
    raise SystemExit(
        f"STOCKTAKE_STAGE4A2B_GATE=FAIL\n{label}=FAIL"
    )


def require(ok: bool, label: str) -> None:
    if not ok:
        fail(label)
    print(f"{label}=OK")


require(TAB.exists(), "FILE_TAB3")
for name, path in FILES.items():
    require(path.exists(), f"FILE_{name.upper()}")

tab = TAB.read_text(encoding="utf-8").replace("\r\n", "\n")
text = {
    name: path.read_text(encoding="utf-8").replace("\r\n", "\n")
    for name, path in FILES.items()
}
combined = "\n".join(text.values())

require(len(tab.splitlines()) < 430, "TAB_ORCHESTRATOR_SIZE")
require("authenticatedFetch(" not in tab, "TAB_NO_DIRECT_API_CALL")
require("toast." not in tab, "TAB_NO_DOMAIN_TOAST")
require("QuantityInput" not in tab, "TAB_NO_COUNTING_WIDGET")
require("<Modal" not in tab, "TAB_NO_MODAL_IMPLEMENTATION")
require("actual_quantity" not in tab, "TAB_NO_COUNT_PAYLOAD")
require("count_attempt_id" not in tab, "TAB_NO_DECISION_PAYLOAD")

require(
    "useStocktakeState({" in tab
    and "useStocktakeLifecycle({" in tab
    and "useStocktakeCounting({" in tab
    and "useStocktakeReview({" in tab
    and "useStocktakeActions({" in tab,
    "TAB_HOOK_ORCHESTRATION",
)

counting = text["counting"]
review = text["review"]
actions = text["actions"]
lifecycle = text["lifecycle"]

require(
    "/warehouse/unified/stocktake/${sid}/count-sheet" in counting,
    "COUNTING_BLIND_SHEET_ENDPOINT",
)
require(
    "stock_status: row.stock_status" in counting,
    "COUNTING_STOCK_STATUS_PAYLOAD",
)
require(
    "actual_quantity: toTotalPacks(" in counting,
    "COUNTING_QUANTITY_PAYLOAD",
)
require(
    "/warehouse/unified/stocktake/${sessionId}/count" in counting,
    "COUNTING_SUBMIT_ENDPOINT",
)
require(
    "phase === \"COUNTING\"" in counting
    and "isAuditLocked" not in counting,
    "COUNTING_CYCLE_DRAFT_PERSISTENCE",
)
require(
    "wanasah_audit_draft:${companyScope}:${locationId}:${sid}" in counting,
    "COUNTING_TENANT_DRAFT_SCOPE",
)
require(
    "expected_quantity" not in counting,
    "COUNTING_EXPECTED_QUANTITY_HIDDEN",
)

require(
    "/warehouse/unified/stocktake/${sid}/review" in review,
    "REVIEW_ENDPOINT",
)
require(
    "data.location_id !== locationId" in review,
    "REVIEW_LOCATION_FAIL_CLOSED",
)
require(
    "approvalBlocked" in review,
    "REVIEW_INDEPENDENT_RECOUNT_GATE",
)

require(
    "/warehouse/unified/stocktake/${sessionId}/approve" in actions,
    "APPROVE_ENDPOINT",
)
require(
    "/warehouse/unified/stocktake/${sessionId}/recount" in actions,
    "RECOUNT_ENDPOINT",
)
require(
    "/warehouse/unified/stocktake/${sessionId}/cancel" in actions,
    "CANCEL_ENDPOINT",
)
require(
    actions.count("review.latest_attempt.id") >= 2,
    "APPROVE_RECOUNT_ATTEMPT_CONCURRENCY",
)
require(
    "authorizer_username:" in actions
    and "authorizer_password:" in actions,
    "RECOUNT_AUTHORIZER_CONTRACT",
)
require(
    "parseRecountRequiresIndependent(raw)" in actions,
    "RECOUNT_INDEPENDENT_RESPONSE",
)

require(
    '"/warehouse/unified/stocktake/start"' in lifecycle
    and '"FULL_COUNT"' in lifecycle,
    "FULL_COUNT_START_PRESERVED",
)
require(
    "sessionsLoadFailed" in lifecycle
    and "activeSessionsTotal" in lifecycle,
    "FULL_COUNT_ACTIVE_SESSION_GUARD",
)
require(
    "loadReview(sid)" in lifecycle
    and "loadCountSheet(sid)" in lifecycle,
    "SERVER_DRIVEN_SESSION_RECOVERY",
)

require(
    "/warehouse/unified/stocktakes/active?" in text["sessions"],
    "SESSION_CENTER_ENDPOINT_PRESERVED",
)
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

print("STOCKTAKE_STAGE4A2B_GATE=PASS")
