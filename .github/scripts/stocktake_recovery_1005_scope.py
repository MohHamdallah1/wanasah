"""Exact immutable owner scope for stocktake session recovery after logout (#1005).

This code is imported by historic owner gates. Its exact manifest is additive:
none of their prior V1 acceptance sets or failure rules is weakened.
"""
from __future__ import annotations

STOCKTAKE_RECOVERY_1005_FILES = frozenset({
    ".github/scripts/stocktake_recovery_1005_scope.py",
    ".github/workflows/stocktake-v1-discovered-pg16-ui.yml",
    ".github/workflows/stocktake-v1-operator-782.yml",
    ".github/workflows/stocktake-v1-review-779.yml",
    ".github/workflows/stocktake-v1-session-read-fence.yml",
    ".github/workflows/stocktake-v1-history-799.yml",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeLifecycle.ts",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeSessions.ts",
    "dashboard/src/pages/inventory/stocktake/uiCopy.ts",
    "dashboard/src/pages/inventory/stocktake/StocktakeServerRecovery.test.tsx",
})


def stocktake_recovery_1005_mode(paths: set[str] | frozenset[str]) -> bool:
    """One full agreed source set, never a subset/superset or unrelated feature."""
    return set(paths) == STOCKTAKE_RECOVERY_1005_FILES


def selftest() -> None:
    assert len(STOCKTAKE_RECOVERY_1005_FILES) == 11
    assert stocktake_recovery_1005_mode(STOCKTAKE_RECOVERY_1005_FILES)
    for item in STOCKTAKE_RECOVERY_1005_FILES:
        assert not stocktake_recovery_1005_mode(STOCKTAKE_RECOVERY_1005_FILES - {item}), item
    for foreign in (
        "wa_backend/api/warehouse/stocktake.py",
        "dashboard/src/pages/inventory/stocktake/StocktakeIdlePanel.tsx",
        "dashboard/src/pages/inventory/Tab4Ledger.tsx",
        "wanasah_frontend/lib/main.dart",
    ):
        assert not stocktake_recovery_1005_mode(
            STOCKTAKE_RECOVERY_1005_FILES | {foreign}
        ), foreign
    assert not stocktake_recovery_1005_mode(set())
    print("STOCKTAKE_RECOVERY_1005_SCOPE=PASS exact=11 missing=11 foreign=4")


if __name__ == "__main__":
    selftest()
