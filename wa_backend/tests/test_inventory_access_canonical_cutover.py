"""Focused canonical access administration with real SQL/dependencies and mocked persistence."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SECRET = "InventoryOwnerCutoverSyntheticSecret123456789012345678901234567890"
with patch.dict(os.environ, {
    "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://access_unit@127.0.0.1:1/access_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://access_admin@127.0.0.1:1/access_unit",
}):
    from api import inventory_permissions as module
    from api import dependencies as legacy

from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from models import Driver, Role, SystemAuditLog


class AuditActor:
    id = 44

    @property
    def company_id(self):
        raise AssertionError("An audit FK must not provide company authority")

    @property
    def is_admin(self):
        raise AssertionError("An audit actor must not provide authorization")


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("A bridge classification must not provide identity authority")


def result(value=None, rows=()):
    synchronous = Mock()
    synchronous.one_or_none.return_value = value
    synchronous.scalar_one_or_none.return_value = value
    synchronous.all.return_value = list(rows)
    return synchronous


def database():
    db = MagicMock(spec=AsyncSession)
    db.in_transaction.return_value = False
    db.execute.return_value = result()
    db.scalars.return_value = result()
    return db


def access(db, owner=True):
    return BackofficeCapabilityAccess(db, BackofficeAuthorizationSubject(
        principal_id=11, backoffice_user_id=22, company_id=7,
        is_company_owner=owner, legacy_grant_driver_id=None if owner else 44,
    ))


def target_results(db, *, target=None, bridge=None):
    canonical = SimpleNamespace(company_id=7, principal_id=101, backoffice_user_id=202) if target is None else target
    mapping = Bridge(company_id=7, backoffice_principal_id=101, backoffice_user_id=202,
                     legacy_driver_id=303) if bridge is None else bridge
    db.execute.side_effect = [result(canonical), result(mapping)]


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class InventoryAccessCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    def assert_no_transaction_mutation(self, db):
        for name in ("commit", "rollback", "begin", "begin_nested", "flush", "add", "delete"):
            getattr(db, name).assert_not_called()

    async def test_owner_gate_allows_only_persisted_canonical_owner_subject(self):
        db = database()
        owner = access(db)
        self.assertIs(await module._require_company_owner(owner), owner)
        with self.assertRaises(HTTPException) as denied:
            await module._require_company_owner(access(db, owner=False))
        self.assertEqual((denied.exception.status_code, denied.exception.detail), (403, "Authorization denied."))
        self.assert_no_transaction_mutation(db)

    async def test_self_access_without_grants_succeeds_and_returns_only_canonical_identity(self):
        db = database()
        with patch.object(BackofficeCapabilityAccess, "require", new=AsyncMock(side_effect=AssertionError("Introspection must not require every permission"))) as require:
            response = await module.capabilities(location_id=None, db=db, access=access(db, owner=False))
        self.assertEqual(response, dict(company_id=7, principal_id=11, backoffice_user_id=22,
                                      is_company_owner=False, location_id=None,
                                      permissions=[], any_permissions=[], location_permissions=[]))
        require.assert_not_awaited()
        self.assertEqual(db.scalars.await_count, 2)
        self.assert_no_transaction_mutation(db)

    async def test_owner_has_complete_capabilities_and_foreign_locations_remain_closed(self):
        db = database()
        response = await module.capabilities(location_id=None, db=db, access=access(db))
        self.assertEqual(response["permissions"], sorted(PERMISSIONS))
        self.assertEqual(response["any_permissions"], sorted(PERMISSIONS))
        db.scalar.return_value = None
        with self.assertRaises(HTTPException) as denied:
            await module.capabilities(location_id=999, db=db, access=access(db))
        self.assertEqual(denied.exception.status_code, 403)
        self.assertIn("inventory_locations.company_id = 7", sql(db.scalar.await_args.args[0]))
        self.assert_no_transaction_mutation(db)

    async def test_location_introspection_uses_canonical_access_and_excludes_foreign_ids(self):
        db = database()
        db.scalars.return_value = result(rows=[501])
        response = await module.location_capabilities(module.LocationCapabilitiesInput(location_ids=[501, 999]), access(db))
        self.assertEqual(response, {"locations": {501: sorted(PERMISSIONS)}})
        self.assertIn("inventory_locations.company_id = 7", sql(db.scalars.await_args.args[0]))
        self.assert_no_transaction_mutation(db)

    async def test_user_listing_is_canonical_paginated_and_owner_relation_based(self):
        db = database()
        row = SimpleNamespace(backoffice_user_id=202, _mapping=dict(principal_id=101, backoffice_user_id=202,
                              full_name="Canonical User", is_active=False, is_company_owner=False))
        db.execute.return_value = result(rows=[row, SimpleNamespace(backoffice_user_id=203)])
        response = await module.users(after_id=200, limit=1, db=db, access=access(db))
        self.assertEqual(response, {"items": [row._mapping], "next_id": 202})
        query = sql(db.execute.await_args.args[0])
        for condition in ("backoffice_users.company_id = 7", "company_principals.company_id = 7",
                          "backoffice_users.id > 200", "company_owners.backoffice_user_id = backoffice_users.id"):
            self.assertIn(condition, query)
        self.assertNotIn("drivers.", query)
        self.assert_no_transaction_mutation(db)

    async def test_target_mapping_requires_exact_company_principal_profile_and_independent_legacy_id(self):
        db = database()
        target_results(db)
        self.assertEqual(await module.target_legacy_grant_driver_id(db, access(db), 202), 303)
        canonical, mapping = [call.args[0] for call in db.execute.await_args_list]
        self.assertIn("backoffice_users.company_id = 7", sql(canonical))
        self.assertIn("backoffice_users.id = 202", sql(canonical))
        self.assertIn("company_principals.principal_type = 'BACKOFFICE'", sql(canonical))
        for condition in ("company_id = 7", "backoffice_principal_id = 101", "backoffice_user_id = 202"):
            self.assertIn(condition, sql(mapping))
        self.assert_no_transaction_mutation(db)

    async def test_missing_cross_company_or_mismatched_targets_and_bridges_fail_before_writes(self):
        invalid = (
            (None, None, 404),
            (SimpleNamespace(company_id=8, principal_id=101, backoffice_user_id=202), None, 404),
            (SimpleNamespace(company_id=7, principal_id=101, backoffice_user_id=203), None, 404),
            (SimpleNamespace(company_id=7, principal_id=101, backoffice_user_id=202), None, 403),
            (SimpleNamespace(company_id=7, principal_id=101, backoffice_user_id=202),
             Bridge(company_id=8, backoffice_principal_id=101, backoffice_user_id=202, legacy_driver_id=303), 403),
            (SimpleNamespace(company_id=7, principal_id=101, backoffice_user_id=202),
             Bridge(company_id=7, backoffice_principal_id=999, backoffice_user_id=202, legacy_driver_id=303), 403),
        )
        for target, bridge, status in invalid:
            with self.subTest(status=status, target=target, bridge=bridge):
                db = database()
                db.execute.side_effect = [result(target), result(bridge)]
                with self.assertRaises(HTTPException) as rejected:
                    await module.target_legacy_grant_driver_id(db, access(db), 202)
                self.assertEqual(rejected.exception.status_code, status)
                self.assert_no_transaction_mutation(db)

    async def test_grant_uses_locator_only_for_storage_and_cached_actor_only_for_audit(self):
        for location_id in (None, 501):
            with self.subTest(location=location_id):
                db = database()
                target_results(db)
                role = SimpleNamespace(id=909)
                db.scalar.side_effect = [role, 777] if location_id is None else [role, 501, 777]
                response = await module.grant(202, module.GrantInput(role_id=909, location_id=location_id), db, access(db), AuditActor())
                self.assertEqual(response, {"created": True})
                statement = db.scalar.await_args.args[0]
                values = statement.compile().params
                self.assertEqual((values["company_id"], values["driver_id"], values["role_id"]), (7, 303, 909))
                self.assertIn("ON CONFLICT DO NOTHING", sql(statement))
                if location_id is not None:
                    validation = sql(db.scalar.await_args_list[1].args[0])
                    self.assertIn("inventory_locations.company_id = 7", validation)
                    self.assertIn("inventory_locations.is_active IS true", validation)
                    self.assertIn("'WAREHOUSE', 'VEHICLE'", validation)
                audit = db.add.call_args.args[0]
                self.assertIsInstance(audit, SystemAuditLog)
                self.assertEqual((audit.company_id, audit.admin_id, audit.target_id), (7, 44, "BackofficeUser_202"))
                db.commit.assert_awaited_once_with()
                db.rollback.assert_not_called()
                db.begin.assert_not_called()

    async def test_duplicate_grant_commits_without_duplicate_audit(self):
        db = database()
        target_results(db)
        db.scalar.side_effect = [SimpleNamespace(id=909), None]
        self.assertEqual(await module.grant(202, module.GrantInput(role_id=909), db, access(db), AuditActor()), {"created": False})
        db.add.assert_not_called()
        db.commit.assert_awaited_once_with()

    async def test_missing_role_and_invalid_or_inactive_location_prevent_grant_writes(self):
        for role in (None, SimpleNamespace(id=909)):
            db = database()
            target_results(db)
            db.scalar.side_effect = [None] if role is None else [role, None]
            with self.assertRaises(HTTPException) as rejected:
                await module.grant(202, module.GrantInput(role_id=909, location_id=501), db, access(db), AuditActor())
            self.assertEqual(rejected.exception.status_code, 404)
            self.assert_no_transaction_mutation(db)

    async def test_list_and_revoke_grants_use_legacy_storage_id_after_canonical_validation(self):
        for scope, table in (("company", "user_roles"), ("location", "user_location_access")):
            with self.subTest(scope=scope):
                db = database()
                target_results(db)
                db.scalars.return_value = result(rows=[SimpleNamespace(id=777, role_id=909, location_id=501)])
                await module.user_grants(202, scope, 0, 50, db, access(db))
                query = sql(db.scalars.await_args.args[0])
                self.assertIn(f"{table}.driver_id = 303", query)
                self.assertIn(f"{table}.company_id = 7", query)
                self.assert_no_transaction_mutation(db)
                db = database()
                target_results(db)
                row = SimpleNamespace(id=777, role_id=909, location_id=501)
                db.scalar.return_value = row
                self.assertEqual(await module.revoke(202, 777, scope, db, access(db), AuditActor()), {"revoked": True})
                query = sql(db.scalar.await_args.args[0])
                self.assertIn(f"{table}.driver_id = 303", query)
                self.assertIn("FOR UPDATE", query)
                db.delete.assert_awaited_once_with(row)
                self.assertEqual(db.add.call_args.args[0].admin_id, 44)
                db.commit.assert_awaited_once_with()

    async def test_unknown_codes_blank_names_system_roles_and_duplicate_names_are_rejected(self):
        for name, codes in (("Role", ["authorization.manage"]), (" ", ["inventory.read"])):
            db = database()
            with self.assertRaises(HTTPException) as rejected:
                await module.save_role(module.RoleInput(name=name, permissions=codes), db, access(db), AuditActor())
            self.assertEqual(rejected.exception.status_code, 422)
            db.execute.assert_not_awaited()
            self.assert_no_transaction_mutation(db)
        for system in (True, False):
            db = database()
            role = SimpleNamespace(id=909, name="Existing", is_system_role=system)
            db.scalar.side_effect = [role] if system else [role, 910]
            with self.assertRaises(HTTPException) as rejected:
                await module.save_role(module.RoleInput(name="Duplicate", permissions=[]), db, access(db), AuditActor(), 909)
            self.assertEqual(rejected.exception.status_code, 409)
            self.assertIn("pg_advisory_xact_lock", sql(db.execute.await_args_list[0].args[0]))
            self.assert_no_transaction_mutation(db)

    async def test_role_creation_retains_lock_canonical_code_validation_and_audit(self):
        db = database()
        db.scalar.return_value = None
        db.scalars.return_value = result(rows=[5001])

        async def assign_role_id():
            db.add.call_args_list[0].args[0].id = 909

        db.flush.side_effect = assign_role_id
        response = await module.save_role(module.RoleInput(name="Receiving", permissions=["inventory.read"]), db, access(db), AuditActor())
        self.assertEqual(response, {"id": 909, "name": "Receiving", "permissions": ["inventory.read"]})
        role, audit = [call.args[0] for call in db.add.call_args_list]
        self.assertIsInstance(role, Role)
        self.assertFalse(role.is_system_role)
        self.assertEqual((role.company_id, audit.company_id, audit.admin_id), (7, 7, 44))
        lock = db.execute.await_args_list[0].args[0]
        lock_values = lock.compile().params.values()
        self.assertIn(7, lock_values)
        self.assertIn("inventory-rbac", lock_values)
        self.assertIn("pg_advisory_xact_lock", sql(lock))
        self.assertIn("inventory-rbac", sql(lock))
        self.assertIn("ON CONFLICT", sql(db.execute.await_args_list[1].args[0]))
        db.commit.assert_awaited_once_with()
        db.rollback.assert_not_called()

    async def test_company_only_capabilities_remain_excluded_from_local_grants(self):
        db = database()
        ordinary = access(db, owner=False)
        await ordinary.codes(501)
        query = sql(db.scalars.await_args.args[0])
        self.assertIn("permission", query)
        self.assertIn("NOT IN", query)
        self.assertIn("catalog.manage", query)
        self.assertIn("catalog.manage", COMPANY_ONLY)

    async def test_real_fastapi_owner_transport_flags_cache_and_missing_identity(self):
        from datetime import datetime, timedelta, timezone
        setting = patch.object(legacy.Config, "SECRET_KEY", SECRET)
        previous = legacy.tenant_context.set(None)
        self.addCleanup(legacy.tenant_context.reset, previous)
        with setting:
            for owner, flag, missing, wrong_channel in ((True, False, False, False), (True, True, False, False),
                    (False, True, False, False), (False, False, False, False),
                    (False, True, True, False), (False, True, False, True)):
                with self.subTest(owner=owner, operational_flag=flag, missing=missing, wrong_channel=wrong_channel):
                    db = database()
                    actor = Driver(id=44, company_id=7, is_active=True, is_admin=flag)
                    auth_result = result((actor, False))
                    db.execute.return_value = auth_result
                    bridge = Bridge(company_id=7, legacy_driver_id=44, backoffice_principal_id=11, backoffice_user_id=22)
                    principal = SimpleNamespace(id=11, company_id=7,
                        principal_type="FIELD_REPRESENTATIVE" if wrong_channel else "BACKOFFICE", is_active=True, auth_revision=3)
                    profile = SimpleNamespace(id=22, company_id=7, principal_id=11, principal_type="BACKOFFICE")
                    persisted_owner = SimpleNamespace(company_id=7, backoffice_user_id=22 if owner else 99)
                    db.scalar.side_effect = [None] if missing else [bridge, principal, profile, persisted_owner, bridge]
                    app = FastAPI()
                    app.include_router(module.router)

                    async def override_db():
                        return db

                    app.dependency_overrides[get_db] = override_db
                    token = jwt.encode(dict(sub="44", company_id=7, type="access", role="Owner", is_admin=True,
                                            exp=datetime.now(timezone.utc) + timedelta(minutes=5)), SECRET, algorithm="HS256")
                    with patch.object(legacy.jwt, "decode", wraps=jwt.decode) as decode, \
                         patch.object(module, "save_role", new=AsyncMock(return_value={"id": 909})) as save:
                        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                            response = await client.post("/inventory/access/roles", json={"name": "Role", "permissions": []},
                                                         headers={"Authorization": f"Bearer {token}"})
                    self.assertEqual(response.status_code, 401 if missing or wrong_channel else 201 if owner else 403, response.text)
                    decode.assert_called_once()
                    auth_result.one_or_none.assert_called_once_with()
                    self.assertEqual(db.execute.await_count, 1)
                    if owner:
                        passed_access, passed_actor = save.await_args.args[2:4]
                        self.assertEqual((passed_access.subject.principal_id, passed_access.subject.backoffice_user_id), (11, 22))
                        self.assertIs(passed_actor, actor)
                    else:
                        save.assert_not_awaited()
                        if not missing and not wrong_channel:
                            self.assertEqual(response.json()["detail"], "Authorization denied.")


if __name__ == "__main__":
    unittest.main()
