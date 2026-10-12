from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from api import tenant
from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "tenant.py"


class _NoGrantDB:
    def __getattr__(self, name):
        raise AssertionError(f"Tenant identity must not read capability storage: {name}")


class _Result:
    def __init__(self, *, one=None, rows=()):
        self._one = one
        self._rows = list(rows)

    def one_or_none(self):
        return self._one

    def all(self):
        return list(self._rows)


class _TenantDB:
    def __init__(self, *, company, settings=(), country_name=None):
        self.company = company
        self.settings = list(settings)
        self.country_name = country_name
        self.execute_calls = []
        self.scalar_calls = []

    async def execute(self, statement):
        self.execute_calls.append(statement)
        if len(self.execute_calls) == 1:
            return _Result(one=self.company)
        if len(self.execute_calls) == 2:
            return _Result(rows=self.settings)
        raise AssertionError("Unexpected tenant execute call")

    async def scalar(self, statement):
        self.scalar_calls.append(statement)
        return self.country_name


def _company(*, company_id=77, timezone="Asia/Amman"):
    return SimpleNamespace(
        id=company_id,
        name="Wanasah Distribution",
        company_code="WNS-01",
        currency_code="JOD",
        timezone=timezone,
    )


def _access(*, owner: bool, company_id=77):
    subject = BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=company_id,
        is_company_owner=owner,
        legacy_grant_driver_id=None if owner else 909,
    )
    return BackofficeCapabilityAccess(db=_NoGrantDB(), subject=subject)


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TenantIdentityCanonicalAuthCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_owner_receives_tenant_identity(self):
        access = _access(owner=True)
        db = _TenantDB(company=_company())

        response = await tenant.tenant_identity(db=db, access=access)

        self.assertEqual(response["company_id"], 77)
        self.assertEqual(response["company_name"], "Wanasah Distribution")
        self.assertEqual(response["display_location"], "Asia/Amman")

    async def test_ordinary_backoffice_without_business_capability_receives_identity(self):
        access = _access(owner=False)
        db = _TenantDB(company=_company())

        response = await tenant.tenant_identity(db=db, access=access)

        self.assertEqual(response["company_id"], 77)
        self.assertEqual(access.subject.principal_id, 101)
        self.assertEqual(access.subject.backoffice_user_id, 202)
        self.assertEqual(access.subject.legacy_grant_driver_id, 909)
        self.assertEqual(access.company_id, 77)

    async def test_access_company_id_scopes_company_and_system_settings_queries(self):
        access = _access(owner=False, company_id=77)
        db = _TenantDB(
            company=_company(company_id=77),
            settings=[
                (tenant.LOCATION_LABEL_SETTING_KEY, "Amman HQ"),
            ],
        )

        await tenant.tenant_identity(db=db, access=access)

        self.assertEqual(len(db.execute_calls), 2)
        company_sql = _sql(db.execute_calls[0])
        settings_sql = _sql(db.execute_calls[1])
        self.assertIn("companies.id = 77", company_sql)
        self.assertIn("system_settings.company_id = 77", settings_sql)
        self.assertNotIn("= 101", company_sql)
        self.assertNotIn("= 202", company_sql)
        self.assertNotIn("= 909", company_sql)

    async def test_explicit_location_label_has_highest_precedence(self):
        db = _TenantDB(
            company=_company(),
            settings=[
                (tenant.COUNTRY_SETTING_KEY, "10"),
                (tenant.LOCATION_LABEL_SETTING_KEY, "  Amman HQ  "),
            ],
            country_name="Jordan",
        )

        response = await tenant.tenant_identity(db=db, access=_access(owner=False))

        self.assertEqual(response["country_id"], 10)
        self.assertEqual(response["country_name"], "Jordan")
        self.assertEqual(response["display_location"], "Amman HQ")
        self.assertEqual(len(db.scalar_calls), 1)
        self.assertIn("countries.id = 10", _sql(db.scalar_calls[0]))

    async def test_country_name_is_fallback_when_location_label_is_blank(self):
        db = _TenantDB(
            company=_company(),
            settings=[
                (tenant.COUNTRY_SETTING_KEY, "10"),
                (tenant.LOCATION_LABEL_SETTING_KEY, "   "),
            ],
            country_name="Jordan",
        )

        response = await tenant.tenant_identity(db=db, access=_access(owner=True))

        self.assertEqual(response["display_location"], "Jordan")
        self.assertEqual(response["country_id"], 10)
        self.assertEqual(response["country_name"], "Jordan")

    async def test_timezone_is_fallback_when_country_setting_is_invalid(self):
        db = _TenantDB(
            company=_company(timezone="Asia/Amman"),
            settings=[
                (tenant.COUNTRY_SETTING_KEY, "not-an-id"),
                (tenant.LOCATION_LABEL_SETTING_KEY, ""),
            ],
            country_name="must-not-be-read",
        )

        response = await tenant.tenant_identity(db=db, access=_access(owner=False))

        self.assertIsNone(response["country_id"])
        self.assertIsNone(response["country_name"])
        self.assertEqual(response["display_location"], "Asia/Amman")
        self.assertEqual(db.scalar_calls, [])

    async def test_missing_country_row_clears_country_id_and_uses_timezone(self):
        db = _TenantDB(
            company=_company(timezone="Asia/Amman"),
            settings=[
                (tenant.COUNTRY_SETTING_KEY, "10"),
            ],
            country_name=None,
        )

        response = await tenant.tenant_identity(db=db, access=_access(owner=False))

        self.assertIsNone(response["country_id"])
        self.assertIsNone(response["country_name"])
        self.assertEqual(response["display_location"], "Asia/Amman")
        self.assertEqual(len(db.scalar_calls), 1)

    async def test_missing_company_preserves_existing_404_contract(self):
        db = _TenantDB(company=None)

        with self.assertRaises(HTTPException) as caught:
            await tenant.tenant_identity(db=db, access=_access(owner=False))

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, "هوية الشركة غير متاحة.")
        self.assertEqual(len(db.execute_calls), 1)
        self.assertEqual(db.scalar_calls, [])

    def test_invalid_or_non_positive_country_settings_remain_ignored(self):
        invalid = (
            None,
            "",
            "   ",
            "0",
            "-1",
            "+1",
            "abc",
            "1.0",
            "2147483648",
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertIsNone(tenant._positive_setting_id(raw))
        self.assertEqual(tenant._positive_setting_id(" 10 "), 10)
        self.assertEqual(tenant._positive_setting_id("2147483647"), 2147483647)

    def test_route_uses_only_cached_canonical_access_dependency(self):
        params = inspect.signature(tenant.tenant_identity).parameters

        self.assertEqual(set(params), {"db", "access"})
        depends = params["access"].default
        self.assertIs(
            depends.dependency,
            get_current_backoffice_capability_access,
        )
        self.assertTrue(depends.use_cache)
        self.assertEqual(
            str(params["access"].annotation),
            "<class 'domains.authorization.backoffice_access.BackofficeCapabilityAccess'>",
        )

    def test_no_capability_requirement_is_invented(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for forbidden in (
            "require_backoffice_capability",
            "require_backoffice_capabilities",
            "tenant.read",
            "company.read",
            "location.read",
            ".require(",
            ".require_all(",
            ".allows(",
            ".location_filter(",
        ):
            self.assertNotIn(forbidden, source)

        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "tenant_identity"
        )
        access_calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "access"
        ]
        self.assertEqual(access_calls, [])

    def test_source_has_zero_legacy_driver_request_identity_or_admin_authority(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "get_current_backoffice_legacy_driver",
            "InventoryAccess",
            "Driver",
            ".is_admin",
            "actor.company_id",
            "current_driver.company_id",
            "legacy_actor.company_id",
        ):
            self.assertNotIn(forbidden, source)

        for identity_name in (
            "principal_id",
            "backoffice_user_id",
            "legacy_driver_id",
            "legacy_grant_driver_id",
        ):
            self.assertNotIn(identity_name, source)

    def test_route_schema_constants_and_read_only_shape_are_preserved(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "tenant_identity"
        )

        self.assertIn(
            '@router.get("/identity", response_model=TenantIdentityResponse, status_code=200)',
            source,
        )
        self.assertEqual(tenant.COUNTRY_SETTING_KEY, "company_country_id")
        self.assertEqual(
            tenant.LOCATION_LABEL_SETTING_KEY,
            "company_location_label",
        )
        self.assertEqual(
            set(tenant.TenantIdentityResponse.model_fields),
            {
                "company_id",
                "company_name",
                "company_code",
                "currency_code",
                "timezone",
                "country_id",
                "country_name",
                "display_location",
            },
        )
        called_names = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertEqual(called_names & {"select"}, {"select"})
        self.assertFalse(called_names & {"insert", "update", "delete"})
        function_source = ast.unparse(function)
        self.assertNotIn("commit", function_source)
        self.assertNotIn("rollback", function_source)
        self.assertNotIn("flush", function_source)


if __name__ == "__main__":
    unittest.main()
