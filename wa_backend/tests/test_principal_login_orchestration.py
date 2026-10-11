from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import jwt

from api.authentication.login import LoginCompanyContext
from api.authentication.login_orchestration import (
    PrincipalLoginRateLimited,
    PrincipalLoginRejected,
    login_dashboard_principal,
    login_field_principal,
)
from domains.auth_sessions.login_attempts import LoginAttemptRateLimited
from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.refresh_sessions import RefreshSessionRejected
from domains.identity.contracts import (
    AuthenticationRejected,
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)

SECRET = "canonical-login-contract-secret-longer-than-thirty-two-bytes"


class FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.queries = 0

    async def execute(self, statement):
        self.queries += 1
        raise AssertionError("Orchestration must not load operational login compatibility")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def dashboard_identity() -> DashboardAuthenticationResult:
    return DashboardAuthenticationResult(
        principal_id=11,
        company_id=7,
        backoffice_user_id=22,
        username="owner",
        full_name="Owner User",
        auth_revision=3,
        is_company_owner=True,
    )


def field_identity() -> FieldAuthenticationResult:
    return FieldAuthenticationResult(
        principal_id=31,
        company_id=7,
        representative_id=44,
        username="rep",
        full_name="Field Rep",
        auth_revision=5,
    )


class PrincipalLoginOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def assert_canonical_token(self, response, identity):
        claims = jwt.decode(response.token, SECRET, algorithms=["HS256"])
        self.assertEqual(set(claims), {"type", "sub", "company_id", "channel", "principal_type", "auth_revision", "jti", "exp"})
        self.assertEqual(claims["sub"], str(identity.principal_id))
        self.assertEqual(claims["company_id"], identity.company_id)
        self.assertEqual(claims["channel"], identity.channel.value)
        self.assertEqual(claims["principal_type"], identity.principal_type.value)
        self.assertEqual(claims["auth_revision"], identity.auth_revision)
        self.assertEqual(claims["type"], "access")
        self.assertTrue(claims["jti"])
        self.assertIsInstance(claims["exp"], int)

    async def test_dashboard_success_composes_all_boundaries_and_commits_once(self):
        db = FakeDB()
        identity = dashboard_identity()

        with (
            patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock()),
            patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock(return_value=LoginCompanyContext(company_id=7, company_code="WNS-01"))),
            patch("api.authentication.login_orchestration.authenticate_identity", new=AsyncMock(return_value=identity)) as authenticate,
            patch("api.authentication.login_orchestration.require_dashboard_admission", new=AsyncMock(return_value=identity)) as admission,
            patch("api.authentication.login_orchestration.create_refresh_session", new=AsyncMock(return_value=SimpleNamespace(refresh_token="refresh.jwt"))) as create_refresh,
            patch("api.authentication.login_orchestration.issue_access_token", wraps=issue_access_token),
            patch("api.authentication.login_orchestration.record_login_attempt") as record_attempt,
        ):
            response = await login_dashboard_principal(
                db,
                company_code="WNS-01",
                username="owner",
                password="secret",
                ip_address="127.0.0.1",
                secret=SECRET,
            )

        self.assertEqual(response.principal_id, 11)
        self.assertEqual(response.backoffice_user_id, 22)
        self.assertTrue(response.is_company_owner)
        self.assertTrue({"driver_id", "driver_name", "is_admin", "legacy_is_admin"}.isdisjoint(response.model_dump()))
        self.assert_canonical_token(response, identity)
        self.assertEqual(response.channel, "DASHBOARD")
        self.assertTrue(response.dashboard_access)
        admission.assert_awaited_once()
        authenticate.assert_awaited_once_with(db, company_id=7, username="owner", password="secret", channel=identity.channel)
        context = create_refresh.await_args.args[1]
        self.assertEqual(context.principal_id, 11)
        self.assertEqual(context.backoffice_user_id, 22)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(db.queries, 0)
        self.assertTrue(record_attempt.call_args.kwargs["successful"])

    async def test_field_success_never_uses_dashboard_admission(self):
        db = FakeDB()
        identity = field_identity()

        with (
            patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock()),
            patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock(return_value=LoginCompanyContext(company_id=7, company_code="WNS-01"))),
            patch("api.authentication.login_orchestration.authenticate_identity", new=AsyncMock(return_value=identity)) as authenticate,
            patch("api.authentication.login_orchestration.require_dashboard_admission", new=AsyncMock()) as admission,
            patch("api.authentication.login_orchestration.create_refresh_session", new=AsyncMock(return_value=SimpleNamespace(refresh_token="field.refresh"))) as create_refresh,
            patch("api.authentication.login_orchestration.issue_access_token", wraps=issue_access_token),
            patch("api.authentication.login_orchestration.record_login_attempt"),
        ):
            response = await login_field_principal(
                db,
                company_code="WNS-01",
                username="rep",
                password="secret",
                ip_address="127.0.0.1",
                secret=SECRET,
            )

        self.assertEqual(response.principal_id, 31)
        self.assertEqual(response.representative_id, 44)
        self.assertTrue({"driver_id", "driver_name", "is_admin", "legacy_is_admin"}.isdisjoint(response.model_dump()))
        self.assert_canonical_token(response, identity)
        self.assertEqual(response.channel, "FIELD")
        admission.assert_not_awaited()
        authenticate.assert_awaited_once_with(db, company_id=7, username="rep", password="secret", channel=identity.channel)
        context = create_refresh.await_args.args[1]
        self.assertEqual(context.principal_id, 31)
        self.assertEqual(context.representative_id, 44)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(db.queries, 0)

    async def test_wrong_channel_identity_is_rejected_before_admission_or_token_issuance(self):
        for login, wrong_identity in ((login_dashboard_principal, field_identity()),
                                      (login_field_principal, dashboard_identity())):
            with self.subTest(channel=wrong_identity.channel):
                db = FakeDB()
                with (
                    patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock()),
                    patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock(return_value=LoginCompanyContext(7, "WNS-01"))),
                    patch("api.authentication.login_orchestration.authenticate_identity", new=AsyncMock(return_value=wrong_identity)),
                    patch("api.authentication.login_orchestration.require_dashboard_admission", new=AsyncMock()) as admission,
                    patch("api.authentication.login_orchestration.create_refresh_session", new=AsyncMock()) as refresh,
                    patch("api.authentication.login_orchestration.issue_access_token") as access,
                    patch("api.authentication.login_orchestration.record_login_attempt") as record,
                ):
                    with self.assertRaises(PrincipalLoginRejected):
                        await login(db, company_code="WNS-01", username="user", password="secret",
                                    ip_address="127.0.0.1", secret=SECRET)
                admission.assert_not_awaited()
                refresh.assert_not_awaited()
                access.assert_not_called()
                self.assertFalse(record.call_args.kwargs["successful"])
                self.assertEqual((db.commits, db.rollbacks, db.queries), (1, 0, 0))

    async def test_authentication_rejection_records_failed_attempt_and_never_issues_session(self):
        db = FakeDB()

        with (
            patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock()),
            patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock(return_value=LoginCompanyContext(company_id=7, company_code="WNS-01"))),
            patch("api.authentication.login_orchestration.authenticate_identity", new=AsyncMock(side_effect=AuthenticationRejected)),
            patch("api.authentication.login_orchestration.create_refresh_session", new=AsyncMock()) as create_refresh,
            patch("api.authentication.login_orchestration.record_login_attempt") as record_attempt,
        ):
            with self.assertRaises(PrincipalLoginRejected):
                await login_dashboard_principal(
                    db,
                    company_code="WNS-01",
                    username="bad",
                    password="bad",
                    ip_address="127.0.0.1",
                    secret="jwt-secret",
                )

        create_refresh.assert_not_awaited()
        self.assertFalse(record_attempt.call_args.kwargs["successful"])
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)

    async def test_rate_limit_rolls_back_read_transaction_before_rejecting(self):
        db = FakeDB()

        with (
            patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock(side_effect=LoginAttemptRateLimited)),
            patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock()) as prepare_company,
        ):
            with self.assertRaises(PrincipalLoginRateLimited):
                await login_dashboard_principal(
                    db,
                    company_code="WNS-01",
                    username="user",
                    password="secret",
                    ip_address="127.0.0.1",
                    secret="jwt-secret",
                )

        prepare_company.assert_not_awaited()
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    async def test_refresh_session_failure_rolls_back_and_does_not_record_success(self):
        db = FakeDB()
        identity = dashboard_identity()

        with (
            patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock()),
            patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock(return_value=LoginCompanyContext(company_id=7, company_code="WNS-01"))),
            patch("api.authentication.login_orchestration.authenticate_identity", new=AsyncMock(return_value=identity)),
            patch("api.authentication.login_orchestration.require_dashboard_admission", new=AsyncMock(return_value=identity)),
            patch("api.authentication.login_orchestration.create_refresh_session", new=AsyncMock(side_effect=RefreshSessionRejected)),
            patch("api.authentication.login_orchestration.record_login_attempt") as record_attempt,
        ):
            with self.assertRaises(PrincipalLoginRejected):
                await login_dashboard_principal(
                    db,
                    company_code="WNS-01",
                    username="owner",
                    password="secret",
                    ip_address="127.0.0.1",
                    secret="jwt-secret",
                )

        record_attempt.assert_not_called()
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    async def test_unexpected_auth_phase_error_rolls_back_instead_of_leaking_transaction(self):
        db = FakeDB()
        failure = RuntimeError("database unavailable")

        with (
            patch("api.authentication.login_orchestration.enforce_company_login_attempt_limit", new=AsyncMock()),
            patch("api.authentication.login_orchestration.prepare_login_company", new=AsyncMock(side_effect=failure)),
            patch("api.authentication.login_orchestration.record_login_attempt") as record_attempt,
        ):
            with self.assertRaises(RuntimeError):
                await login_field_principal(
                    db,
                    company_code="WNS-01",
                    username="rep",
                    password="secret",
                    ip_address="127.0.0.1",
                    secret="jwt-secret",
                )

        record_attempt.assert_not_called()
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
