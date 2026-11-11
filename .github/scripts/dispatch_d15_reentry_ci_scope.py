"""D15 #908: a single exact, no-hitchhiker fast secure reentry PR.

Historical D07/D06/D14/D15-1A owner contracts remain independently enforced.
"""
from __future__ import annotations
import sys

D15_908 = frozenset({
    ".github/scripts/dispatch_d15_reentry_ci_scope.py",
    ".github/workflows/dispatch-d15-reentry.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/dispatch-d15-reentry.config.ts",
    "dashboard/e2e/dispatch-d14-browser.spec.ts",
    "dashboard/e2e/dispatch-d15-reentry.spec.ts",
    "dashboard/src/components/operations/DashboardLayout.tsx",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
})
MARKER = ".github/scripts/dispatch_d15_reentry_ci_scope.py"

def d15_reentry_mode(files: set[str] | frozenset[str]) -> bool:
    candidate = set(files)
    if MARKER not in candidate:
        return False
    assert candidate == D15_908, (
        "D15 #908 file ownership must be EXACT: "
        f"missing={sorted(D15_908 - candidate)} "
        f"foreign={sorted(candidate - D15_908)}"
    )
    return True

def selftest() -> None:
    assert d15_reentry_mode(set(D15_908))
    for missing in D15_908:
        trimmed = set(D15_908 - {missing})
        if missing == MARKER:
            assert not d15_reentry_mode(trimmed)
        else:
            try: d15_reentry_mode(trimmed)
            except AssertionError: pass
            else: raise AssertionError(f"Admitted missing file: {missing}")
    for foreign in (
        "dashboard/src/components/operations/dashboard.css",
        "dashboard/e2e/dispatch-d15-overflow.spec.ts",
        "dashboard/src/hooks/useInventoryAccess.ts",
        "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
        "dashboard/src/App.tsx",
        "wa_backend/api/dispatch.py",
        "wa_backend/models.py",
        "wanasah_flutter/lib/main.dart",
    ):
        try: d15_reentry_mode(set(D15_908 | {foreign}))
        except AssertionError: pass
        else: raise AssertionError(f"Admitted foreign path: {foreign}")
    print("D15_908_EXACT_SCOPE=PASS eleven=11 missing=11 foreign=8 Worker2_CSS=DENIED")

# D15 #909 exact measured source fix + signed 60-sample Chromium proof.
# Historical #908 exact scope remains unchanged; no cross-owner wildcard.
D15_909 = frozenset({
    ".github/scripts/dispatch_d15_reentry_ci_scope.py",
    ".github/workflows/dispatch-d15-reentry.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/dispatch-d15-horizontal-overflow.spec.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
})
D15_909_MARKER = "dashboard/e2e/dispatch-d15-horizontal-overflow.spec.ts"

def d15_overflow_mode(files: set[str] | frozenset[str]) -> bool:
    candidate = set(files)
    if D15_909_MARKER not in candidate:
        return False
    assert candidate == D15_909, (
        "D15 #909 EXACT missing=" + str(sorted(D15_909 - candidate)) +
        " foreign=" + str(sorted(candidate - D15_909))
    )
    return True

def overflow_selftest() -> None:
    assert d15_overflow_mode(set(D15_909))
    for missing in D15_909:
        subset = set(D15_909 - {missing})
        if missing == D15_909_MARKER:
            assert not d15_overflow_mode(subset)
        else:
            try: d15_overflow_mode(subset)
            except AssertionError: pass
            else: raise AssertionError(f"D15 #909 missing file admitted: {missing}")
    for foreign in (
        "dashboard/src/lib/authStorage.ts",
        "dashboard/src/hooks/useInventoryAccess.ts",
        "dashboard/src/components/operations/dashboard.css",
        "dashboard/src/components/dashboard/WorkspaceTopBar.css",
        "dashboard/src/components/operations/DashboardLayout.tsx",
        "wa_backend/api/dispatch.py",
        "wa_backend/main.py",
        "wanasah_frontend/lib/main.dart",
    ):
        try: d15_overflow_mode(set(D15_909 | {foreign}))
        except AssertionError: pass
        else: raise AssertionError(f"D15 #909 foreign admitted: {foreign}")
    print("D15_909_EXACT_SCOPE=PASS paths=7 missing=7 foreign=8; D15_908 scope unchanged")

if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("Only --selftest supported")
    selftest()
    overflow_selftest()
