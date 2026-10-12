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
from domains.identity.backoffice_legacy_actor import BackofficeLegacyActorLocatorRejected
from realtime import auth


ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / "realtime" / "auth.py"


class _DB:
    def __init__(self, blacklisted=False):
        self.blacklisted = blacklisted
        self.scalar_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.blacklisted


def _claims(*, company=77, principal=101, channel="DASHBOARD", principal_type="BACKOFFICE", revision=4, exp=2_000_000_000):
    return CompanyTokenClaims(
        token_type="access",
        principal_id=principal,
        company_id=company,
        channel=channel,
        principal_type=principal_type,
        auth_revision=revision,
        jti="ws-jti",
        exp=exp,
    )


def _dashboard(*, company=77, principal=101, profile=202, revision=4, owner=False):
    return DashboardRequestContext(
        principal_id=principal,
        company_id=company,
        backoffice_user_id=profile,
        auth_revision=revision,
        is_company_owner=owner,
    )


def _subject(context, *, owner=None):
    resolved_owner = context.is_company_owner if owner is None else owner
    return BackofficeAuthorizationSubject(
        principal_id=context.principal_id,
        backoffice_user_id=context.backoffice_user_id,
        company_id=context.company_id,
        is_company_owner=resolved_owner,
        legacy_grant_driver_id=None if resolved_owner else 303,
    )


def _locator(context, *, driver=303, company=None, is_admin=None):
    values = dict(
        principal_id=context.principal_id,
        backoffice_user_id=context.backoffice_user_id,
        company_id=context.company_id if company is None else company,
        legacy_driver_id=driver,
    )
    if is_admin is not None:
        values["is_admin"] = is_admin
    return SimpleNamespace(**values)


