"""D15 #899 Batch 1A: exact, narrowly reviewed visual/fresh-auth scope.

Never admit a partial, foreign, or mixed CI-policy/Backend/Worker2 PR via
this dedicated scope. Legacy D06/D07/D14 route safety checks remain active.
"""
from __future__ import annotations

import sys

D15_VISUAL_1A = frozenset({
    ".github/scripts/dispatch_d15_visual_ci_scope.py",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/dispatch-d14-browser.spec.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
})

D15_ONLY_MARKER = ".github/scripts/dispatch_d15_visual_ci_scope.py"


def d15_visual_mode(candidate: set[str] | frozenset[str]) -> bool:
    actual = set(candidate)
    if D15_ONLY_MARKER not in actual:
        return False
    assert actual == D15_VISUAL_1A, (
        "D15 #899 author scope is EXACT; "
        f"missing={sorted(D15_VISUAL_1A - actual)} "
        f"foreign={sorted(actual - D15_VISUAL_1A)}"
    )
    return True


def selftest() -> None:
    assert d15_visual_mode(set(D15_VISUAL_1A))
    for missing in D15_VISUAL_1A:
        partial = set(D15_VISUAL_1A - {missing})
        if missing == D15_ONLY_MARKER:
            # Without the *only* D15 marker, this scope confers no authority;
            # the existing owner gates reject the remaining D14 partial.
            assert d15_visual_mode(partial) is False
            continue
        try:
            d15_visual_mode(partial)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"D15 partial admitted: {missing}")
    for foreign in (
        "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
        "dashboard/src/lib/authStorage.ts",
        "dashboard/src/components/operations/OperationsSidebar.tsx",
        "wa_backend/api/dispatch.py",
        "wa_backend/services.py",
        "wa_backend/domains/inventory_costing/service.py",
        "wanasah_frontend/lib/main.dart",
        "ARCHITECTURE.md",
    ):
        try:
            d15_visual_mode(set(D15_VISUAL_1A | {foreign}))
        except AssertionError:
            pass
        else:
            raise AssertionError(f"D15 foreign scope admitted: {foreign}")
    assert not d15_visual_mode({
        "dashboard/src/pages/DispatchBoard.tsx",
        "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
    }), "Worker2 mixed files must not become authorized"
    print("D15_VISUAL_1A_EXACT_SCOPE=PASS exact=7 missing=7 foreign=8 Worker2=DENIED")


if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("Only --selftest is supported")
    selftest()
