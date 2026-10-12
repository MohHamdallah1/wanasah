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
from realtime import auth


ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / "realtime" / "auth.py"


class _DB:
    def __init__(self, *scalar_results):
        self.scalar_results = list(scalar_results or (False,))
        self.scalar_calls = []

    async def scalar(self, statement):
        self.scalar_calls.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar call")
        return self.scalar_results.pop(0)


def _claims(
    *,
    company=77,
    principal=101,
    channel="DASHBOARD",
    principal_type="BACKOFFICE",
    revision=4,
    exp=2_000_000_000,
):
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


def _dashboard(
    *,
    company=77,
    principal=101,
    profile=202,
    revision=4,
    owner=False,
):
    return DashboardRequestContext(
        principal_id=principal,
        company_id=company,
        backoffice_user_id=profile,
        auth_revision=revision,
        is_company_owner=owner,
    )


def _subject(context, *, owner=None, is_admin_marker=None):
    resolved_owner = context.is_company_owner if owner is None else owner
    values = dict(
        principal_id=context.principal_id,
        backoffice_user_id=context.backoffice_user_id,
        company_id=context.company_id,
        is_company_owner=resolved_owner,
        legacy_grant_driver_id=None if resolved_owner else 303,
    )
    if is_admin_marker is None:
        return BackofficeAuthorizationSubject(**values)
    return SimpleNamespace(**values, is_admin=is_admin_marker)


class RealtimeWebSocketCanonicalAuthTests(unittest.IsolatedAsyncioTestCase):
    async def _authenticate(
        self,
        *,
        claims=None,
        context=None,
        subject=None,
        scalar_results=(False,),
        admin=False,
        capability=None,
        any_location=False,
    ):
        claims = claims or _claims()
        context = context or _dashboard()
        if subject is None:
            subject = (
                _subject(context)
                if isinstance(context, DashboardRequestContext)
                else SimpleNamespace()
            )
        db = _DB(*scalar_results)
        tenant_ids = []

        @asynccontextmanager
        async def session(company_id):
            tenant_ids.append(company_id)
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=claims) as decode,
            patch.object(auth, "tenant_session", new=session),
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
        ):
            if admin:
                result = await auth.authenticate_websocket_admin("token")
            else:
                result = await auth.authenticate_websocket_user(
                    "token",
                    capability=capability,
                    any_location=any_location,
                )

        return SimpleNamespace(
            result=result,
            db=db,
            tenant_ids=tenant_ids,
            decode=decode,
            resolve_context=resolve_context,
            resolve_subject=resolve_subject,
            claims=claims,
            subject=subject,
        )

    async def test_valid_dashboard_token_uses_codec_and_persisted_context(self):
        context = _dashboard(company=77, principal=101, profile=202, revision=9)
        claims = _claims(company=77, principal=101, revision=9, exp=2_000_000_123)
        run = await self._authenticate(
            claims=claims,
            context=context,
        )
        self.assertEqual(run.tenant_ids, [77])
        self.assertEqual(
            (run.result.company_id, run.result.token_expires_at),
            (77, 2_000_000_123),
        )
        run.decode.assert_called_once_with(
            "token",
            secret=auth.Config.SECRET_KEY,
            expected_type="access",
        )
        run.resolve_context.assert_awaited_once_with(run.db, claims)
        run.resolve_subject.assert_awaited_once_with(run.db, context)

    async def test_catalog_read_any_location_allows_inside_auth_tenant_session(self):
        run = await self._authenticate(
            scalar_results=(False, True),
            capability="catalog.read",
            any_location=True,
        )
        self.assertEqual(run.result.company_id, 77)
        self.assertEqual(run.tenant_ids, [77])
        self.assertEqual(len(run.db.scalar_calls), 2)

    async def test_missing_catalog_read_denies(self):
        with self.assertRaisesRegex(
            auth.WebSocketAuthError,
            "websocket authorization failed",
        ):
            await self._authenticate(
                scalar_results=(False, False),
                capability="catalog.read",
                any_location=True,
            )

    async def test_company_owner_allows_capability_canonically_without_grant_lookup(self):
        context = _dashboard(owner=True)
        run = await self._authenticate(
            context=context,
            subject=_subject(context, owner=True),
            scalar_results=(False,),
            capability="catalog.read",
            any_location=True,
        )
        self.assertEqual(run.result.company_id, 77)
        self.assertEqual(len(run.db.scalar_calls), 1)

    async def test_legacy_admin_marker_cannot_bypass_missing_capability(self):
        context = _dashboard(owner=False)
        with self.assertRaisesRegex(
            auth.WebSocketAuthError,
            "websocket authorization failed",
        ):
            await self._authenticate(
                context=context,
                subject=_subject(
                    context,
                    owner=False,
                    is_admin_marker=True,
                ),
                scalar_results=(False, False),
                capability="catalog.read",
                any_location=True,
            )

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
            with self.assertRaisesRegex(
                auth.WebSocketAuthError,
                "revoked websocket token",
            ):
                await auth.authenticate_websocket_user(
                    "revoked",
                    capability="catalog.read",
                    any_location=True,
                )
        resolver.assert_not_awaited()

    async def test_invalid_and_expired_tokens_fail_at_canonical_decode(self):
        for failure in (ValueError("invalid"), RuntimeError("expired")):
            with self.subTest(type=type(failure).__name__):
                with patch.object(auth, "decode_company_token", side_effect=failure):
                    with self.assertRaisesRegex(
                        auth.WebSocketAuthError,
                        "invalid websocket token",
                    ):
                        await auth.authenticate_websocket_user("bad")

    async def test_field_representative_is_rejected_from_dashboard_websocket(self):
        field = FieldRequestContext(
            principal_id=101,
            company_id=77,
            representative_id=404,
            auth_revision=4,
        )
        with self.assertRaisesRegex(
            auth.WebSocketAuthError,
            "websocket authorization failed",
        ):
            await self._authenticate(
                claims=_claims(
                    channel="FIELD",
                    principal_type="FIELD_REPRESENTATIVE",
                ),
                context=field,
                capability="catalog.read",
                any_location=True,
            )

    async def test_inactive_or_stale_persisted_identity_is_rejected(self):
        db = _DB(False)

        @asynccontextmanager
        async def session(_company_id):
            yield db

        with (
            patch.object(auth, "decode_company_token", return_value=_claims()),
            patch.object(auth, "tenant_session", new=session),
            patch.object(
                auth,
                "resolve_access_context",
                new_callable=AsyncMock,
                side_effect=RequestContextRejected(),
            ),
        ):
            with self.assertRaisesRegex(
                auth.WebSocketAuthError,
                "websocket authorization failed",
            ):
                await auth.authenticate_websocket_user(
                    "inactive",
                    capability="catalog.read",
                    any_location=True,
                )

    async def test_claim_company_cannot_override_persisted_company(self):
        with self.assertRaisesRegex(
            auth.WebSocketAuthError,
            "websocket authorization failed",
        ):
            await self._authenticate(
                claims=_claims(company=77),
                context=_dashboard(company=88),
            )

    async def test_independent_principal_and_backoffice_ids_work(self):
        context = _dashboard(company=9, principal=17, profile=421)
        run = await self._authenticate(
            claims=_claims(company=9, principal=17),
            context=context,
        )
        self.assertEqual(run.result.company_id, 9)
        self.assertNotEqual(17, 421)

    async def test_admin_requires_explicit_company_owner_even_if_admin_marker_true(self):
        owner_context = _dashboard(owner=True)
        owner = await self._authenticate(
            context=owner_context,
            subject=_subject(owner_context, owner=True),
            admin=True,
        )
        self.assertEqual(owner.result.company_id, 77)

        ordinary = _dashboard(owner=False)
        with self.assertRaisesRegex(
            auth.WebSocketAuthError,
            "websocket authorization failed",
        ):
            await self._authenticate(
                context=ordinary,
                subject=_subject(
                    ordinary,
                    owner=False,
                    is_admin_marker=True,
                ),
                admin=True,
            )


