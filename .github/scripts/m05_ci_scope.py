"""M05 #945 exact file ownership, additive historical-CI compatibility.

Old D06/D07/F06/Finance/Stocktake/LiveStock and M04 checks are untouched.
Only this literal M05 file set is accepted. No directory prefix or wildcard.
"""

M05_EXACT = frozenset({
    '.github/scripts/m05_ci_scope.py',
    '.github/scripts/live_stock_ci_ownership.py',
    '.github/workflows/dispatch-m05-readiness-pg16.yml',
    '.github/workflows/dispatch-m05-ui-contract.yml',
    '.github/workflows/dispatch-p0-route-stock-safety.yml',
    '.github/workflows/dispatch-route-launch-d07-acceptance.yml',
    '.github/workflows/dispatch-shop-create-f06-acceptance.yml',
    '.github/workflows/dispatch-shop-finance-p0-acceptance.yml',
    '.github/workflows/live-stock-inflight-authority-acceptance.yml',
    'dashboard/e2e/dispatch-d08-journey.spec.ts',
    'dashboard/e2e/dispatch-d12-scale.spec.ts',
    'dashboard/src/components/dispatch/PendingRoutesTable.tsx',
    'dashboard/src/components/dispatch/PostponedRoutesModal.tsx',
    'dashboard/src/features/dispatch/routeLifecycle/RouteLifecyclePanel.tsx',
    'dashboard/src/features/dispatch/routeLifecycle/command.ts',
    'dashboard/src/features/dispatch/routeLifecycle/contract.ts',
    'dashboard/src/features/dispatch/routeLifecycle/copy.ts',
    'dashboard/src/features/operations/representativeSettlement/RepresentativeSettlementJourney.tsx',
    'dashboard/src/features/operations/representativeSettlement/SignedMultiVehicleCustodyJourney.tsx',
    'dashboard/src/features/operations/representativeSettlement/VehicleCountReadPanel.tsx',
    'dashboard/src/features/operations/representativeSettlement/VehicleVariancePanel.tsx',
    'dashboard/src/features/operations/representativeSettlement/vehicleCountCommand.ts',
    'dashboard/src/features/operations/representativeSettlement/vehicleCountRead.ts',
    'dashboard/src/features/operations/representativeSettlement/vehicleResponsibilityRead.ts',
    'dashboard/src/pages/DispatchBoard.tsx',
    'dashboard/src/test/dispatch-m05-command.test.ts',
    'dashboard/src/test/dispatch-m05-lifecycle.test.ts',
    'dashboard/src/test/dispatch-m05-m04-count.test.tsx',
    'dashboard/src/test/dispatch-m05-panel.test.tsx',
    'dashboard/src/test/dispatch-m05-vehicle-responsibilities.test.ts',
    'dashboard/src/types/dispatch.ts',
    'dashboard/tsconfig.m05.json',
    'wa_backend/api/dispatch.py',
    'wa_backend/domains/dispatch/route_execution/readiness/current_periods.py',
    'wa_backend/domains/dispatch/route_execution/readiness/probe.py',
    'wa_backend/schemas.py',
    'wa_backend/tests/test_dispatch_m05_reads_postgres.py',
    'wanasah_frontend/lib/blocs/visit/visit_bloc.dart',
    'wanasah_frontend/lib/features/visits/application/visit_submission_service.dart',
    'wanasah_frontend/lib/features/visits/data/local_visit_replay_adapter.dart',
    'wanasah_frontend/lib/features/visits/data/signed_visit_execution_reader.dart',
    'wanasah_frontend/lib/features/work_session/data/execution_context.dart',
    'wanasah_frontend/lib/features/work_session/data/field_execution_reader.dart',
    'wanasah_frontend/lib/features/work_session/data/signed_field_execution_authority.dart',
    'wanasah_frontend/lib/features/work_session/data/work_session_remote_data_source.dart',
    'wanasah_frontend/test/features/visits/data/visit_replay_adapter_test.dart',
    'wanasah_frontend/test/features/work_session/execution_context_proof_test.dart',
    'wanasah_frontend/test/features/work_session/signed_field_execution_authority_test.dart',
})

M05_UNIQUE = frozenset({
    ".github/scripts/m05_ci_scope.py",
    "dashboard/src/features/operations/representativeSettlement/SignedMultiVehicleCustodyJourney.tsx",
})
assert M05_UNIQUE <= M05_EXACT

def m05_mode(candidate):
    files = frozenset(candidate)
    if not files & M05_UNIQUE:
        return False
    assert files == M05_EXACT, (
        f"M05 #945 exact owner mismatch missing={sorted(M05_EXACT - files)} "
        f"extra={sorted(files - M05_EXACT)}"
    )
    return True

def selftest():
    assert m05_mode(M05_EXACT)
    for missing in M05_EXACT:
        try:
            m05_mode(M05_EXACT - {missing})
        except AssertionError:
            pass
        else:
            raise AssertionError(f"M05 partial accepted: {missing}")
    for foreign in (
        "wa_backend/domains/inventory/services.py",
        "wa_backend/domains/work_session_multi_route/end.py",
        "wa_backend/domains/representative_settlement_multi_vehicle/http.py",
        "dashboard/src/lib/authStorage.ts",
        "wanasah_frontend/lib/main.dart",
    ):
        try:
            m05_mode(M05_EXACT | {foreign})
        except AssertionError:
            pass
        else:
            raise AssertionError(f"M05 foreign accepted: {foreign}")
    from pathlib import Path
    from runpy import run_path
    assert not m05_mode({"dashboard/src/pages/DispatchBoard.tsx"})
    m04 = run_path(str(Path(__file__).with_name("m04_ci_scope.py")))
    assert m04["m04_mode"](m04["M04_EXACT"])
    assert not m05_mode(m04["M04_EXACT"])
    print(f"M05_EXACT_SCOPE_SELFTEST=PASS exact={len(M05_EXACT)} missing={len(M05_EXACT)} foreign=5 M04=RETAINED")

if __name__ == "__main__":
    selftest()
