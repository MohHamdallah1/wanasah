"""Exact C01/C02/C03+X01 MAIN-target PR #983 release ownership.

Do not admit partial, foreign, or unrelated PR changes. The 51 production,
test and evidence paths were fixed from independently reviewed integration
tree de8a0515 versus exact merged MAIN d49631fa; five CI gates follow.
"""
import sys
import subprocess

RELEASE_FILES = frozenset({
    '.github/scripts/dispatch_c03_x01_release_scope.py',
    '.github/workflows/dispatch-p0-route-stock-safety.yml',
    '.github/workflows/dispatch-route-launch-d07-acceptance.yml',
    '.github/workflows/dispatch-x01-c03-release-acceptance.yml',
    '.github/workflows/live-stock-inflight-authority-acceptance.yml',
    'dashboard/e2e/dispatch-c03-final-real-browser.cjs',
    'dashboard/src/features/dispatch/custodyRecovery/VehicleCustodyRecoveryEntry.tsx',
    'dashboard/src/features/dispatch/custodyRecovery/VehicleCustodyRecoveryPanel.tsx',
    'dashboard/src/features/dispatch/custodyRecovery/command.ts',
    'dashboard/src/features/dispatch/custodyRecovery/contract.ts',
    'dashboard/src/features/dispatch/custodyRecovery/copy.ts',
    'dashboard/src/features/dispatch/launchResources/LaunchResourceSelect.tsx',
    'dashboard/src/features/dispatch/launchResources/launchResourceRead.ts',
    'dashboard/src/features/dispatch/launchResources/launchResourceReasons.ts',
    'dashboard/src/pages/DispatchBoard.tsx',
    'dashboard/src/test/dispatch-c03-command.test.ts',
    'dashboard/src/test/dispatch-c03-entry.test.tsx',
    'dashboard/src/test/dispatch-c03-final-blocked-selector.test.tsx',
    'dashboard/tsconfig.c03-final.json',
    'dashboard/tsconfig.c03.json',
    'docs/evidence/dispatch-c03-final-977/README.md',
    'docs/evidence/dispatch-c03-final-977/ar-1440-after.png',
    'docs/evidence/dispatch-c03-final-977/ar-1440-before.png',
    'docs/evidence/dispatch-c03-final-977/ar-390-after.png',
    'docs/evidence/dispatch-c03-final-977/ar-390-before.png',
    'docs/evidence/dispatch-c03-final-977/en-1440-after.png',
    'docs/evidence/dispatch-c03-final-977/en-1440-before.png',
    'docs/evidence/dispatch-c03-final-977/en-390-after.png',
    'docs/evidence/dispatch-c03-final-977/en-390-before.png',
    'docs/evidence/dispatch-x01-m06-980/INTEGRATION_GAPS.md',
    'docs/evidence/dispatch-x01-m06-980/OWNER_VISUAL_ACCEPTANCE.md',
    'wa_backend/api/vehicles/__init__.py',
    'wa_backend/api/vehicles/custody.py',
    'wa_backend/api/vehicles/custody_review.py',
    'wa_backend/domains/dispatch/route_execution/custody/__init__.py',
    'wa_backend/domains/dispatch/route_execution/custody/access.py',
    'wa_backend/domains/dispatch/route_execution/custody/proofs.py',
    'wa_backend/domains/dispatch/route_execution/custody/service.py',
    'wa_backend/domains/dispatch/route_execution/custody/snapshot.py',
    'wa_backend/domains/dispatch/route_execution/readiness/custody_codes.py',
    'wa_backend/domains/dispatch/route_execution/readiness/launch_resources.py',
    'wa_backend/tests/c02_signed_custody_real_http.py',
    'wa_backend/tests/test_dispatch_c01_c02_custody_postgres.py',
    'wa_backend/tests/test_dispatch_c01_c02_negative_postgres.py',
    'wa_backend/tests/test_dispatch_c03_final_browser_seed_postgres.py',
    'wa_backend/tests/test_dispatch_c03_real_two_actor_postgres.py',
    'wa_backend/tests/test_dispatch_d08_journey_postgres.py',
    'wa_backend/tests/test_dispatch_m05_launch_availability_postgres.py',
    'wa_backend/tests/test_dispatch_x01_custody_uom_m06_bridge_postgres.py',
    'wa_backend/tests/test_field_authorization_phase3_routes.py',
    'wanasah_frontend/lib/features/custody/recovery/custody_handoff_client.dart',
    'wanasah_frontend/lib/features/custody/recovery/custody_handoff_screen.dart',
    'wanasah_frontend/lib/features/custody/recovery/custody_handoff_strings.dart',
    'wanasah_frontend/lib/screens/dashboard_screen.dart',
    'wanasah_frontend/test/app/field_shell_composition_test.dart',
    'wanasah_frontend/test/features/custody/custody_handoff_screen_test.dart',
})

