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

if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("Only --selftest supported")
    selftest()
