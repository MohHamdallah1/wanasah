from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest


GUARD_PATH = Path(__file__).resolve().parents[1] / "legacy_admin_authorization_guard.py"
SPEC = importlib.util.spec_from_file_location("legacy_admin_authorization_guard", GUARD_PATH)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


class LegacyAdminAuthorizationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def codes(self):
        return [item.code for item in guard.scan_repository(self.root).violations]

    def test_allows_canonical_owner_capability_and_separate_platform_realm(self):
        self.write(
            "wa_backend/api/example.py",
            """
async def read(access):
    if access.subject.is_company_owner:
        return await access.require("inventory.read")
    return await access.require("inventory.read", location_id=7)
""",
        )
        self.write(
            "dashboard/src/example.tsx",
            """
const canRead = access.isCompanyOwner || access.can("inventory.read");
const platformRole = "PlatformAdmin";
""",
        )
        self.write(
            "wanasah_frontend/lib/example.dart",
            """
bool sameFieldChannel(Map<String, dynamic> value) =>
  value['principal_type'] == 'FIELD_REPRESENTATIVE';
""",
        )

        report = guard.scan_repository(self.root)
        self.assertEqual(report.violations, ())
        self.assertEqual(report.scanned_by_surface["backend_and_workers"], 1)
        self.assertEqual(report.scanned_by_surface["dashboard"], 1)
        self.assertEqual(report.scanned_by_surface["flutter"], 1)

    def test_permits_only_explicit_historical_test_migration_and_archive_exclusions(self):
        self.write(
            "wa_backend/alembic/versions/0001_history.py",
            "def downgrade(driver):\n    driver.is_admin = False\n",
        )
        self.write(
            "wa_backend/tests/test_history.py",
            "def test_old_flag(driver):\n    assert driver.is_admin is False\n",
        )
        self.write(
            "wa_backend/perf_reports/phase1_baseline/schema.py",
            "is_admin: bool = False\n",
        )
        self.write(
            "dashboard/src/test/history.test.ts",
            "expect({ isAdmin: false }.isAdmin).toBe(false);\n",
        )

        report = guard.scan_repository(self.root)
        self.assertEqual(report.violations, ())
        self.assertEqual(len(report.excluded_by_reason["alembic_history"]), 1)
        self.assertEqual(len(report.excluded_by_reason["backend_tests"]), 1)
        self.assertEqual(len(report.excluded_by_reason["archived_perf_evidence"]), 1)
        self.assertEqual(len(report.excluded_by_reason["dashboard_tests"]), 1)

    def test_rejects_backend_driver_flag_authority(self):
        self.write(
            "wa_backend/api/orders.py",
            """
def can_edit(driver):
    if driver.is_admin:
        return True
    return False
""",
        )
        report = guard.scan_repository(self.root)
        self.assertIn("LEGACY_FLAG_ATTRIBUTE", [item.code for item in report.violations])
        self.assertTrue(any(item.detail == "is_admin" for item in report.violations))

    def test_rejects_replacement_manager_owner_and_superuser_flags(self):
        samples = {
            "wa_backend/workers/tasks/job.py": "def run(actor):\n    return actor.is_manager\n",
            "dashboard/src/Page.tsx": "const allowed = user.isOwner;\n",
            "wanasah_frontend/lib/page.dart": "final allowed = identity['is_superuser'] == true;\n",
        }
        for path, source in samples.items():
            with self.subTest(path=path):
                nested = self.root / path
                nested.parent.mkdir(parents=True, exist_ok=True)
                nested.write_text(source, encoding="utf-8")

        report = guard.scan_repository(self.root)
        details = {item.detail for item in report.violations}
        self.assertTrue({"is_manager", "isOwner", "is_superuser"}.issubset(details))

    def test_rejects_bare_generic_persona_booleans(self):
        samples = {
            "wa_backend/api/example.py": "admin: bool = False\n",
            "dashboard/src/example.ts": "const manager = true;\n",
            "wanasah_frontend/lib/example.dart": "final owner = false;\n",
        }
        for path, source in samples.items():
            self.write(path, source)

        report = guard.scan_repository(self.root)
        matches = [
            item for item in report.violations
            if item.code == "GENERIC_PERSONA_BOOLEAN"
        ]
        self.assertEqual(
            {item.detail for item in matches},
            {"admin", "manager", "owner"},
        )

    def test_rejects_generic_role_name_as_permission_authority(self):
        self.write(
            "wa_backend/api/example.py",
            """
def allowed(user):
    return user.role == "Admin"
""",
        )
        self.write(
            "dashboard/src/example.ts",
            "const allowed = account.role === 'Manager';\n",
        )
        report = guard.scan_repository(self.root)
        matches = [
            item for item in report.violations
            if item.code == "GENERIC_ROLE_PERSONA_AUTHORITY"
        ]
        self.assertEqual({item.detail for item in matches}, {"admin", "manager"})

    def test_comments_do_not_create_false_positive_but_string_contract_does(self):
        self.write(
            "dashboard/src/comment.ts",
            "// Never reintroduce isAdmin here.\nconst ok = access.can('catalog.read');\n",
        )
        self.assertEqual(guard.scan_repository(self.root).violations, ())

        self.write(
            "dashboard/src/contract.ts",
            "const legacyKey = 'is_admin';\n",
        )
        report = guard.scan_repository(self.root)
        self.assertTrue(any(item.detail == "is_admin" for item in report.violations))

    def test_retired_get_current_admin_must_stay_fail_closed(self):
        self.write(
            "wa_backend/api/dependencies.py",
            """
def _retired_dependency():
    return PermissionError()

async def get_current_admin():
    raise _retired_dependency()
""",
        )
        self.assertEqual(guard.scan_repository(self.root).violations, ())

        self.write(
            "wa_backend/api/dependencies.py",
            """
async def get_current_admin():
    return object()
""",
        )
        report = guard.scan_repository(self.root)
        self.assertTrue(
            any(
                item.code == "RETIRED_ADMIN_DEPENDENCY_REACTIVATED"
                for item in report.violations
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
