"""D15 #913: frozen exact zero-flash visual+auth-safe scope, no wildcards."""
from __future__ import annotations
import sys

D15_913_SCOPE = frozenset({
    ".github/scripts/dispatch_d15_zero_flash_scope.py",
    ".github/workflows/dispatch-d15-zero-flash.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/e2e/dispatch-d14-browser.spec.ts",
    "dashboard/e2e/dispatch-d15-zero-flash.spec.ts",
    "dashboard/src/components/operations/DashboardLayout.tsx",
    "dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx",
    "dashboard/src/features/dispatch/stableUi/DispatchWorkspaceStructure.tsx",
    "dashboard/src/features/dispatch/stableUi/dispatchNoMotion.css",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/auth-session-consumer-isolation.test.tsx",
})
MARKER = ".github/scripts/dispatch_d15_zero_flash_scope.py"

def d15_zero_flash_mode(paths: set[str] | frozenset[str]) -> bool:
    actual = set(paths)
    if MARKER not in actual:
        return False
    assert actual == D15_913_SCOPE, (
        "D15 #913 exact ownership only: "
        f"missing={sorted(D15_913_SCOPE - actual)} "
        f"foreign={sorted(actual - D15_913_SCOPE)}"
    )
    return True

def selftest() -> None:
    assert d15_zero_flash_mode(set(D15_913_SCOPE))
    for missing in D15_913_SCOPE:
        subset = set(D15_913_SCOPE - {missing})
        if missing == MARKER:
            assert d15_zero_flash_mode(subset) is False
        else:
            try:
                d15_zero_flash_mode(subset)
            except AssertionError:
                pass
            else:
                raise AssertionError(f"Partial D15 scope admitted: {missing}")
    for foreign in (
        "dashboard/src/App.tsx",
        "dashboard/src/hooks/useInventoryAccess.ts",
        "dashboard/src/features/dispatch/useDispatchAccessGate.ts",
        "dashboard/src/components/dashboard/WorkspaceTopBar.css",
        "dashboard/src/components/operations/dashboard.css",
        "dashboard/e2e/dispatch-d15-first-paint.spec.ts",
        "dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx",
        "wa_backend/api/dispatch.py",
        "wa_backend/main.py",
        "wanasah_frontend/lib/main.dart",
    ):
        try:
            d15_zero_flash_mode(set(D15_913_SCOPE | {foreign}))
        except AssertionError:
            pass
        else:
            raise AssertionError(f"Foreign D15 scope admitted: {foreign}")
    assert not d15_zero_flash_mode({"dashboard/src/pages/DispatchBoard.tsx"})
    print("D15_913_EXACT_SCOPE=PASS total=13 missing=13 foreign=10 no_worker2_or_auth_scope")

if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("Only --selftest accepted")
    selftest()
