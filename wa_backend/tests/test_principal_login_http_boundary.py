from __future__ import annotations

from dataclasses import replace
import inspect
import unittest

from context import tenant_context
from domains.identity.contracts import (
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)
from api.authentication.login import (
    LoginBoundaryRejected,
    LoginCompanyContext,
    build_dashboard_login_response,
    build_field_login_response,
    prepare_login_company,
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
        )

        self.assertEqual(response["token"], "access-field")
        self.assertEqual(response["refresh_token"], "refresh-field")
        self.assertEqual(response["principal_id"], 102)
        self.assertEqual(response["representative_id"], 401)
        self.assertEqual(response["channel"], "FIELD")
        self.assertEqual(response["company_id"], 7)
        self.assertEqual(response["company_code"], "WNS-01")

    def test_both_responses_have_no_legacy_identity_or_authority_fields(self):
        for builder, identity in ((build_dashboard_login_response, self.dashboard),
                                  (build_field_login_response, self.field)):
            with self.subTest(channel=identity.channel):
                response = builder(company=self.company, authentication=identity,
                                   access_token="a", refresh_token="r")
                self.assertTrue({"driver_id", "driver_name", "is_admin", "legacy_is_admin"}.isdisjoint(response))

    def test_principal_and_profile_ids_remain_independent(self):
        dashboard = build_dashboard_login_response(
            company=self.company, authentication=self.dashboard,
            access_token="a", refresh_token="r",
        )
        field = build_field_login_response(
            company=self.company, authentication=self.field,
            access_token="a", refresh_token="r",
        )
        self.assertEqual((dashboard["principal_id"], dashboard["backoffice_user_id"]), (101, 301))
        self.assertEqual((field["principal_id"], field["representative_id"]), (102, 401))

    def test_company_owner_is_explicit_canonical_state(self):
        for owner in (False, True):
            identity = replace(self.dashboard, is_company_owner=owner)
            response = build_dashboard_login_response(
                company=self.company, authentication=identity,
                access_token="a", refresh_token="r",
            )
            self.assertIs(response["is_company_owner"], owner)
            self.assertEqual(response["principal_id"], 101)
            self.assertEqual(response["backoffice_user_id"], 301)
            self.assertTrue(response["dashboard_access"])

    def test_no_credential_material_in_response(self):
        response = build_dashboard_login_response(
            company=self.company,
            authentication=self.dashboard,
            access_token="a",
            refresh_token="r",
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
                "dashboard_access",
            },
        )
        self.assertNotIn("username", response)
        self.assertNotIn("password", response)
        self.assertNotIn("password_hash", response)
        self.assertNotIn("full_name", response)

    def test_builders_have_no_compatibility_argument(self):
        for builder in (build_dashboard_login_response, build_field_login_response):
            self.assertEqual(set(inspect.signature(builder).parameters),
                             {"company", "authentication", "access_token", "refresh_token"})
            with self.assertRaises(TypeError):
                builder(company=self.company, authentication=self.dashboard,
                        access_token="a", refresh_token="r", compatibility=None)

    def test_cross_company_authentication_fails_closed_for_both_builders(self):
        for builder, identity in ((build_dashboard_login_response, self.dashboard),
                                  (build_field_login_response, self.field)):
            with self.subTest(channel=identity.channel), self.assertRaises(LoginBoundaryRejected):
                builder(company=self.company, authentication=replace(identity, company_id=8),
                        access_token="a", refresh_token="r")

    async def test_company_seed_failure_restores_tenant_context(self):
        class FailingDB(FakeLoginDB):
            async def execute(self, statement, params=None):
                raise RuntimeError("synthetic RLS seed failure")

        with self.assertRaises(LoginBoundaryRejected):
            await prepare_login_company(FailingDB(company_id=41), company_code="TENANT-41")
        self.assertIsNone(tenant_context.get())


if __name__ == "__main__":
    unittest.main()
