"""M04 #942 final exact owning path set; cross-domain historical CI compat.

This is an exact repository-file list, NEVER a path glob. Previous D06/D07/
F06/Finance/Stocktake/R3/Return-Cost strict historical modes stay enforced.
"""
M04_EXACT = frozenset([
  ".github/scripts/m04_ci_scope.py",
  ".github/workflows/dispatch-m04-vehicle-custody.yml",
  ".github/workflows/dispatch-p0-route-stock-safety.yml",
  ".github/workflows/dispatch-route-launch-d07-acceptance.yml",
  ".github/workflows/dispatch-shop-create-f06-acceptance.yml",
  ".github/workflows/dispatch-shop-finance-p0-acceptance.yml",
  ".github/workflows/live-stock-v1-r3-physical-location-truth.yml",
  ".github/workflows/stocktake-v1-discovered-pg16-ui.yml",
  ".github/workflows/v1-return-cost-fidelity-closure.yml",
  "dashboard/e2e/dispatch-d12-scale.spec.ts",
  "wa_backend/alembic/env.py",
  "wa_backend/alembic/versions/e4b7c9d2a601_m04_multi_vehicle_checkpoint.py",
  "wa_backend/api/dispatch.py",
  "wa_backend/api/representative_settlement.py",
  "wa_backend/api/warehouse/stocktake.py",
  "wa_backend/domains/inventory_vehicle_load/service.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/INTEGRATION.md",
  "wa_backend/domains/representative_settlement_multi_vehicle/__init__.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/activation.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/application.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/checkpoints.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/contracts.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/financial_readiness.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/http.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/inventory_adapter.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/inventory_integration.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/load_ownership.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/models.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/period_pricing.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/policy.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/read_model.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/resolution.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/review_evidence.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/schema.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/snapshots.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/variance.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/variance_http.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/variance_scope.py",
  "wa_backend/domains/representative_settlement_multi_vehicle/variance_workflow.py",
  "wa_backend/models.py",
  "wa_backend/services.py",
  "wa_backend/tests/test_cp14c_stocktake_lifecycle_postgres.py",
  "wa_backend/tests/test_dispatch_m04_commands.py",
  "wa_backend/tests/test_dispatch_m04_domain.py",
  "wa_backend/tests/test_dispatch_m04_financial_domain.py",
  "wa_backend/tests/test_dispatch_m04_full_m03_postgres.py",
  "wa_backend/tests/test_dispatch_m04_inventory_helpers.py",
  "wa_backend/tests/test_dispatch_m04_load_ownership.py",
  "wa_backend/tests/test_dispatch_m04_membership.py",
  "wa_backend/tests/test_dispatch_m04_read_postgres.py",
  "wa_backend/tests/test_dispatch_m04_review_replay.py",
  "wa_backend/tests/test_dispatch_m04_variance_postgres.py",
  "wa_backend/tests/test_dispatch_m04_write_postgres.py",
  "wa_backend/tests/test_live_stock_v1_two_purchase_stocktake_continuous_postgres.py",
  "wa_backend/tests/test_vehicle_reconciliation_strict_custody.py"
])
M04_UNIQUE = frozenset({
    ".github/scripts/m04_ci_scope.py",
    "wa_backend/domains/representative_settlement_multi_vehicle/schema.py",
    "wa_backend/domains/representative_settlement_multi_vehicle/checkpoints.py",
    "wa_backend/tests/test_dispatch_m04_full_m03_postgres.py",
})
assert M04_UNIQUE <= M04_EXACT and len(M04_EXACT) == 55


def m04_mode(candidate):
    files = frozenset(candidate)
    if not files & M04_UNIQUE:
        return False
    assert files == M04_EXACT, (
        f"M04 #942 exact ownership failure "
        f"missing={sorted(M04_EXACT - files)} "
        f"extra={sorted(files - M04_EXACT)}"
    )
    return True


def selftest():
    assert m04_mode(M04_EXACT)
    for missing in sorted(M04_EXACT):
        try:
            m04_mode(M04_EXACT - {missing})
        except AssertionError:
            pass
        else:
            raise AssertionError(f"M04 partial was admitted: {missing}")
    for foreign in (
        "wa_backend/api/driver.py",
        "wa_backend/domains/work_session_multi_route/end.py",
        "dashboard/src/pages/DispatchBoard.tsx",
        "wanasah_frontend/lib/main.dart",
        "wa_backend/domains/inventory/services.py",
    ):
        try:
            m04_mode(M04_EXACT | {foreign})
        except AssertionError:
            pass
        else:
            raise AssertionError(f"M04 foreign was admitted: {foreign}")
    assert not m04_mode({".github/workflows/dispatch-shop-finance-p0-acceptance.yml"})
    print("M04_942_EXACT_SELFTEST=PASS exact=55 missing=55 foreign=5")


if __name__ == "__main__":
    selftest()
