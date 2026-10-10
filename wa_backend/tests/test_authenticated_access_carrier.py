"""Focused carrier and FastAPI dependency-cache checks; persistence is mocked."""
import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SECRET = "CarrierSyntheticSecret123456789012345678901234567890123456"
# Import HTTP dependencies against synthetic URLs only; never connect to them.
with patch.dict(os.environ, {"ENVIRONMENT": "test", "SECRET_KEY": SECRET,
                            "DATABASE_URL": "postgresql+asyncpg://carrier_unit@127.0.0.1:1/carrier_unit",
                            "DATABASE_URL_MIGRATION": "postgresql+asyncpg://carrier_admin@127.0.0.1:1/carrier_unit"}):
    from api.authentication import dependencies as deps
from domains.auth_sessions.codec import decode_company_token, issue_access_token
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext, RequestContextRejected


def dashboard():
    return DashboardRequestContext(principal_id=10, company_id=1, backoffice_user_id=70, auth_revision=2, is_company_owner=True)


def field():
    return FieldRequestContext(principal_id=20, company_id=2, representative_id=90, auth_revision=3)


def token_for(context, **options):
    return issue_access_token(principal_id=context.principal_id, company_id=context.company_id,
                              channel=context.channel.value, principal_type=context.principal_type.value,
                              auth_revision=context.auth_revision, secret=SECRET, **options)


class CarrierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        setting = patch.object(deps.Config, "SECRET_KEY", SECRET)
        setting.start()
        self.addCleanup(setting.stop)
        current_tenant = deps.tenant_context.set(None)
        self.addCleanup(deps.tenant_context.reset, current_tenant)

    def db(self, *, transaction=True, blacklisted=False):
        db = MagicMock(spec=AsyncSession)
        db.in_transaction.return_value = transaction
        db.scalar.return_value = blacklisted
        return db

    async def carrier(self, db, raw):
        return await deps.get_authenticated_access_session(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw), db=db,
        )

    async def test_dashboard_and_field_preserve_exact_values_and_are_frozen(self):
        for trusted in (dashboard(), field()):
            raw, db = token_for(trusted), self.db()
            decoded = decode_company_token(raw, secret=SECRET, expected_type="access")
            with patch.object(deps, "decode_company_token", return_value=decoded) as decode, \
                 patch.object(deps, "resolve_access_context", AsyncMock(return_value=trusted)) as resolve:
                carrier = await self.carrier(db, raw)
                self.assertTrue(carrier.token == raw)
                self.assertIs(carrier.claims, decoded)
                self.assertIs(carrier.context, trusted)
                self.assertEqual(decode.call_count, 1)
                self.assertEqual(resolve.await_count, 1)
                self.assertTrue(resolve.call_args.args == (db, decoded))
                self.assertEqual(db.scalar.await_count, 1)
                self.assertTrue(raw in db.scalar.call_args.args[0].compile().params.values())
                with self.assertRaises(FrozenInstanceError):
                    carrier.token = "changed"
                self.assertNotIn(raw, repr(carrier))

    async def test_decode_tenant_blacklist_context_order(self):
        trusted, db = dashboard(), self.db()
        raw = token_for(trusted)
        events = []
        original_decode, original_tenant, original_blacklist = deps.decode_company_token, deps._establish_tenant_context, deps._reject_blacklisted_token
        def decode(*args, **kwargs):
            events.append("decode")
            return original_decode(*args, **kwargs)
        async def tenant(*args, **kwargs):
            events.append("tenant")
            await original_tenant(*args, **kwargs)
        async def blacklist(*args, **kwargs):
            events.append("blacklist")
            await original_blacklist(*args, **kwargs)
        async def resolve(*args, **kwargs):
            events.append("context")
            self.assertEqual(deps.tenant_context.get(), trusted.company_id)
            self.assertEqual(db.execute.await_count, 1)
            return trusted
        with patch.object(deps, "decode_company_token", side_effect=decode), \
             patch.object(deps, "_establish_tenant_context", side_effect=tenant), \
             patch.object(deps, "_reject_blacklisted_token", side_effect=blacklist), \
             patch.object(deps, "resolve_access_context", side_effect=resolve):
            await self.carrier(db, raw)
        self.assertEqual(events, ["decode", "tenant", "blacklist", "context"])

    async def test_first_checkout_establishes_tenant_before_resolution(self):
        db = self.db(transaction=False)
        with patch.object(deps, "resolve_access_context", AsyncMock(return_value=dashboard())):
            await self.carrier(db, token_for(dashboard()))
        self.assertEqual(db.connection.await_count, 1)
        self.assertEqual(db.execute.await_count, 0)
        self.assertEqual(deps.tenant_context.get(), 1)

    async def test_blacklist_rejection_once_before_context(self):
        db = self.db(blacklisted=True)
        with patch.object(deps, "resolve_access_context", AsyncMock()) as resolve:
            with self.assertRaises(HTTPException) as rejected:
                await self.carrier(db, token_for(dashboard()))
        self.assertEqual(rejected.exception.status_code, 401)
        self.assertEqual(rejected.exception.headers, {"WWW-Authenticate": "Bearer"})
        self.assertEqual(db.scalar.await_count, 1)
        self.assertEqual(resolve.await_count, 0)

    async def test_invalid_expired_and_missing_bearer_fail_before_persistence(self):
        for raw in ("invalid-access", token_for(dashboard(), now=datetime.now(timezone.utc) - timedelta(days=1))):
            db = self.db()
            with patch.object(deps, "resolve_access_context", AsyncMock()) as resolve:
                with self.assertRaises(HTTPException) as rejected:
                    await self.carrier(db, raw)
            self.assertEqual(rejected.exception.status_code, 401)
            self.assertEqual(db.execute.await_count + db.scalar.await_count + resolve.await_count, 0)
        for credentials in (None, HTTPAuthorizationCredentials(scheme="Basic", credentials="x"),
                            HTTPAuthorizationCredentials(scheme="Bearer", credentials="")):
            with patch.object(deps, "decode_company_token") as decode:
                with self.assertRaises(HTTPException):
                    await deps.get_authenticated_access_session(credentials=credentials, db=self.db())
                self.assertEqual(decode.call_count, 0)

    async def test_context_and_persistence_rejections_remain_opaque(self):
        for failure in (RequestContextRejected(), RuntimeError("synthetic persistence detail")):
            with patch.object(deps, "resolve_access_context", AsyncMock(side_effect=failure)):
                with self.assertRaises(HTTPException) as rejected:
                    await self.carrier(self.db(), token_for(dashboard()))
            self.assertEqual(rejected.exception.status_code, 401)
            self.assertEqual(rejected.exception.detail, deps._AUTH_REJECTION_DETAIL)

    async def test_context_only_wrappers_preserve_identity_and_channel_denials(self):
        for trusted in (dashboard(), field()):
            raw, db = token_for(trusted), self.db()
            with patch.object(deps, "decode_company_token", wraps=deps.decode_company_token) as decode, \
                 patch.object(deps, "resolve_access_context", AsyncMock(return_value=trusted)) as resolve:
                carrier = await self.carrier(db, raw)
                current = await deps.get_current_principal_context(session=carrier)
                self.assertIs(current, trusted)
                correct = deps.get_current_backoffice_context if isinstance(trusted, DashboardRequestContext) else deps.get_current_field_context
                incorrect = deps.get_current_field_context if isinstance(trusted, DashboardRequestContext) else deps.get_current_backoffice_context
                self.assertIs(await correct(current=current), trusted)
                with self.assertRaises(HTTPException) as rejected:
                    await incorrect(current=current)
                self.assertEqual(rejected.exception.status_code, 401)
                self.assertEqual((decode.call_count, resolve.await_count, db.scalar.await_count), (1, 1, 1))
        with patch.object(deps, "resolve_access_context", AsyncMock(return_value=dashboard())) as resolve:
            self.assertIs(await deps._resolve_http_context(token=token_for(dashboard()), db=self.db()), resolve.return_value)

    async def test_direct_principal_credentials_db_api_delegates_once(self):
        trusted, db = dashboard(), self.db()
        raw = token_for(trusted)
        with patch.object(deps, "decode_company_token", wraps=deps.decode_company_token) as decode, \
             patch.object(deps, "resolve_access_context", AsyncMock(return_value=trusted)) as resolve:
            current = await deps.get_current_principal_context(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw), db=db,
            )
        self.assertIs(current, trusted)
        self.assertEqual((decode.call_count, resolve.await_count, db.scalar.await_count), (1, 1, 1))

    async def test_fastapi_cache_shares_carrier_across_dependencies_per_request(self):
        # These routes exist only on a local test app, never on the runtime app.
        app, captured, db = FastAPI(), [], self.db()
        async def test_db():
            return db
        app.dependency_overrides[deps.get_db] = test_db
        async def dashboard_endpoint(
            session=Depends(deps.get_authenticated_access_session),
            principal=Depends(deps.get_current_principal_context),
            current=Depends(deps.get_current_backoffice_context),
        ):
            captured.append((session, principal, current))
            return {"ok": True}
        async def field_endpoint(
            session=Depends(deps.get_authenticated_access_session),
            principal=Depends(deps.get_current_principal_context),
            current=Depends(deps.get_current_field_context),
        ):
            captured.append((session, principal, current))
            return {"ok": True}
        app.add_api_route("/dashboard", dashboard_endpoint)
        app.add_api_route("/field", field_endpoint)
        contexts = {10: dashboard(), 20: field()}
        async def resolve(db, claims):
            return contexts[claims.principal_id]
        with patch.object(deps, "decode_company_token", wraps=deps.decode_company_token) as decode, \
             patch.object(deps, "resolve_access_context", AsyncMock(side_effect=resolve)) as resolution:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://carrier.test") as client:
                for index, (path, trusted) in enumerate((("/dashboard", contexts[10]), ("/field", contexts[20])), 1):
                    raw = token_for(trusted)
                    response = await client.get(path, headers={"Authorization": "Bearer " + raw})
                    self.assertEqual(response.status_code, 200)
                    carrier, principal, channel_context = captured[-1]
                    self.assertTrue(carrier.token == raw)
                    self.assertIs(carrier.context, trusted)
                    self.assertIs(principal, trusted)
                    self.assertIs(channel_context, trusted)
                    self.assertEqual((decode.call_count, resolution.await_count, db.scalar.await_count), (index, index, index))
                denied = await client.get("/dashboard", headers={"Authorization": "Bearer " + token_for(contexts[20])})
                self.assertEqual(denied.status_code, 401)
                self.assertEqual((decode.call_count, resolution.await_count, db.scalar.await_count), (3, 3, 3))
        self.assertIsNot(captured[0][0], captured[1][0])

    async def test_extra_jwt_authority_is_not_carried_or_used(self):
        trusted = field()
        claims = decode_company_token(token_for(trusted), secret=SECRET).to_payload()
        raw = jwt.encode({**claims, "role": "Admin", "is_admin": True, "capabilities": ["all"]}, SECRET, algorithm="HS256")
        with patch.object(deps, "resolve_access_context", AsyncMock(return_value=trusted)):
            carrier = await self.carrier(self.db(), raw)
        self.assertIs(carrier.context, trusted)
        self.assertFalse(any(hasattr(carrier.claims, name) for name in ("role", "is_admin", "capabilities")))
        tree = ast.parse(Path(deps.__file__).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue(names.isdisjoint({"Driver", "RefreshToken", "is_admin"}))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertTrue(calls.isdisjoint({"add", "delete", "flush", "commit", "rollback", "post"}))


if __name__ == "__main__":
    unittest.main()