class RealtimeWebSocketSourceAuditTests(unittest.TestCase):
    def test_source_uses_only_canonical_identity_and_capability_authority(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "access_token_identity",
            "Driver.is_admin",
            ".is_admin",
            "Driver.company_id",
            "Driver.id",
            "select(Driver",
            "resolve_backoffice_legacy_actor_locator",
            "legacy_driver_id",
            "driver_id",
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
            "BackofficeCapabilityAccess(",
            ").require(",
            "capability=capability",
            "any_location=any_location",
            "subject.is_company_owner",
            "token_expires_at=claims.exp",
        ):
            self.assertIn(required, source, required)

    def test_public_callable_surface_and_capability_parameters_are_preserved(self):
        self.assertTrue(inspect.iscoroutinefunction(auth.authenticate_websocket_user))
        self.assertTrue(inspect.iscoroutinefunction(auth.authenticate_websocket_admin))
        self.assertEqual(
            set(auth.WebSocketAdminIdentity.__dataclass_fields__),
            {"company_id", "token_expires_at"},
        )
        parameters = inspect.signature(auth.authenticate_websocket_user).parameters
        self.assertEqual(set(parameters), {"token", "capability", "any_location"})
        self.assertEqual(parameters["capability"].default, None)
        self.assertIs(parameters["any_location"].default, False)

    def test_no_principal_profile_id_equality_assumption(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "context.principal_id == context.backoffice_user_id",
            "context.backoffice_user_id == context.principal_id",
            "claims.principal_id == context.backoffice_user_id",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
