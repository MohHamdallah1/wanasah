"""Exact, no-hitchhiker D15 #918 presentation-fidelity fix scope.

This independently extends the historical D15 #913 acceptance. It cannot authorize
Backend, auth, permissions, global App, Inventory or Products changes.
"""
from __future__ import annotations
import sys

D15_918 = frozenset({
    ".github/scripts/dispatch_d15_real_content_scope.py",
    ".github/workflows/dispatch-d15-zero-flash.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/dispatch-d15-zero-flash.spec.ts",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
    "dashboard/src/test/dispatch-scale-containment.test.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/components/operations/DashboardLayout.tsx",
    "dashboard/src/components/dispatch/PendingRoutesTable.tsx",
    "dashboard/src/features/dispatch/stableUi/DispatchWorkspaceStructure.tsx",
    "dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx",
})

# Separate exact #922 P1 presentation/readiness scope. The original #918
# accepted set stays byte-for-byte mandatory for its historical PR.
D15_922 = frozenset({
    ".github/scripts/dispatch_d15_real_content_scope.py",
    ".github/workflows/dispatch-d15-launch-reentry-p1.yml",
    "dashboard/e2e/dispatch-d15-launch-reentry-p1.spec.ts",
    "dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx",
    "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-d11-commercial-preflight.test.tsx",
})

MARKER = ".github/scripts/dispatch_d15_real_content_scope.py"

def d15_real_content_mode(paths: set[str] | frozenset[str]) -> bool:
    actual = set(paths)
    if MARKER not in actual:
        return False
    if actual == D15_922:
        return True
    assert actual == D15_918, (
        "D15 #918 exact owner scope missing=" + str(sorted(D15_918 - actual)) +
        " foreign=" + str(sorted(actual - D15_918))
    )
    return True

def selftest() -> None:
    assert d15_real_content_mode(set(D15_918))
    assert d15_real_content_mode(set(D15_922))
    for absent in D15_922:
        candidate = set(D15_922 - {absent})
        if absent == MARKER:
            assert d15_real_content_mode(candidate) is False
        else:
            try: d15_real_content_mode(candidate)
            except AssertionError: pass
            else: raise AssertionError("D15 #922 incomplete scope accepted: " + absent)
    for extra in ("wa_backend/api/dispatch.py", "dashboard/src/App.tsx",
                  "dashboard/src/features/dispatch/commercialPreflight/useCommercialPreflight.ts",
                  "dashboard/src/components/ui/custom-select.tsx"):
        try: d15_real_content_mode(set(D15_922 | {extra}))
        except AssertionError: pass
        else: raise AssertionError("D15 #922 foreign file accepted: " + extra)

    for absent in D15_918:
        candidate = set(D15_918 - {absent})
        if absent == MARKER:
            assert d15_real_content_mode(candidate) is False
        else:
            try: d15_real_content_mode(candidate)
            except AssertionError: pass
            else: raise AssertionError("Missing file accepted: " + absent)
    for extra in ("dashboard/src/App.tsx", "dashboard/src/hooks/useInventoryAccess.ts",
                  "dashboard/src/features/dispatch/useDispatchAccessGate.ts",
                  "dashboard/src/components/operations/dashboard.css",
                  "dashboard/src/pages/products/ProductsPage.tsx",
                  "wa_backend/api/dispatch.py", "dashboard/src/lib/authStorage.ts"):
        try: d15_real_content_mode(set(D15_918 | {extra}))
        except AssertionError: pass
        else: raise AssertionError("Foreign scope accepted: " + extra)
    print("D15_918_REAL_CONTENT_SCOPE=PASS total=13 missing=13 foreign=7")
    print("D15_922_LAUNCH_P1_SCOPE=PASS total=7 missing=7 foreign=4")

if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]: raise SystemExit("Only --selftest")
    selftest()
