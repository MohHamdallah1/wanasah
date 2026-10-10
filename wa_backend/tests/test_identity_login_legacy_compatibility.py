from __future__ import annotations

from types import SimpleNamespace
import unittest

from domains.identity.legacy_compatibility import (
    LegacyLoginCompatibility,
    LegacyLoginCompatibilityMissing,
    load_dashboard_login_compatibility,
    load_field_login_compatibility,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _FakeDB:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.row)


class IdentityLoginLegacyCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def _row(self, *, company_id=7, legacy_driver_id=44, is_admin=True):
        bridge = SimpleNamespace(
            company_id=company_id,
            legacy_driver_id=legacy_driver_id,
            backoffice_user_id=101,
            field_representative_id=202,
        )
        driver = SimpleNamespace(
            id=legacy_driver_id,
            company_id=company_id,
            is_admin=is_admin,
            full_name="Legacy Name",
        )
        return bridge, driver

    async def test_dashboard_resolves_exact_reviewed_legacy_row(self):
        db = _FakeDB(self._row())

        result = await load_dashboard_login_compatibility(
            db,
            company_id=7,
            backoffice_user_id=101,
        )

        self.assertEqual(
            result,
            LegacyLoginCompatibility(
                legacy_driver_id=44,
                legacy_is_admin=True,
                legacy_driver_name="Legacy Name",
            ),
        )
        sql = str(db.statements[0])
        self.assertIn("backoffice_user_id", sql)
        self.assertIn("company_id", sql)

    async def test_field_resolves_exact_reviewed_legacy_row(self):
        db = _FakeDB(self._row(is_admin=False))

        result = await load_field_login_compatibility(
            db,
            company_id=7,
            representative_id=202,
        )

        self.assertEqual(result.legacy_driver_id, 44)
        self.assertFalse(result.legacy_is_admin)
        sql = str(db.statements[0])
        self.assertIn("field_representative_id", sql)

    async def test_missing_bridge_fails_closed(self):
        with self.assertRaises(LegacyLoginCompatibilityMissing):
            await load_dashboard_login_compatibility(
                _FakeDB(None),
                company_id=7,
                backoffice_user_id=101,
            )

    async def test_cross_company_or_mismatched_driver_fails_closed(self):
        bridge, driver = self._row(company_id=7)
        driver.company_id = 8
        with self.assertRaises(LegacyLoginCompatibilityMissing):
            await load_field_login_compatibility(
                _FakeDB((bridge, driver)),
                company_id=7,
                representative_id=202,
            )

        bridge, driver = self._row(company_id=7)
        driver.id = 999
        with self.assertRaises(LegacyLoginCompatibilityMissing):
            await load_field_login_compatibility(
                _FakeDB((bridge, driver)),
                company_id=7,
                representative_id=202,
            )

    async def test_adapter_does_not_use_bridge_classification_as_authority(self):
        bridge, driver = self._row()
        bridge.classification = "DUAL_SPLIT"
        result = await load_dashboard_login_compatibility(
            _FakeDB((bridge, driver)),
            company_id=7,
            backoffice_user_id=101,
        )
        self.assertEqual(result.legacy_driver_id, 44)


if __name__ == "__main__":
    unittest.main()
