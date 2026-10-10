from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt

from api.authentication import dependencies as http_dependencies
from config import Config
from domains.auth_sessions.codec import issue_access_token, issue_refresh_token
from domains.auth_sessions.context import (
    DashboardRequestContext,
    FieldRequestContext,
    RequestContextRejected,
)


class _FakeTenantContext:
    def __init__(self, events: list[str]):
        self.events = events
        self.company_id: int | None = None

    def set(self, company_id: int):
        self.company_id = company_id
        self.events.append("tenant")


class _FakeDB:
    def __init__(
        self,
        *,
        blacklisted: bool = False,
        events: list[str] | None = None,
        in_transaction: bool = False,
    ):
        self.blacklisted = blacklisted
        self.events = events if events is not None else []
        self._in_transaction = in_transaction
        self.connection_calls = 0
        self.execute_calls = 0
        self.blacklist_tokens: list[str] = []

    def in_transaction(self) -> bool:
        return self._in_transaction

    async def connection(self):
        self.connection_calls += 1
        self.events.append("connection")
        return object()

    async def execute(self, statement, params=None):
        self.execute_calls += 1
        self.events.append("set_config")
        return object()

    async def scalar(self, statement):
        self.events.append("blacklist")
        compiled = statement.compile()
        self.blacklist_tokens.extend(
            value for value in compiled.params.values() if isinstance(value, str)
        )
        return self.blacklisted


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _dashboard_context(*, owner: bool = False) -> DashboardRequestContext:
    return DashboardRequestContext(
        principal_id=11,
        company_id=7,
        backoffice_user_id=101,
        auth_revision=3,
        is_company_owner=owner,
    )


def _field_context() -> FieldRequestContext:
    return FieldRequestContext(
        principal_id=12,
        company_id=7,
        representative_id=202,
        auth_revision=4,
    )


def _access_token(
    *,
    principal_id: int = 11,
    channel: str = "DASHBOARD",
    principal_type: str = "BACKOFFICE",
    auth_revision: int = 3,
    secret: str | None = None,
    now: datetime | None = None,
) -> str:
    return issue_access_token(
        principal_id=principal_id,
        company_id=7,
        channel=channel,
        principal_type=principal_type,
        auth_revision=auth_revision,
        secret=secret or Config.SECRET_KEY,
        now=now,
    )


class PrincipalHTTPDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def _assert_auth_rejected(self, awaitable) -> HTTPException:
        with self.assertRaises(HTTPException) as raised:
            await awaitable
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(
            raised.exception.detail,
            "Authentication credentials are invalid or expired.",
        )
        return raised.exception

    async def test_valid_dashboard_access_token(self):
        token = _access_token()
        db = _FakeDB()
        expected = _dashboard_context(owner=True)
        with patch.object(
            http_dependencies,
            "resolve_access_context",
            AsyncMock(return_value=expected),
        ):
            result = await http_dependencies.get_current_principal_context(
                credentials=_credentials(token),
                db=db,
            )
        self.assertIs(result, expected)

    async def test_valid_field_access_token(self):
        token = _access_token(
            principal_id=12,
            channel="FIELD",
            principal_type="FIELD_REPRESENTATIVE",
            auth_revision=4,
        )
        db = _FakeDB()
        expected = _field_context()
        with patch.object(
            http_dependencies,
            "resolve_access_context",
            AsyncMock(return_value=expected),
        ):
            result = await http_dependencies.get_current_principal_context(
                credentials=_credentials(token),
                db=db,
            )
        self.assertIs(result, expected)

    async def test_invalid_signature_fails_before_database(self):
        token = _access_token(secret="definitely-not-the-config-secret")
        db = _FakeDB()
        await self._assert_auth_rejected(
            http_dependencies.get_current_principal_context(
                credentials=_credentials(token), db=db
            )
        )
        self.assertEqual(db.connection_calls, 0)
        self.assertEqual(db.events, [])

    async def test_expired_token_fails_before_database(self):
        token = _access_token(
            now=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        db = _FakeDB()
        await self._assert_auth_rejected(
            http_dependencies.get_current_principal_context(
                credentials=_credentials(token), db=db
            )
        )
        self.assertEqual(db.events, [])

    async def test_non_access_token_fails_before_database(self):
        token = issue_refresh_token(
            principal_id=11,
            company_id=7,
            channel="DASHBOARD",
            principal_type="BACKOFFICE",
            auth_revision=3,
            secret=Config.SECRET_KEY,
        )
        db = _FakeDB()
        await self._assert_auth_rejected(
            http_dependencies.get_current_principal_context(
                credentials=_credentials(token), db=db
            )
        )
        self.assertEqual(db.events, [])

    async def test_blacklist_rejects_exact_access_token_before_resolution(self):
        token = _access_token()
        events: list[str] = []
        db = _FakeDB(blacklisted=True, events=events)
        resolver = AsyncMock(return_value=_dashboard_context())
        with patch.object(http_dependencies, "resolve_access_context", resolver):
            await self._assert_auth_rejected(
                http_dependencies.get_current_principal_context(
                    credentials=_credentials(token), db=db
                )
            )
        resolver.assert_not_awaited()
        self.assertIn(token, db.blacklist_tokens)

    async def test_request_context_rejection_is_not_exposed(self):
        token = _access_token()
        db = _FakeDB()
        resolver = AsyncMock(side_effect=RequestContextRejected("internal detail"))
        with patch.object(http_dependencies, "resolve_access_context", resolver):
            error = await self._assert_auth_rejected(
                http_dependencies.get_current_principal_context(
                    credentials=_credentials(token), db=db
                )
            )
        self.assertNotIn("internal detail", str(error.detail))

    async def test_dashboard_rejects_field_context(self):
        await self._assert_auth_rejected(
            http_dependencies.get_current_backoffice_context(_field_context())
        )

    async def test_field_rejects_dashboard_context(self):
        await self._assert_auth_rejected(
            http_dependencies.get_current_field_context(_dashboard_context())
        )

    async def test_tenant_is_set_before_persistence_resolution(self):
        token = _access_token()
        events: list[str] = []
        db = _FakeDB(events=events)

        async def _resolve(db_arg, claims):
            self.assertIs(db_arg, db)
            events.append("resolve")
            return _dashboard_context()

        with (
            patch.object(
                http_dependencies,
                "tenant_context",
                _FakeTenantContext(events),
            ),
            patch.object(http_dependencies, "resolve_access_context", _resolve),
        ):
            await http_dependencies.get_current_principal_context(
                credentials=_credentials(token),
                db=db,
            )

        self.assertEqual(events[:4], ["tenant", "connection", "blacklist", "resolve"])

    async def test_returned_context_cannot_receive_legacy_or_credential_authority(self):
        now = datetime.now(timezone.utc)
        payload = {
            "type": "access",
            "sub": "11",
            "company_id": 7,
            "channel": "DASHBOARD",
            "principal_type": "BACKOFFICE",
            "auth_revision": 3,
            "jti": "extra-claims-test",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "role": "Admin",
            "is_admin": True,
            "username": "legacy-name",
            "capabilities": ["everything"],
            "password_hash": "must-never-surface",
        }
        token = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
        db = _FakeDB()

        async def _resolve(_db, claims):
            self.assertFalse(hasattr(claims, "role"))
            self.assertFalse(hasattr(claims, "is_admin"))
            self.assertFalse(hasattr(claims, "username"))
            self.assertFalse(hasattr(claims, "capabilities"))
            self.assertFalse(hasattr(claims, "password_hash"))
            return _dashboard_context()

        with patch.object(http_dependencies, "resolve_access_context", _resolve):
            result = await http_dependencies.get_current_principal_context(
                credentials=_credentials(token),
                db=db,
            )

        keys = set(asdict(result))
        self.assertFalse(
            keys & {"password_hash", "username", "role", "is_admin", "capabilities", "driver_id"}
        )


if __name__ == "__main__":
    unittest.main()