class RealtimeWebSocketCanonicalAuthTests(unittest.IsolatedAsyncioTestCase):
    async def _authenticate(
        self,
        *,
        claims=None,
        context=None,
        subject=None,
        locator=None,
        blacklisted=False,
        admin=False,
    ):
        claims = claims or _claims()
        context = context or _dashboard()
        if subject is None:
            subject = _subject(context) if isinstance(context, DashboardRequestContext) else SimpleNamespace()
        if locator is None:
            locator = _locator(context) if isinstance(context, DashboardRequestContext) else SimpleNamespace()
        db = _DB(blacklisted)
        tenant_ids = []

        @asynccontextmanager
        async def session(company_id):
            tenant_ids.append(company_id)
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=claims) as decode,
            patch.object(auth, "tenant_session", new=session),
            patch.object(auth, "resolve_access_context", new_callable=AsyncMock, return_value=context) as resolve_context,
            patch.object(auth, "resolve_backoffice_authorization_subject", new_callable=AsyncMock, return_value=subject) as resolve_subject,
            patch.object(auth, "resolve_backoffice_legacy_actor_locator", new_callable=AsyncMock, return_value=locator) as resolve_locator,
        ):
            result = await (
                auth.authenticate_websocket_admin("token")
                if admin
                else auth.authenticate_websocket_user("token")
            )

        return SimpleNamespace(
            result=result,
            db=db,
            tenant_ids=tenant_ids,
            decode=decode,
            resolve_context=resolve_context,
            resolve_subject=resolve_subject,
            resolve_locator=resolve_locator,
            claims=claims,
        )

    async def test_valid_dashboard_token_uses_codec_persisted_context_and_exact_mapping(self):
        context = _dashboard(company=77, principal=101, profile=202, revision=9)
        claims = _claims(company=77, principal=101, revision=9, exp=2_000_000_123)
        run = await self._authenticate(
            claims=claims,
            context=context,
            locator=_locator(context, driver=909),
        )
        self.assertEqual(run.tenant_ids, [77])
        self.assertEqual((run.result.company_id, run.result.driver_id, run.result.token_expires_at), (77, 909, 2_000_000_123))
        run.decode.assert_called_once_with("token", secret=auth.Config.SECRET_KEY, expected_type="access")
        run.resolve_context.assert_awaited_once_with(run.db, claims)
        run.resolve_subject.assert_awaited_once_with(run.db, context)
        run.resolve_locator.assert_awaited_once_with(run.db, context)

    async def test_blacklisted_token_is_rejected_before_persisted_resolution(self):
        db = _DB(True)

        @asynccontextmanager
        async def session(_company_id):
            yield db

        resolver = AsyncMock()
        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=session),
            patch.object(auth, "resolve_access_context", new=resolver),
        ):
            with self.assertRaisesRegex(auth.WebSocketAuthError, "revoked websocket token"):
                await auth.authenticate_websocket_user("revoked")
        resolver.assert_not_awaited()

    async def test_invalid_and_expired_tokens_fail_at_canonical_decode(self):
        for failure in (ValueError("invalid"), RuntimeError("expired")):
            with self.subTest(type=type(failure).__name__):
                with patch.object(auth, "decode_company_token", side_effect=failure):
                    with self.assertRaisesRegex(auth.WebSocketAuthError, "invalid websocket token"):
                        await auth.authenticate_websocket_user("bad")

    async def test_field_representative_is_rejected_from_dashboard_websocket(self):
        field = FieldRequestContext(
            principal_id=101,
            company_id=77,
            representative_id=404,
            auth_revision=4,
        )
        with self.assertRaisesRegex(auth.WebSocketAuthError, "websocket authorization failed"):
            await self._authenticate(
                claims=_claims(channel="FIELD", principal_type="FIELD_REPRESENTATIVE"),
                context=field,
            )

    async def test_inactive_or_stale_persisted_identity_is_rejected(self):
        db = _DB(False)

        @asynccontextmanager
        async def session(_company_id):
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=session),
            patch.object(auth, "resolve_access_context", new_callable=AsyncMock, side_effect=RequestContextRejected()),
        ):
            with self.assertRaisesRegex(auth.WebSocketAuthError, "websocket authorization failed"):
                await auth.authenticate_websocket_user("inactive")

    async def test_claim_company_cannot_override_persisted_company(self):
        with self.assertRaisesRegex(auth.WebSocketAuthError, "websocket authorization failed"):
            await self._authenticate(claims=_claims(company=77), context=_dashboard(company=88))

    async def test_independent_ids_work_and_legacy_admin_flag_is_irrelevant(self):
        context = _dashboard(company=9, principal=17, profile=421)
        results = []
        for legacy_is_admin in (False, True):
            run = await self._authenticate(
                claims=_claims(company=9, principal=17),
                context=context,
                locator=_locator(context, driver=8_003, is_admin=legacy_is_admin),
            )
            results.append(run.result)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0].driver_id, 8_003)
        self.assertEqual(len({17, 421, 8_003}), 3)

    async def test_admin_requires_explicit_company_owner_even_if_legacy_admin_true(self):
        owner_context = _dashboard(owner=True)
        owner = await self._authenticate(
            context=owner_context,
            subject=_subject(owner_context, owner=True),
            locator=_locator(owner_context, is_admin=False),
            admin=True,
        )
        self.assertEqual(owner.result.company_id, 77)

        ordinary = _dashboard(owner=False)
        with self.assertRaisesRegex(auth.WebSocketAuthError, "websocket authorization failed"):
            await self._authenticate(
                context=ordinary,
                subject=_subject(ordinary, owner=False),
                locator=_locator(ordinary, is_admin=True),
                admin=True,
            )

    async def test_cross_company_legacy_mapping_fails_closed(self):
        context = _dashboard(company=77)
        with self.assertRaisesRegex(auth.WebSocketAuthError, "websocket authorization failed"):
            await self._authenticate(context=context, locator=_locator(context, company=88))

    async def test_missing_legacy_mapping_fails_closed_for_compatibility_driver_id(self):
        db = _DB(False)
        context = _dashboard()

        @asynccontextmanager
        async def session(_company_id):
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=session),
            patch.object(auth, "resolve_access_context", new_callable=AsyncMock, return_value=context),
            patch.object(auth, "resolve_backoffice_authorization_subject", new_callable=AsyncMock, return_value=_subject(context)),
            patch.object(
                auth,
                "resolve_backoffice_legacy_actor_locator",
                new_callable=AsyncMock,
                side_effect=BackofficeLegacyActorLocatorRejected(),
            ),
        ):
            with self.assertRaisesRegex(auth.WebSocketAuthError, "websocket authorization failed"):
                await auth.authenticate_websocket_user("token")


class RealtimeWebSocketSourceAuditTests(unittest.TestCase):
    def test_source_uses_only_canonical_identity_authority(self):
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
        ):
            self.assertNotIn(forbidden, source, forbidden)
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

    def test_public_callable_and_compatibility_surface_is_preserved(self):
        self.assertTrue(inspect.iscoroutinefunction(auth.authenticate_websocket_user))
        self.assertTrue(inspect.iscoroutinefunction(auth.authenticate_websocket_admin))
        self.assertEqual(
            set(auth.WebSocketAdminIdentity.__dataclass_fields__),
            {"company_id", "driver_id", "token_expires_at"},
        )

    def test_no_principal_profile_driver_id_equality_assumption(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "principal_id == locator.legacy_driver_id",
            "backoffice_user_id == locator.legacy_driver_id",
            "claims.principal_id == locator.legacy_driver_id",
            "locator.legacy_driver_id == context.principal_id",
            "locator.legacy_driver_id == context.backoffice_user_id",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
