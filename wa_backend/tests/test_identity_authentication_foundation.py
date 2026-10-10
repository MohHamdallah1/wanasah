from types import SimpleNamespace
import unittest

import bcrypt

from domains.identity.authentication import authenticate_identity, verify_existing_password
from domains.identity.channels import IdentityChannel
from domains.identity.contracts import (
    AuthenticationRejected,
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)
from domains.identity.models import BackofficeUser, CompanyOwner, CompanyPrincipal, FieldRepresentative
from domains.identity.repository import (
    IdentityRecordNotFound,
    load_active_principal_by_username,
    load_company_owner,
    load_principal_by_id,
    require_active_company,
    require_backoffice_profile,
    require_field_representative_profile,
)
from models import Company


class ScalarSession:
    def __init__(self, values=None):
        self.values = values or {}
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        return self.values.get(entity)


class IdentityRepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_repository_queries_always_include_tenant_predicate(self):
        db = ScalarSession()

        with self.assertRaises(IdentityRecordNotFound):
            await require_active_company(db, 7)
        active_company_sql = str(db.statements[-1])
        self.assertIn("companies.id", active_company_sql)
        self.assertIn("companies.is_active", active_company_sql)

        await load_active_principal_by_username(db, company_id=7, username="user")
        principal_sql = str(db.statements[-1])
        self.assertIn("company_principals.company_id", principal_sql)
        self.assertIn("company_principals.username", principal_sql)
        self.assertIn("company_principals.is_active", principal_sql)

        await load_principal_by_id(db, company_id=7, principal_id=11)
        principal_id_sql = str(db.statements[-1])
        self.assertIn("company_principals.company_id", principal_id_sql)
        self.assertIn("company_principals.id", principal_id_sql)

        with self.assertRaises(IdentityRecordNotFound):
            await require_backoffice_profile(db, company_id=7, principal_id=11)
        backoffice_sql = str(db.statements[-1])
        self.assertIn("backoffice_users.company_id", backoffice_sql)
        self.assertIn("backoffice_users.principal_id", backoffice_sql)
        self.assertIn("backoffice_users.principal_type", backoffice_sql)

        with self.assertRaises(IdentityRecordNotFound):
            await require_field_representative_profile(db, company_id=7, principal_id=11)
        field_sql = str(db.statements[-1])
        self.assertIn("field_representatives.company_id", field_sql)
        self.assertIn("field_representatives.principal_id", field_sql)
        self.assertIn("field_representatives.principal_type", field_sql)

        await load_company_owner(db, company_id=7)
        owner_sql = str(db.statements[-1])
        self.assertIn("company_owners.company_id", owner_sql)


class IdentityAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "correct-password"
        cls.password_hash = bcrypt.hashpw(
            cls.password.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")

    def dashboard_db(self, *, principal=True, profile=True, owner=True, company=True):
        values = {
            Company: SimpleNamespace(id=1, is_active=True) if company else None,
            CompanyPrincipal: (
                SimpleNamespace(
                    id=10,
                    company_id=1,
                    username="owner",
                    password_hash=self.password_hash,
                    full_name="Owner User",
                    principal_type="BACKOFFICE",
                    is_active=True,
                    auth_revision=3,
                )
                if principal else None
            ),
            BackofficeUser: SimpleNamespace(id=20, company_id=1, principal_id=10) if profile else None,
            CompanyOwner: SimpleNamespace(company_id=1, backoffice_user_id=20) if owner else None,
        }
        return ScalarSession(values)

    def field_db(self, *, profile=True):
        return ScalarSession({
            Company: SimpleNamespace(id=1, is_active=True),
            CompanyPrincipal: SimpleNamespace(
                id=11,
                company_id=1,
                username="rep",
                password_hash=self.password_hash,
                full_name="Field Rep",
                principal_type="FIELD_REPRESENTATIVE",
                is_active=True,
                auth_revision=2,
            ),
            FieldRepresentative: SimpleNamespace(id=31, company_id=1, principal_id=11) if profile else None,
        })

    async def test_existing_bcrypt_hash_verification(self):
        self.assertTrue(await verify_existing_password(self.password, self.password_hash))
        self.assertFalse(await verify_existing_password("wrong", self.password_hash))

    async def test_dashboard_requires_backoffice_profile_and_returns_owner_state(self):
        result = await authenticate_identity(
            self.dashboard_db(), company_id=1, username="owner",
            password=self.password, channel=IdentityChannel.DASHBOARD,
        )
        self.assertIsInstance(result, DashboardAuthenticationResult)
        self.assertEqual(result.principal_id, 10)
        self.assertEqual(result.backoffice_user_id, 20)
        self.assertTrue(result.is_company_owner)
        self.assertFalse(hasattr(result, "password_hash"))

    async def test_field_requires_field_profile_and_keeps_profile_id_distinct(self):
        result = await authenticate_identity(
            self.field_db(), company_id=1, username="rep",
            password=self.password, channel=IdentityChannel.FIELD,
        )
        self.assertIsInstance(result, FieldAuthenticationResult)
        self.assertEqual(result.principal_id, 11)
        self.assertEqual(result.representative_id, 31)
        self.assertNotEqual(result.principal_id, result.representative_id)
        self.assertFalse(hasattr(result, "password_hash"))

    async def test_wrong_channel_fails_closed_without_role_inference(self):
        with self.assertRaises(AuthenticationRejected):
            await authenticate_identity(
                self.field_db(), company_id=1, username="rep",
                password=self.password, channel=IdentityChannel.DASHBOARD,
            )

    async def test_missing_profile_fails_closed(self):
        with self.assertRaises(AuthenticationRejected):
            await authenticate_identity(
                self.dashboard_db(profile=False), company_id=1, username="owner",
                password=self.password, channel=IdentityChannel.DASHBOARD,
            )

    async def test_inactive_or_unknown_principal_and_bad_password_fail_closed(self):
        for db, password in (
            (self.dashboard_db(principal=False), self.password),
            (self.dashboard_db(), "wrong-password"),
        ):
            with self.assertRaises(AuthenticationRejected):
                await authenticate_identity(
                    db, company_id=1, username="owner",
                    password=password, channel=IdentityChannel.DASHBOARD,
                )

    async def test_inactive_or_wrong_company_fails_before_identity_acceptance(self):
        with self.assertRaises(AuthenticationRejected):
            await authenticate_identity(
                self.dashboard_db(company=False), company_id=999, username="owner",
                password=self.password, channel=IdentityChannel.DASHBOARD,
            )

    async def test_unknown_channel_fails_closed(self):
        with self.assertRaises(AuthenticationRejected):
            await authenticate_identity(
                self.dashboard_db(), company_id=1, username="owner",
                password=self.password, channel="Admin",
            )


if __name__ == "__main__":
    unittest.main()
