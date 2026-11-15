"""Exact independently reviewed V1 zero-flash Stocktake #1026 owner scope.

Additive admission only: existing historic owner sets and immutable original
door and PG16/ledger boundaries remain unchanged. Reject all incomplete,
superset, unrelated and cross-worker scopes.
"""
from __future__ import annotations

STOCKTAKE_ZERO_FLASH_1026_FILES = frozenset({
    ".github/scripts/stocktake_zero_flash_1026_scope.py",
    ".github/workflows/stocktake-v1-operator-782.yml",
    ".github/workflows/stocktake-v1-discovered-pg16-ui.yml",
    ".github/workflows/stocktake-v1-history-799.yml",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/stocktake/hooks/useStocktakeSessions.ts",
    "dashboard/src/pages/inventory/stocktake/StocktakeServerRecovery.test.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeShellLayout.test.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeIdleGate.test.tsx",
})


def stocktake_zero_flash_1026_mode(paths: set[str] | frozenset[str]) -> bool:
    return set(paths) == STOCKTAKE_ZERO_FLASH_1026_FILES


def selftest() -> None:
    manifest = STOCKTAKE_ZERO_FLASH_1026_FILES
    assert len(manifest) == 9
    assert stocktake_zero_flash_1026_mode(manifest)
    for missing in manifest:
        assert not stocktake_zero_flash_1026_mode(manifest - {missing}), missing
    for foreign in (
        "dashboard/src/components/operations/OperationsSidebar.tsx",
        "dashboard/src/pages/inventory/stocktake/StocktakeIdlePanel.tsx",
        "dashboard/src/pages/inventory/Tab4Ledger.tsx",
        "wa_backend/models.py",
        "wanasah_frontend/lib/main.dart",
    ):
        assert not stocktake_zero_flash_1026_mode(manifest | {foreign}), foreign
    assert not stocktake_zero_flash_1026_mode(set())
    print("STOCKTAKE_ZERO_FLASH_1026_SCOPE=PASS")


if __name__ == "__main__":
    selftest()
