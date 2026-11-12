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
    "dashboard/e2e/dispatch-d15-zero-flash.spec.ts",
    "dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx",
    "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-d11-commercial-preflight.test.tsx",
})

# #925: exact DATA-only progressive signed reentry scope. No auth/backend/other pages.
D15_925 = frozenset({
    ".github/scripts/dispatch_d15_real_content_scope.py",
    ".github/workflows/dispatch-d15-data-reentry-p1.yml",
    "dashboard/e2e/dispatch-d15-data-reentry-p1.spec.ts",
    "dashboard/src/features/dispatch/loadDispatchRead.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/components/dispatch/ShopTable.tsx",
    "dashboard/src/components/dispatch/RouteLoadProductTable.tsx",
    "dashboard/src/components/dispatch/ProductSearchControls.tsx",
    "dashboard/src/test/dispatch-capability-denied-v1.test.ts",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
})

# D15 2026-11-12: same-actor signed warm READ, no normal return blackout.
# Exactly two UI modules, the existing access gate, one unit + one real
# browser witness, and the already-owned targeted CI workflow/guard.
D15_WARM_REENTRY = frozenset({
    ".github/scripts/dispatch_d15_real_content_scope.py",
    ".github/workflows/dispatch-d15-data-reentry-p1.yml",
    "dashboard/e2e/dispatch-d15-data-reentry-p1.spec.ts",
    "dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx",
    "dashboard/src/features/dispatch/useDispatchAccessGate.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-access-notice-v1.test.tsx",
})

# #930: a strictly UI-only Launch operator-workbench redesign. No Backend,
# cross-page auth, pricing authority or unrelated Dispatch tab code may enter.
D15_LAUNCH_UI_930 = frozenset({
    ".github/scripts/dispatch_d15_real_content_scope.py",
    "dashboard/src/components/dispatch/ProductSearchControls.tsx",
    "dashboard/src/components/dispatch/RouteLoadProductTable.tsx",
    "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-d11-commercial-preflight.test.tsx",
    "dashboard/src/test/dispatch-product-discovery.test.tsx",
})

MARKER = ".github/scripts/dispatch_d15_real_content_scope.py"

def d15_real_content_mode(paths: set[str] | frozenset[str]) -> bool:
    actual = set(paths)
    if MARKER not in actual:
        return False
    if actual == D15_LAUNCH_UI_930:
        return True
    if actual == D15_WARM_REENTRY:
        return True
    if actual == D15_925:
        return True
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
    assert d15_real_content_mode(set(D15_925))
    assert d15_real_content_mode(set(D15_WARM_REENTRY))
    assert d15_real_content_mode(set(D15_LAUNCH_UI_930))
    for missing in D15_LAUNCH_UI_930:
        candidate = set(D15_LAUNCH_UI_930 - {missing})
        if missing == MARKER:
            assert d15_real_content_mode(candidate) is False
        else:
            try: d15_real_content_mode(candidate)
            except AssertionError: pass
            else: raise AssertionError("D15 #930 incomplete scope accepted: " + missing)
    for foreign in ("dashboard/src/App.tsx", "dashboard/src/hooks/useInventoryAccess.ts",
                    "dashboard/src/features/dispatch/commercialPreflight/contract.ts",
                    "wa_backend/api/dispatch.py", "dashboard/src/pages/products/ProductsPage.tsx",
                    "dashboard/src/pages/inventory/MainInventory.tsx"):
        try: d15_real_content_mode(set(D15_LAUNCH_UI_930 | {foreign}))
        except AssertionError: pass
        else: raise AssertionError("D15 #930 foreign file accepted: " + foreign)
    for missing in D15_WARM_REENTRY:
        candidate = set(D15_WARM_REENTRY - {missing})
        if missing == MARKER:
            assert d15_real_content_mode(candidate) is False
        else:
            try: d15_real_content_mode(candidate)
            except AssertionError: pass
            else: raise AssertionError("D15 warm reentry partial admitted " + missing)
    for foreign in ("wa_backend/api/dispatch.py", "dashboard/src/App.tsx",
                    "dashboard/src/hooks/useInventoryAccess.ts"):
        try: d15_real_content_mode(set(D15_WARM_REENTRY | {foreign}))
        except AssertionError: pass
        else: raise AssertionError("D15 warm reentry foreign admitted " + foreign)
    for missing in D15_925:
        candidate = set(D15_925 - {missing})
        if missing == MARKER:
            assert d15_real_content_mode(candidate) is False
        else:
            try: d15_real_content_mode(candidate)
            except AssertionError: pass
            else: raise AssertionError("D15 #925 partial admitted " + missing)
    for foreign in ("wa_backend/api/dispatch.py", "dashboard/src/App.tsx",
                    "dashboard/src/hooks/useInventoryAccess.ts",
                    "dashboard/src/features/dispatch/commercialPreflight/useCommercialPreflight.ts"):
        try: d15_real_content_mode(set(D15_925 | {foreign}))
        except AssertionError: pass
        else: raise AssertionError("D15 #925 foreign admitted " + foreign)

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
    print("D15_922_LAUNCH_P1_SCOPE=PASS total=8 missing=8 foreign=4")
    print("D15_925_DATA_REENTRY_SCOPE=PASS total=10 missing=10 foreign=4")
    print("D15_930_LAUNCH_WORKBENCH_SCOPE=PASS total=7 missing=7 foreign=6")

if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]: raise SystemExit("Only --selftest")
    selftest()
