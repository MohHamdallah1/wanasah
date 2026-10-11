"""Legacy transport mapping and real FastAPI cache checks; persistence is mocked."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SECRET = "LegacyFieldTransportSyntheticSecret123456789012345678901234567890"
with patch.dict(os.environ, {
    "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://legacy_field_unit@127.0.0.1:1/legacy_field_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://legacy_field_admin@127.0.0.1:1/legacy_field_unit",
}):
    from api import dependencies as legacy
    from api.authentication import dependencies as canonical
    from api.authentication import legacy_field_transport as module

from domains.auth_sessions.context import FieldRequestContext
from models import Driver


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("A migration label must never classify the request")


class TransportActor(SimpleNamespace):
    @property
    def is_admin(self):
        raise AssertionError("An operational flag must never classify the request")


def actor(**changes):
    return TransportActor(**{**dict(id=303, company_id=7, is_active=True), **changes})


def bridge(**changes):
    return Bridge(**{**dict(company_id=7, legacy_driver_id=303,
                           field_principal_id=101, field_representative_id=202), **changes})


def identity(**changes):
    return SimpleNamespace(**{**dict(
        representative_company_id=7, representative_id=202, representative_principal_id=101,
        representative_type="FIELD_REPRESENTATIVE", principal_company_id=7, principal_id=101,
        principal_type="FIELD_REPRESENTATIVE", principal_active=True, auth_revision=13,
    ), **changes})


def database(mapping, canonical_identity):
    mapping_result, identity_result = Mock(), Mock()
    mapping_result.one_or_none.return_value = mapping
    identity_result.one_or_none.return_value = canonical_identity
    db = MagicMock(spec=AsyncSession)
    # Async execute returns explicit synchronous SQLAlchemy Result-style mocks.
    db.execute.side_effect = [mapping_result, identity_result]
    db.in_transaction.return_value = False
    db.scalar.return_value = False
    return db, mapping_result, identity_result


def legacy_access(**changes):
    return jwt.encode({**dict(sub="303", company_id=7, type="access",
                             exp=datetime.now(timezone.utc) + timedelta(minutes=5)), **changes},
                      SECRET, algorithm="HS256")


class LegacyFieldTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        setting = patch.object(legacy.Config, "SECRET_KEY", SECRET)
        setting.start()
        self.addCleanup(setting.stop)
        previous = legacy.tenant_context.set(None)
        self.addCleanup(legacy.tenant_context.reset, previous)

    def assert_request_owns_transaction(self, db):
        for name in ("commit", "rollback", "begin", "begin_nested", "flush", "add", "add_all", "delete"):
            getattr(db, name).assert_not_called()

    def assert_opaque(self, error):
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.detail, canonical._AUTH_REJECTION_DETAIL)
        self.assertEqual(error.headers, {"WWW-Authenticate": "Bearer"})
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)

    async def resolve(self, db, current=None):
        return await module.get_legacy_transport_field_context(
            current_driver=actor() if current is None else current, db=db,
        )

    async def test_field_only_returns_frozen_canonical_context_with_independent_ids(self):
        db, mapping_result, identity_result = database(bridge(), identity())
        context = await self.resolve(db)
        self.assertIsInstance(context, FieldRequestContext)
        self.assertEqual(context, FieldRequestContext(101, 7, 202, 13))
        self.assertEqual(context.channel.value, "FIELD")
        self.assertEqual(context.principal_type.value, "FIELD_REPRESENTATIVE")
        with self.assertRaises(FrozenInstanceError):
            context.principal_id = 303
        self.assertEqual(db.execute.await_count, 2)
        mapping_result.one_or_none.assert_called_once_with()
        identity_result.one_or_none.assert_called_once_with()
        self.assert_request_owns_transaction(db)
        db.connection.assert_not_called()

    async def test_dual_split_field_side_works_for_both_legacy_flags_without_label_authority(self):
        for flag in (False, True):
            with self.subTest(legacy_flag=flag):
                current = Driver(id=303, company_id=7, is_active=True, is_admin=flag)
                mapping = bridge(backoffice_principal_id=404, backoffice_user_id=505)
                db, _, _ = database(mapping, identity())
                self.assertEqual(await self.resolve(db, current), FieldRequestContext(101, 7, 202, 13))
                self.assert_request_owns_transaction(db)

    async def test_coincidentally_equal_ids_are_allowed_but_never_required(self):
        db, _, _ = database(bridge(field_principal_id=303, field_representative_id=303),
                            identity(principal_id=303, representative_id=303, representative_principal_id=303))
        self.assertEqual(await self.resolve(db), FieldRequestContext(303, 7, 303, 13))

    async def test_backoffice_only_missing_and_unpopulated_field_mapping_rejected_before_canonical_lookup(self):
        for mapping in (None, bridge(field_principal_id=None, field_representative_id=None),
                        bridge(field_principal_id=None), bridge(field_representative_id=None)):
            with self.subTest(mapping=mapping):
                db, _, identity_result = database(mapping, identity())
                current = Driver(id=303, company_id=7, is_active=True, is_admin=False)
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db, current)
                self.assert_opaque(rejected.exception)
                self.assertEqual(db.execute.await_count, 1)
                identity_result.one_or_none.assert_not_called()
                self.assert_request_owns_transaction(db)

    async def test_duplicate_bridge_or_canonical_result_is_rejected(self):
        for ambiguous in ("bridge", "identity"):
            with self.subTest(ambiguous=ambiguous):
                db, mapping_result, identity_result = database(bridge(), identity())
                (mapping_result if ambiguous == "bridge" else identity_result).one_or_none.side_effect = (
                    MultipleResultsFound("synthetic internal identity")
                )
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque(rejected.exception)
                self.assertEqual(db.execute.await_count, 1 if ambiguous == "bridge" else 2)
                self.assert_request_owns_transaction(db)

    async def test_missing_profile_or_principal_rejects_joined_identity(self):
        for absent in ("FieldRepresentative", "CompanyPrincipal"):
            with self.subTest(absent=absent):
                db, _, _ = database(bridge(), None)
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque(rejected.exception)
                self.assert_request_owns_transaction(db)

    async def test_mismatched_profile_principal_types_active_state_and_companies_are_rejected(self):
        invalid = (
            dict(representative_id=999), dict(representative_principal_id=999), dict(principal_id=999),
            dict(representative_type="BACKOFFICE"), dict(principal_type="BACKOFFICE"),
            dict(principal_active=False), dict(principal_active=None),
            dict(representative_company_id=8), dict(principal_company_id=8),
        )
        for change in invalid:
            with self.subTest(change=change):
                db, _, _ = database(bridge(), identity(**change))
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque(rejected.exception)
                self.assert_request_owns_transaction(db)

    async def test_foreign_bridge_or_wrong_operational_locator_rejected_before_canonical_lookup(self):
        for change in (dict(company_id=8), dict(legacy_driver_id=101), dict(legacy_driver_id=202)):
            with self.subTest(change=change):
                db, _, identity_result = database(bridge(**change), identity())
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque(rejected.exception)
                self.assertEqual(db.execute.await_count, 1)
                identity_result.one_or_none.assert_not_called()

    async def test_transport_ids_must_be_strict_positive_integers_before_any_query(self):
        for name in ("id", "company_id"):
            for bad in (None, 0, -1, True, False, "303", 303.0):
                with self.subTest(name=name, bad=bad):
                    db, _, _ = database(bridge(), identity())
                    with self.assertRaises(HTTPException) as rejected:
                        await self.resolve(db, actor(**{name: bad}))
                    self.assert_opaque(rejected.exception)
                    db.execute.assert_not_awaited()
                    self.assert_request_owns_transaction(db)

    async def test_bridge_and_canonical_ids_and_revision_are_strict_positive_integers(self):
        for name in ("company_id", "legacy_driver_id", "field_principal_id", "field_representative_id"):
            for bad in (None, 0, -1, True, "101", 101.0):
                with self.subTest(bridge_field=name, bad=bad):
                    db, _, _ = database(bridge(**{name: bad}), identity())
                    with self.assertRaises(HTTPException) as rejected:
                        await self.resolve(db)
                    self.assert_opaque(rejected.exception)
        for name in ("representative_company_id", "representative_id", "representative_principal_id",
                     "principal_company_id", "principal_id", "auth_revision"):
            for bad in (None, 0, -1, True, "13", 13.0):
                with self.subTest(canonical_field=name, bad=bad):
                    db, _, _ = database(bridge(), identity(**{name: bad}))
                    with self.assertRaises(HTTPException) as rejected:
                        await self.resolve(db)
                    self.assert_opaque(rejected.exception)

    async def test_revision_is_current_canonical_value_and_no_second_authentication_occurs(self):
        db, _, _ = database(bridge(), identity(auth_revision=37))
        with patch.object(legacy.jwt, "decode", side_effect=AssertionError("Transport already authenticated")) as decode, \
             patch.object(canonical, "decode_company_token", side_effect=AssertionError("No canonical token here")) as canonical_decode:
            self.assertEqual(await self.resolve(db), FieldRequestContext(101, 7, 202, 37))
        decode.assert_not_called()
        canonical_decode.assert_not_called()
        self.assert_request_owns_transaction(db)

    async def test_queries_use_exact_tenant_bridge_and_canonical_identity_without_sensitive_columns(self):
        db, _, _ = database(bridge(), identity())
        await self.resolve(db)
        mapping, linked = [call.args[0] for call in db.execute.await_args_list]
        self.assertEqual([column.name for column in mapping.selected_columns],
                         ["company_id", "legacy_driver_id", "field_principal_id", "field_representative_id"])
        self.assertEqual([(item.left.name, item.right.value) for item in mapping.whereclause.clauses],
                         [("company_id", 7), ("legacy_driver_id", 303)])
        predicates = list(linked.whereclause.clauses)
        self.assertEqual([(item.left.table.name, item.left.name, item.right.value) for item in predicates[:-1]], [
            ("field_representatives", "company_id", 7), ("field_representatives", "id", 202),
            ("field_representatives", "principal_id", 101),
            ("field_representatives", "principal_type", "FIELD_REPRESENTATIVE"),
            ("company_principals", "company_id", 7), ("company_principals", "id", 101),
            ("company_principals", "principal_type", "FIELD_REPRESENTATIVE"),
        ])
        joined = linked.get_final_froms()[0]
        self.assertEqual((joined.left.name, joined.right.name), ("field_representatives", "company_principals"))
        self.assertEqual([str(item) for item in joined.onclause.clauses], [
            "company_principals.company_id = field_representatives.company_id",
            "company_principals.id = field_representatives.principal_id",
        ])
        sql = str(linked.compile(dialect=postgresql.dialect()))
        self.assertIn("company_principals.is_active IS true", sql)
        for forbidden in ("classification", "is_admin", "password_hash", "username"):
            self.assertNotIn(forbidden, str(mapping.compile(dialect=postgresql.dialect())) + sql)

    async def test_mapping_persistence_and_result_errors_are_opaque_without_transaction_mutation(self):
        for stage in ("bridge", "canonical", "result"):
            with self.subTest(stage=stage):
                db, mapping_result, identity_result = database(bridge(), identity())
                failure = RuntimeError("synthetic SQL / bridge / principal internals")
                if stage == "bridge":
                    db.execute.side_effect = failure
                elif stage == "canonical":
                    db.execute.side_effect = [mapping_result, failure]
                else:
                    identity_result.one_or_none.side_effect = failure
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque(rejected.exception)
                self.assert_request_owns_transaction(db)

    def test_depends_uses_the_exact_legacy_transport_and_shared_request_session_with_cache(self):
        parameters = inspect.signature(module.get_legacy_transport_field_context).parameters
        self.assertEqual(list(parameters), ["current_driver", "db"])
        self.assertIs(parameters["current_driver"].default.dependency, legacy.get_current_driver)
        self.assertIs(parameters["db"].default.dependency, legacy.get_db)
        self.assertTrue(parameters["current_driver"].default.use_cache)
        self.assertTrue(parameters["db"].default.use_cache)

    def application(self, db):
        app, captured = FastAPI(), []

        async def request_db():
            return db

        async def legacy_first(current_driver=Depends(legacy.get_current_driver),
                               context=Depends(module.get_legacy_transport_field_context)):
            captured.append((current_driver, context))
            return dict(legacy_driver_id=current_driver.id, principal_id=context.principal_id,
                        representative_id=context.representative_id, auth_revision=context.auth_revision)

        async def context_first(context=Depends(module.get_legacy_transport_field_context),
                                current_driver=Depends(legacy.get_current_driver)):
            return await legacy_first(current_driver, context)

        app.dependency_overrides[legacy.get_db] = request_db
        app.add_api_route("/legacy-first", legacy_first)
        app.add_api_route("/context-first", context_first)
        return app, captured

    async def test_fastapi_cache_reuses_real_legacy_authentication_in_both_dependency_orders(self):
        current = actor()
        db, mapping_result, identity_result = database(bridge(), identity(auth_revision=37))
        authentication_result = Mock()
        authentication_result.one_or_none.return_value = (current, False)
        db.execute.side_effect = [authentication_result, mapping_result, identity_result] * 2
        app, captured = self.application(db)
        # Legacy transport claims are not canonical identity or revision authority.
        raw = legacy_access(role="Admin", is_admin=True, auth_revision=999)
        with patch.object(legacy.jwt, "decode", wraps=legacy.jwt.decode) as decode, \
             patch.object(canonical, "decode_company_token", side_effect=AssertionError("No duplicate decoder")) as canonical_decode:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://legacy-field.test") as client:
                for index, path in enumerate(("/legacy-first", "/context-first"), 1):
                    response = await client.get(path, headers={"Authorization": "Bearer " + raw})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), dict(legacy_driver_id=303, principal_id=101,
                                                          representative_id=202, auth_revision=37))
                    self.assertIs(captured[-1][0], current)
                    self.assertEqual(captured[-1][1], FieldRequestContext(101, 7, 202, 37))
                    self.assertEqual(decode.call_count, index)
                    self.assertEqual(authentication_result.one_or_none.call_count, index)
                    self.assertEqual(db.execute.await_count, index * 3)
                    self.assertEqual(db.connection.await_count, index)
            canonical_decode.assert_not_called()
        self.assert_request_owns_transaction(db)

    async def test_upstream_legacy_authentication_rejections_keep_their_original_responses(self):
        for reason in ("missing bearer", "expired", "disabled"):
            with self.subTest(reason=reason):
                db, mapping_result, identity_result = database(bridge(), identity())
                authentication_result = Mock()
                authentication_result.one_or_none.return_value = (actor(is_active=False), False)
                db.execute.side_effect = [authentication_result, mapping_result, identity_result]
                app, captured = self.application(db)
                raw = legacy_access(exp=datetime.now(timezone.utc) - timedelta(minutes=1)) if reason == "expired" else legacy_access()
                headers = {} if reason == "missing bearer" else {"Authorization": "Bearer " + raw}
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://legacy-field.test") as client:
                    response = await client.get("/legacy-first", headers=headers)
                self.assertEqual(response.status_code, 401 if reason == "expired" else 403)
                if reason == "disabled":
                    self.assertEqual(response.json()["detail"]["code"], "ACCOUNT_DISABLED")
                else:
                    self.assertEqual(response.json()["detail"], "Token is invalid or expired" if reason == "expired" else "Not authenticated")
                self.assertNotIn("www-authenticate", response.headers)
                self.assertEqual(captured, [])
                mapping_result.one_or_none.assert_not_called()
                identity_result.one_or_none.assert_not_called()
                self.assert_request_owns_transaction(db)


if __name__ == "__main__":
    unittest.main()
