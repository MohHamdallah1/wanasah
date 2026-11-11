"""D14 #891: exact reviewed browser acceptance PR ownership.

This is a frozen ten-file exception for one real PG16/Chromium release proof,
not a general permission to alter historical Dispatch/Inventory gates.
"""
from __future__ import annotations

import sys

D14_BROWSER_SCOPE = frozenset({
    ".github/scripts/dispatch_d14_ci_scope.py",
    ".github/workflows/dispatch-d14-browser-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/dispatch-d14-browser.config.ts",
    "dashboard/e2e/dispatch-d14-browser.spec.ts",
    "dashboard/src/components/operations/OperationsSidebar.tsx",
    "dashboard/src/pages/DispatchBoard.tsx",
    "wa_backend/tests/test_dispatch_d14_browser_fixture.py",
})

# Unique to #891. Historical PRs with shared Board/gate files remain governed by
# their existing frozen ownership modes; a partial #891 never inherits a mode.
D14_BROWSER_MARKERS = frozenset({
    ".github/scripts/dispatch_d14_ci_scope.py",
    ".github/workflows/dispatch-d14-browser-acceptance.yml",
    "dashboard/e2e/dispatch-d14-browser.config.ts",
    "dashboard/e2e/dispatch-d14-browser.spec.ts",
    "wa_backend/tests/test_dispatch_d14_browser_fixture.py",
})


def d14_mode(candidate: set[str] | frozenset[str]) -> bool:
    candidate = set(candidate)
    if not candidate.intersection(D14_BROWSER_MARKERS):
        return False
    assert candidate == D14_BROWSER_SCOPE, (
        "D14 browser scope must be EXACT, no missing/foreign paths; "
        f"missing={sorted(D14_BROWSER_SCOPE - candidate)}, "
        f"foreign={sorted(candidate - D14_BROWSER_SCOPE)}"
    )
    return True


def selftest() -> None:
    assert d14_mode(set(D14_BROWSER_SCOPE))
    for missing in D14_BROWSER_SCOPE:
        partial = set(D14_BROWSER_SCOPE - {missing})
        try:
            d14_mode(partial)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"D14 partial scope admitted: {missing}")
    for foreign in (
        "wa_backend/api/dispatch.py",
        "wa_backend/services.py",
        "wa_backend/domains/inventory_costing/service.py",
        "dashboard/src/lib/authStorage.ts",
        "dashboard/src/components/dispatch/ShopTable.tsx",
        "wanasah_frontend/lib/main.dart",
        "ARCHITECTURE.md",
    ):
        try:
            d14_mode(set(D14_BROWSER_SCOPE | {foreign}))
        except AssertionError:
            pass
        else:
            raise AssertionError(f"D14 foreign path admitted: {foreign}")
    assert not d14_mode({"dashboard/src/pages/DispatchBoard.tsx"})
    print("D14_BROWSER_EXACT_SCOPE=PASS exact=10 missing=10 foreign=7 shared-old=DENIED")


if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("Only --selftest is supported")
    selftest()
