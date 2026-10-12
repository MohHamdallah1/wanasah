from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions.context import (
    DashboardRequestContext,
    FieldRequestContext,
    RequestContextRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.identity.backoffice_legacy_actor import (
    BackofficeLegacyActorLocatorRejected,
)
from realtime import auth


ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / "realtime" / "auth.py"


class _FakeDB:
    def __init__(self, *, blacklisted: bool = False):
        self.blacklisted = blacklisted
        self.scalar_calls = []

    async def scalar(self, statement):
        self.scalar_calls.append(statement)
        return self.blacklisted


def _claims(
    *,
    principal_id: int = 101,
    company_id: int = 77,
    channel: str = "DASHBOARD",
    principal_type: str = "BACKOFFICE",
    auth_revision: int = 4,
    exp: int = 2_000_000_000,
) -> CompanyTokenClaims:
    return CompanyTokenClaims(
        token_type="access",
        principal_id=principal_id,
        company_id=company_id,
        channel=channel,
        principal_type=principal_type,
        auth_revision=auth_revision,
        jti="ws-jti",
        exp=exp,
    )


def _dashboard(
    *,
    principal_id: int = 101,
    company_id: int = 77,
    backoffice_user_id: int = 202,
    auth_revision: int = 4,
    owner: bool = False,
) -> DashboardRequestContext:
    return DashboardRequestContext(
        principal_id=principal_id,
        company_id=company_id,
        backoffice_user_id=backoffice_user_id,
        auth_revision=auth_revision,
        is_company_owner=owner,
    )


def _field() -> FieldRequestContext:
    return FieldRequestContext(
        principal_id=101,
        company_id=77,
        representative_id=404,
        auth_revision=4,
    )


def _subject(context: DashboardRequestContext, *, owner: bool | None = None):
    return BackofficeAuthorizationSubject(
        principal_id=context.principal_id,
        backoffice_user_id=context.backoffice_user_id,
        company_id=context.company_id,
        is_company_owner=context.is_company_owner if owner is None else owner,
        legacy_grant_driver_id=None if (context.is_company_owner if owner is None else owner) else 303,
    )


def _locator(
    context: DashboardRequestContext,
    *,
    driver_id: int = 303,
    company_id: int | None = None,
    is_admin: bool | None = None,
):
    values = {
        "principal_id": context.principal_id,
        "backoffice_user_id": context.backoffice_user_id,
        "company_id": context.company_id if company_id is None else company_id,
        "legacy_driver_id": driver_id,
    }
    if is_admin is not None:
        values["is_admin"] = is_admin
    return SimpleNamespace(**values)


class RealtimeWebSocketCanonicalAuthTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        *,
        claims: CompanyTokenClaims | None = None,
        context=None,
        subject=None,
        locator=None,
        blacklisted: bool = False,
        admin: bool = False,
    ):
        claims = claims or _claims()
        context = context or _dashboard()
        if subject is None:
            subject = (
                _subject(context)
                if isinstance(context, DashboardRequestContext)
                else SimpleNamespace()
            )
        if locator is None:
            locator = (
                _locator(context)
                if isinstance(context, DashboardRequestContext)
                else SimpleNamespace()
            )
        db = _FakeDB(blacklisted=blacklisted)
        opened_companies = []

        @asynccontextmanager
        async def fake_tenant_session(company_id):
            opened_companies.append(company_id)
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=claims) as decode,
            patch.object(auth, "tenant_session", new=fake_tenant_session),
            patch.object(
                auth,
                "resolve_access_context",
                new_callable=AsyncMock,
                return_value=context,
            ) as resolve_context,
            patch.object(
                auth,
                "resolve_backoffice_authorization_subject",
                new_callable=AsyncMock,
                return_value=subject,
            ) as resolve_subject,
            patch.object(
                auth,
                "resolve_backoffice_legacy_actor_locator",
                new_callable=AsyncMock,
                return_value=locator,
            ) as resolve_locator,
        ):
            result = await (
                auth.authenticate_websocket_admin("token")
                if admin
                else auth.authenticate_websocket_user("token")
            )

        return SimpleNamespace(
            result=result,
            db=db,
            opened_companies=opened_companies,
            decode=decode,
            resolve_context=resolve_context,
            resolve_subject=resolve_subject,
            resolve_locator=resolve_locator,
            claims=claims,
            context=context,
        )

    async def test_valid_backoffice_access_token_uses_persisted_context_and_mapping(self):
        context = _dashboard(principal_id=101, backoffice_user_id=202, company_id=77)
        run = await self._run(
            claims=_claims(principal_id=101, company_id=77, exp=2_000_000_123),
            context=context,
            locator=_locator(context, driver_id=909),
        )

        self.assertEqual(run.opened_companies, [77])
        self.assertEqual(run.result.company_id, 77)
        self.assertEqual(run.result.driver_id, 909)
        self.assertEqual(run.result.token_expires_at, 2_000_000_123)
        run.decode.assert_called_once_with(
            "token",
            secret=auth.Config.SECRET_KEY,
            expected_type="access",
        )
        run.resolve_context.assert_awaited_once_with(run.db, run.claims)
        run.resolve_subject.assert_awaited_once_with(run.db, context)
        run.resolve_locator.assert_awaited_once_with(run.db, context)

    async def test_claim_company_only_bootstraps_and_persisted_company_mismatch_fails_closed(self):
        claims = _claims(company_id=77)
        foreign_context = _dashboard(company_id=88)
        with self.assertRaises(auth.WebSocketAuthError) as caught:
            await self._run(claims=claims, context=foreign_context)
        self.assertEqual(str(caught.exception), "websocket authorization failed")

    async def test_blacklisted_token_rejected_before_persisted_resolution(self):
        db = _FakeDB(blacklisted=True)
        opened = []

        @asynccontextmanager
        async def fake_tenant_session(company_id):
            opened.append(company_id)
            yield db

        resolve_context = AsyncMock()
        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=fake_tenant_session),
            patch.object(auth, "resolve_access_context", new=resolve_context),
        ):
            with self.assertRaises(auth.WebSocketAuthError) as caught:
                await auth.authenticate_websocket_user("revoked")
        self.assertEqual(str(caught.exception), "revoked websocket token")
        self.assertEqual(opened, [77])
        resolve_context.assert_not_awaited()

    async def test_invalid_or_expired_token_is_rejected_by_canonical_codec(self):
        for error in (ValueError("invalid"), RuntimeError("expired")):
            with self.subTest(error=type(error).__name__):
                with patch.object(auth, "decode_company_token", side_effect=error):
                    with self.assertRaises(auth.WebSocketAuthError) as caught:
                        await auth.authenticate_websocket_user("bad")
                self.assertEqual(str(caught.exception), "invalid websocket token")

    async def test_field_representative_context_is_rejected_from_dashboard_websocket(self):
        with self.assertRaises(auth.WebSocketAuthError) as caught:
            await self._run(
                claims=_claims(channel="FIELD", principal_type="FIELD_REPRESENTATIVE"),
                context=_field(),
            )
        self.assertEqual(str(caught.exception), "websocket authorization failed")

    async def test_inactive_or_stale_persisted_identity_rejection_is_fail_closed(self):
        db = _FakeDB()

        @asynccontextmanager
        async def fake_tenant_session(_company_id):
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=fake_tenant_session),
            patch.object(
                auth,
                "resolve_access_context",
                new_callable=AsyncMock,
                side_effect=RequestContextRejected(),
            ),
        ):
            with self.assertRaises(auth.WebSocketAuthError) as caught:
                await auth.authenticate_websocket_user("inactive")
        self.assertEqual(str(caught.exception), "websocket authorization failed")

    async def test_independent_principal_backoffice_and_driver_ids_are_preserved(self):
        context = _dashboard(principal_id=17, backoffice_user_id=421, company_id=9)
        run = await self._run(
            claims=_claims(principal_id=17, company_id=9),
            context=context,
            subject=_subject(context),
            locator=_locator(context, driver_id=8_003),
        )
        self.assertEqual(run.result.company_id, 9)
        self.assertEqual(run.result.driver_id, 8_003)
        self.assertNotEqual(17, 421)
        self.assertNotEqual(17, 8_003)
        self.assertNotEqual(421, 8_003)

    async def test_legacy_driver_admin_flag_is_irrelevant_for_websocket_user(self):
        context = _dashboard()
        results = []
        for legacy_is_admin in (False, True):
            run = await self._run(
                context=context,
                locator=_locator(
                    context,
                    driver_id=303,
                    is_admin=legacy_is_admin,
                ),
            )
            results.append(run.result)
        self.assertEqual(results[0], results[1])

    async def test_admin_accepts_explicit_company_owner_only(self):
        owner_context = _dashboard(owner=True)
        owner = await self._run(
            context=owner_context,
            subject=_subject(owner_context, owner=True),
            locator=_locator(owner_context, driver_id=303, is_admin=False),
            admin=True,
        )
        self.assertEqual(owner.result.company_id, 77)

        ordinary_context = _dashboard(owner=False)
        with self.assertRaises(auth.WebSocketAuthError) as caught:
            await self._run(
                context=ordinary_context,
                subject=_subject(ordinary_context, owner=False),
                locator=_locator(
                    ordinary_context,
                    driver_id=303,
                    is_admin=True,
                ),
                admin=True,
            )
        self.assertEqual(str(caught.exception), "websocket authorization failed")

    async def test_cross_company_legacy_mapping_fails_closed(self):
        context = _dashboard(company_id=77)
        with self.assertRaises(auth.WebSocketAuthError) as caught:
            await self._run(
                context=context,
                locator=_locator(context, company_id=88),
            )
        self.assertEqual(str(caught.exception), "websocket authorization failed")

    async def test_missing_identity_legacy_driver_map_fails_closed(self):
        db = _FakeDB()
        context = _dashboard()

        @asynccontextmanager
        async def fake_tenant_session(_company_id):
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=fake_tenant_session),
            patch.object(
                auth,
                "resolve_access_context",
                new_callable=AsyncMock,
                return_value=context,
            ),
            patch.object(
                auth,
                "resolve_backoffice_authorization_subject",
                new_callable=AsyncMock,
                return_value=_subject(context),
            ),
            patch.object(
                auth,
                "resolve_backoffice_legacy_actor_locator",
                new_callable=AsyncMock,
                side_effect=BackofficeLegacyActorLocatorRejected(),
            ),
        ):
            with self.assertRaises(auth.WebSocketAuthError) as caught:
                await auth.authenticate_websocket_user("token")
        self.assertEqual(str(caught.exception), "websocket authorization failed")


