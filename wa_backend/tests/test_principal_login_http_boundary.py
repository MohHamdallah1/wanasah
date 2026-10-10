from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from context import tenant_context
from domains.identity.contracts import (
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)
from domains.identity.legacy_compatibility import (
    LegacyLoginCompatibility,
    LegacyLoginCompatibilityMissing,
)
from api.authentication.login import (
    LoginBoundaryRejected,
    LoginCompanyContext,
    build_dashboard_login_response,
    build_field_login_response,
    prepare_login_company,
    require_dashboard_login_compatibility,
    require_field_login_compatibility,
)


class FakeLoginDB:
    def __init__(self, *, company_id: int | None):
        self.company_id = company_id
        self.events: list[tuple] = []

    async def scalar(self, statement):
        self.events.append(("company_lookup", tenant_context.get(), str(statement)))
        return self.company_id

    async def execute(self, statement, params=None):
        self.events.append(("rls_seed", tenant_context.get(), params, str(statement)))
        return object()


class PrincipalLoginHTTPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tenant_context.set(None)
        self.company = LoginCompanyContext(company_id=7, company_code="WNS-01")
        self.dashboard = DashboardAuthenticationResult(
            principal_id=101,
            company_id=7,
            backoffice_user_id=301,
            username="canonical-dashboard",
            full_name="Canonical Dashboard",
            auth_revision=4,
            is_company_owner=True,
        )
        self.field = FieldAuthenticationResult(
            principal_id=102,
            company_id=7,
            representative_id=401,
            username="canonical-field",
            full_name="Canonical Field",
            auth_revision=8,
        )
        self.compatibility = LegacyLoginCompatibility(
            legacy_driver_id=9001,
            legacy_is_admin=False,
            legacy_driver_name="Legacy Driver",
        )

    def tearDown(self):
        tenant_context.set(None)

    async def test_company_inactive_or_not_found_rejected(self):
        db = FakeLoginDB(company_id=None)

        with self.assertRaises(LoginBoundaryRejected):
            await prepare_login_company(db, company_code="MISSING")

        self.assertEqual([event[0] for event in db.events], ["company_lookup"])
        self.assertIsNone(tenant_context.get())

    async def test_tenant_seeded_before_identity_owned_work(self):
        db = FakeLoginDB(company_id=41)

        company = await prepare_login_company(db, company_code="TENANT-41")

        self.assertEqual(company, LoginCompanyContext(41, "TENANT-41"))
        self.assertEqual(db.events[0][0], "company_lookup")
        self.assertIsNone(db.events[0][1])
        self.assertEqual(db.events[1][0], "rls_seed")
        self.assertEqual(db.events[1][1], 41)
        self.assertEqual(db.events[1][2], {"v": "41"})
        self.assertEqual(tenant_context.get(), 41)

    def test_dashboard_canonical_response(self):
        response = build_dashboard_login_response(
            company=self.company,
            authentication=self.dashboard,
            access_token="access-dashboard",
            refresh_token="refresh-dashboard",
            compatibility=self.compatibility,
        )

        self.assertEqual(response["token"], "access-dashboard")
        self.assertEqual(response["refresh_token"], "refresh-dashboard")
        self.assertEqual(response["principal_id"], 101)
        self.assertEqual(response["backoffice_user_id"], 301)
        self.assertEqual(response["channel"], "DASHBOARD")
        self.assertTrue(response["is_company_owner"])
        self.assertEqual(response["company_id"], 7)
        self.assertEqual(response["company_code"], "WNS-01")
        self.assertTrue(response["dashboard_access"])

    def test_field_canonical_response(self):
        response = build_field_login_response(
            company=self.company,
            authentication=self.field,
            access_token="access-field",
            refresh_token="refresh-field",
            compatibility=self.compatibility,
        )

        self.assertEqual(response["token"], "access-field")
        self.assertEqual(response["refresh_token"], "refresh-field")
        self.assertEqual(response["principal_id"], 102)
        self.assertEqual(response["representative_id"], 401)
        self.assertEqual(response["channel"], "FIELD")
        self.assertEqual(response["company_id"], 7)
        self.assertEqual(response["company_code"], "WNS-01")

    def test_exact_legacy_compatibility_ids_preserved(self):
        dashboard = build_dashboard_login_response(
            company=self.company,
            authentication=self.dashboard,
            access_token="a",
            refresh_token="r",
            compatibility=self.compatibility,
        )
        field = build_field_login_response(
            company=self.company,
            authentication=self.field,
            access_token="a",
            refresh_token="r",
            compatibility=self.compatibility,
        )

        self.assertEqual(dashboard["driver_id"], 9001)
        self.assertEqual(field["driver_id"], 9001)
        self.assertEqual(dashboard["driver_name"], "Legacy Driver")
        self.assertEqual(field["driver_name"], "Legacy Driver")

    def test_principal_and_profile_ids_never_substitute_driver_id(self):
        response = build_field_login_response(
            company=self.company,
            authentication=self.field,
            access_token="a",
            refresh_token="r",
            compatibility=LegacyLoginCompatibility(
                legacy_driver_id=9999,
                legacy_is_admin=False,
                legacy_driver_name="Legacy",
            ),
        )

        self.assertEqual(response["driver_id"], 9999)
        self.assertNotEqual(response["driver_id"], response["principal_id"])
        self.assertNotEqual(response["driver_id"], response["representative_id"])

    def test_compatibility_is_admin_cannot_change_canonical_identity(self):
        false_response = build_dashboard_login_response(
            company=self.company,
            authentication=self.dashboard,
            access_token="a",
            refresh_token="r",
            compatibility=LegacyLoginCompatibility(9001, False, "Legacy"),
        )
        true_response = build_dashboard_login_response(
            company=self.company,
            authentication=self.dashboard,
            access_token="a",
            refresh_token="r",
            compatibility=LegacyLoginCompatibility(9001, True, "Legacy"),
        )

        for key in (
            "principal_id",
            "backoffice_user_id",
            "channel",
            "company_id",
            "company_code",
            "is_company_owner",
        ):
            self.assertEqual(false_response[key], true_response[key])
        self.assertFalse(false_response["is_admin"])
        self.assertTrue(true_response["is_admin"])
        self.assertEqual(self.dashboard.principal_type.value, "BACKOFFICE")

    def test_no_credential_material_in_response(self):
        response = build_dashboard_login_response(
            company=self.company,
            authentication=self.dashboard,
            access_token="a",
            refresh_token="r",
            compatibility=self.compatibility,
        )

        self.assertEqual(
            set(response),
            {
                "token",
                "refresh_token",
                "principal_id",
                "backoffice_user_id",
                "channel",
                "is_company_owner",
                "company_id",
                "company_code",
                "driver_id",
                "driver_name",
                "is_admin",
                "dashboard_access",
            },
        )
        self.assertNotIn("username", response)
        self.assertNotIn("password", response)
        self.assertNotIn("password_hash", response)
        self.assertNotIn("full_name", response)

    def test_missing_compatibility_mapping_fails_closed(self):
        with self.assertRaises(LoginBoundaryRejected):
            build_dashboard_login_response(
                company=self.company,
                authentication=self.dashboard,
                access_token="a",
                refresh_token="r",
                compatibility=None,
            )

    async def test_dashboard_compatibility_uses_existing_adapter_only(self):
        db = object()
        expected = LegacyLoginCompatibility(777, True, "Legacy Admin")
        with patch(
            "api.authentication.login.load_dashboard_login_compatibility",
            new=AsyncMock(return_value=expected),
        ) as loader:
            result = await require_dashboard_login_compatibility(
                db,
                company=self.company,
                authentication=self.dashboard,
            )

        self.assertEqual(result, expected)
        loader.assert_awaited_once_with(
            db,
            company_id=7,
            backoffice_user_id=301,
        )

    async def test_compatibility_adapter_missing_mapping_is_rejected(self):
        db = object()
        with patch(
            "api.authentication.login.load_field_login_compatibility",
            new=AsyncMock(side_effect=LegacyLoginCompatibilityMissing),
        ) as loader:
            with self.assertRaises(LoginBoundaryRejected):
                await require_field_login_compatibility(
                    db,
                    company=self.company,
                    authentication=self.field,
                )

        loader.assert_awaited_once_with(
            db,
            company_id=7,
            representative_id=401,
        )


if __name__ == "__main__":
    unittest.main()