# X02 includes accepted ports and the focused D10 locale-test parity correction
# on the immutable 56-file #983 release. No incomplete/foreign diff is valid.
D22_FILES = frozenset({
    'dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx',
    'dashboard/src/features/dispatch/stableUi/dispatchChromeCopy.ts',
    'dashboard/src/test/dispatch-d22-chrome-i18n.test.tsx',
})
M06_FILES = frozenset({
    '.github/workflows/dispatch-m06-owner-acceptance.yml',
    'dashboard/e2e/dispatch-m06-owner-visual.config.ts',
    'dashboard/e2e/dispatch-m06-owner-visual.spec.ts',
    'docs/operations/DISPATCH_M06_OWNER_ACCEPTANCE_MATRIX.md',
    'wa_backend/tests/m06_owner_settlement_gate.py',
    'wa_backend/tests/test_dispatch_m06_owner_acceptance_postgres.py',
    'wanasah_frontend/test/features/work_session/m06_full_day_execution_proof_test.dart',
})
D10_LOCALE_TEST_FILES = frozenset({
    'dashboard/src/test/auth-session-consumer-isolation.test.tsx',
})
UNIFIED_RELEASE_FILES = RELEASE_FILES | D22_FILES | M06_FILES | D10_LOCALE_TEST_FILES


def unified_release_mode(paths):
    return set(paths) == UNIFIED_RELEASE_FILES


def release_mode(paths):
    actual = set(paths)
    return actual == RELEASE_FILES or unified_release_mode(actual)


def assert_release(paths):
    actual = set(paths)
    if actual == RELEASE_FILES:
        return "C03_X01_983_RELEASE_EXACT"
    if unified_release_mode(actual):
        return "C03_X01_X02_UNIFIED_EXACT"
    raise AssertionError(
        "C03_X01_X02_RELEASE_EXACT rejected "
        f"original_missing={sorted(RELEASE_FILES-actual)} "
        f"unified_missing={sorted(UNIFIED_RELEASE_FILES-actual)} "
        f"unified_foreign={sorted(actual-UNIFIED_RELEASE_FILES)}"
    )


def selftest():
    assert len(RELEASE_FILES) == 56, len(RELEASE_FILES)
    assert len(D22_FILES) == 3 and len(M06_FILES) == 7 and len(D10_LOCALE_TEST_FILES) == 1
    assert not (RELEASE_FILES & D22_FILES)
    assert not (RELEASE_FILES & M06_FILES)
    assert not (D22_FILES & M06_FILES)
    assert not ((RELEASE_FILES | D22_FILES | M06_FILES) & D10_LOCALE_TEST_FILES)
    assert len(UNIFIED_RELEASE_FILES) == 67

    def deny(paths):
        assert not release_mode(paths), sorted(paths)
        try:
            assert_release(paths)
        except AssertionError:
            return
        raise AssertionError("Incomplete or foreign release scope accepted")

    assert assert_release(RELEASE_FILES) == "C03_X01_983_RELEASE_EXACT"
    assert assert_release(UNIFIED_RELEASE_FILES) == "C03_X01_X02_UNIFIED_EXACT"
    for allowed in (RELEASE_FILES, UNIFIED_RELEASE_FILES):
        assert release_mode(allowed)
        for missing in allowed:
            deny(allowed - {missing})
        for foreign in (
            "wa_backend/api/dispatch.py", "wa_backend/models.py",
            "dashboard/src/App.tsx", "wanasah_frontend/lib/main.dart",
        ):
            assert foreign not in UNIFIED_RELEASE_FILES
            deny(allowed | {foreign})
    # Neither accepted upstream PR, nor either incomplete release, can
    # masquerade as the 67-file union; 56 and 7 remain separate exact modes.
    for partial in (
        D22_FILES, M06_FILES, D22_FILES | M06_FILES,
        RELEASE_FILES | D22_FILES, RELEASE_FILES | M06_FILES,
        RELEASE_FILES | D22_FILES | M06_FILES,
    ):
        deny(partial)
    print("C03_X01_X02_RELEASE_SCOPE_SELFTEST=PASS "
          "original=56 unified=67 missing=123 foreign=8 partial=6")

if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] == "--selftest"
    selftest()