class RealtimeWebSocketSourceAuditTests(unittest.TestCase):
    def test_runtime_source_has_no_legacy_request_authority(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "access_token_identity",
            "Driver.is_admin",
            ".is_admin",
            "Driver.company_id",
            "Driver.id",
            "select(Driver",
            "is_superuser",
            "is_manager",
            "admin claim",
        ):
            self.assertNotIn(forbidden, source, forbidden)

    def test_runtime_uses_exact_canonical_contracts_and_bounded_mapping(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        for required in (
            "decode_company_token(",
            'expected_type="access"',
            "tenant_session(claims.company_id)",
            "TokenBlacklist.token == token",
            "resolve_access_context(db, claims)",
            "isinstance(context, DashboardRequestContext)",
            "company_id=context.company_id",
            "resolve_backoffice_authorization_subject(",
            "subject.is_company_owner",
            "resolve_backoffice_legacy_actor_locator(",
            "driver_id=locator.legacy_driver_id",
            "token_expires_at=claims.exp",
        ):
            self.assertIn(required, source, required)

    def test_callable_and_compatibility_surface_is_preserved(self):
        self.assertTrue(inspect.iscoroutinefunction(auth.authenticate_websocket_user))
        self.assertTrue(inspect.iscoroutinefunction(auth.authenticate_websocket_admin))
        fields = auth.WebSocketAdminIdentity.__dataclass_fields__
        self.assertEqual(
            set(fields),
            {"company_id", "driver_id", "token_expires_at"},
        )

    def test_no_principal_profile_driver_id_equality_assumption(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        forbidden_equalities = (
            "principal_id == locator.legacy_driver_id",
            "backoffice_user_id == locator.legacy_driver_id",
            "claims.principal_id == locator.legacy_driver_id",
            "locator.legacy_driver_id == context.principal_id",
            "locator.legacy_driver_id == context.backoffice_user_id",
        )
        for forbidden in forbidden_equalities:
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
