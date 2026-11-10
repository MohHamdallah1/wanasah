"""D06 #889 owner-approved exact cross-owner acceptance for Shop privacy.

The only admitted crossover is this ONE complete D06 patch. Existing D07/F06,
D09/D10 and Live Stock ownership contracts remain unchanged for other PRs.
Partial D06 or a foreign path fails closed, even if common Dispatch files appear.
"""
D06_EXACT = frozenset({
    ".github/scripts/dispatch_d06_ci_scope.py",
    ".github/scripts/live_stock_ci_ownership.py",
    ".github/workflows/dispatch-d06-shop-privacy.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
    ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
    ".github/workflows/dispatch-shop-create-f06-acceptance.yml",
    ".github/workflows/dispatch-shop-finance-p0-acceptance.yml",
    ".github/workflows/live-stock-inflight-authority-acceptance.yml",
    "dashboard/src/components/dispatch/ShopTable.tsx",
    "dashboard/src/features/dispatch/dispatchUiText.ts",
    "dashboard/src/features/dispatch/shopForm/contract.ts",
    "dashboard/src/pages/DispatchBoard.tsx",
    "dashboard/src/test/dispatch-d06-shop-financial-redaction.test.tsx",
    "dashboard/src/test/dispatch-d13-accessibility.test.tsx",
    "dashboard/src/test/dispatch-shop-metadata-finance-v1.test.tsx",
    "dashboard/src/types/dispatch.ts",
    "wa_backend/alembic/versions/f6c2a7d4e890_d06_shop_financial_read.py",
    "wa_backend/api/dispatch.py",
    "wa_backend/domains/authorization/capabilities.py",
    "wa_backend/domains/dispatch_shop_read_scope.py",
    "wa_backend/schemas.py",
    "wa_backend/tests/test_dispatch_d06_secure_shop_reads_postgres.py",
    "wa_backend/tests/test_field_authorization_phase1_postgres.py",
})
D06_NEW = frozenset({
    ".github/workflows/dispatch-d06-shop-privacy.yml",
    ".github/scripts/dispatch_d06_ci_scope.py",
    "wa_backend/domains/dispatch_shop_read_scope.py",
    "wa_backend/tests/test_dispatch_d06_secure_shop_reads_postgres.py",
})
assert len(D06_EXACT) == 23 and D06_NEW <= D06_EXACT


def d06_mode(candidate):
    """True only for exact D06; a partial/mixed D06 fails without bypass."""
    changed = frozenset(candidate)
    if changed == D06_EXACT:
        return True
    if changed & D06_NEW:
        raise AssertionError(
            "D06_EXACT_SCOPE_DENIED missing="
            + str(sorted(D06_EXACT - changed))
            + " extra=" + str(sorted(changed - D06_EXACT))
        )
    return False


def selftest():
    assert d06_mode(D06_EXACT)
    for missing in D06_EXACT:
        try:
            d06_mode(D06_EXACT - {missing})
        except AssertionError:
            pass
        else:
            raise AssertionError("D06 missing file admitted: " + missing)
    for extra in (
        "wa_backend/api/driver.py", "wa_backend/models.py",
        "wanasah_frontend/lib/main.dart", "dashboard/src/lib/authStorage.ts",
    ):
        try:
            d06_mode(D06_EXACT | {extra})
        except AssertionError:
            pass
        else:
            raise AssertionError("D06 unrelated path admitted: " + extra)
    print("D06_EXACT_SCOPE_SELFTEST=PASS files=" + str(len(D06_EXACT)))


if __name__ == "__main__":
    selftest()
