"""Exact Stocktake #1031 public-shell-only signed reentry authorization scope."""
STOCKTAKE_FIRST_PAINT_1031_FILES = frozenset({
    ".github/scripts/stocktake_first_paint_1031_scope.py",
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/stocktake-v1-operator-782.yml",
    ".github/workflows/stocktake-v1-history-799.yml",
    ".github/workflows/stocktake-v1-discovered-pg16-ui.yml",
    "dashboard/src/pages/inventory/MainInventory.tsx",
    "dashboard/src/pages/inventory/Tab3Stocktake.tsx",
    "dashboard/src/pages/inventory/stocktake/StocktakeShellLayout.test.tsx",
    "dashboard/src/test/live-stock-warehouse-discovery.test.tsx",
})

def stocktake_first_paint_1031_mode(paths):
    return set(paths) == STOCKTAKE_FIRST_PAINT_1031_FILES

def selftest():
    scope=STOCKTAKE_FIRST_PAINT_1031_FILES
    assert len(scope) == 9
    assert stocktake_first_paint_1031_mode(scope)
    for missing in scope:
        assert not stocktake_first_paint_1031_mode(scope - {missing}), missing
    for foreign in (
        "dashboard/src/pages/inventory/Tab2Inbound.tsx",
        "dashboard/src/pages/inventory/stocktake/StocktakeIdlePanel.tsx",
        "wa_backend/api/warehouse/stocktake.py",
        "wanasah_frontend/lib/main.dart",
    ):
        assert not stocktake_first_paint_1031_mode(scope | {foreign}), foreign
    assert not stocktake_first_paint_1031_mode(set())
    print("STOCKTAKE_FIRST_PAINT_1031_SCOPE=PASS exact=9 missing=9 foreign=4")

if __name__=="__main__":
    selftest()
