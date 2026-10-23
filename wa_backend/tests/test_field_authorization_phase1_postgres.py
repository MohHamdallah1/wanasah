"""Real migrated PostgreSQL proof for the FIELD persisted foundation only."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from domains.authorization.capabilities import FIELD_ASSIGNABLE_PERMISSIONS, PERMISSIONS
from domains.authorization.field_models import FieldRepresentativeRole
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from models import Base

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = "9c4f8a2d7e31"
REVISION = "fa6c1e8d2b73"
KEY = "FIELD_REPRESENTATIVE_V1"
EXPECTED = {
    "work_session.read", "work_session.execute", "visit.read", "visit.execute",
    "inventory.read", "transfer.read", "transfer.receive", "transfer.reject",
    "catalog.read", "pricing.view", "reconciliation.execute", "shop.create",
}
pytestmark = pytest.mark.skipif(os.getenv("WANASAH_FIELD_AUTH_PHASE1_GATE") != "1",
                               reason="dedicated migrated FIELD authorization database only")


def url(name, *, driver="postgresql"):
    value = make_url(os.environ[name])
    assert value.database == "field_auth_phase1_gate"
    return value.set(drivername=driver).render_as_string(hide_password=False)


def alembic(*args):
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, check=True)


def data_module():
    spec = importlib.util.spec_from_file_location("field_phase1_migration",
        ROOT / "alembic/versions/fa6c1e8d2b73_field_authorization_foundation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rerun_data():
    engine = create_engine(url("DATABASE_URL_MIGRATION", driver="postgresql+psycopg"))
    try:
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                data_module()._provision_and_backfill()
    finally:
        engine.dispose()


def company(db, code):
    return db.execute("""
        INSERT INTO companies(name,company_code,is_active,subscription_status,currency_code,timezone,created_at)
        VALUES (%s,%s,true,'active','JOD','UTC',CURRENT_TIMESTAMP) RETURNING id
    """, (code, code)).fetchone()[0]


def profile(db, tenant, *, principal_id, representative_id, active=True):
    db.execute("""
        INSERT INTO company_principals(id,company_id,username,password_hash,full_name,principal_type,is_active)
        VALUES (%s,%s,%s,'synthetic-not-for-login','FIELD foundation','FIELD_REPRESENTATIVE',%s)
    """, (principal_id, tenant, "field-" + str(principal_id), active))
    db.execute("INSERT INTO field_representatives(id,company_id,principal_id) VALUES (%s,%s,%s)",
               (representative_id, tenant, principal_id))


def backoffice_snapshot(db):
    return (
        db.execute("SELECT company_id,id,name,is_system_role FROM roles ORDER BY id").fetchall(),
        db.execute("SELECT company_id,role_id,permission_id FROM role_permissions ORDER BY 1,2,3").fetchall(),
        db.execute("SELECT company_id,driver_id,role_id FROM user_roles ORDER BY 1,2,3").fetchall(),
        db.execute("SELECT company_id,driver_id,location_id,role_id FROM user_location_access ORDER BY 1,2,3,4").fetchall(),
    )


@pytest.fixture(scope="module")
def gate():
    # Fresh workflow-owned service only. Never reset/drop an existing database.
    alembic("upgrade", PREVIOUS)
    with psycopg.connect(url("DATABASE_URL_MIGRATION"), autocommit=True) as db:
        assert db.execute("SELECT to_regclass('field_representative_roles')").fetchone()[0] is None
        with db.transaction():
            a, b, empty = (company(db, code) for code in ("FIELD-P1-A", "FIELD-P1-B", "FIELD-P1-EMPTY"))
            profile(db, a, principal_id=31001, representative_id=21001)
            profile(db, a, principal_id=31002, representative_id=21002, active=False)
            profile(db, a, principal_id=31003, representative_id=21003)
            profile(db, b, principal_id=32001, representative_id=22001)
            db.execute("""
                INSERT INTO company_principals(id,company_id,username,password_hash,full_name,principal_type)
                VALUES (41001,%s,'office-dual','synthetic','Backoffice','BACKOFFICE')
            """, (a,))
            db.execute("INSERT INTO backoffice_users(id,company_id,principal_id) VALUES (51001,%s,41001)", (a,))
            db.execute("""
                INSERT INTO drivers(id,company_id,username,password_hash,full_name,is_active,created_at)
                VALUES (11001,%s,'operational-dual','synthetic','Operational',true,CURRENT_TIMESTAMP)
            """, (a,))
            db.execute("""
                INSERT INTO identity_legacy_driver_map(company_id,legacy_driver_id,classification,
                    backoffice_principal_id,backoffice_user_id,field_principal_id,field_representative_id)
                VALUES (%s,11001,'DUAL_SPLIT',41001,51001,31001,21001)
            """, (a,))
            office_role = db.execute("""
                INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,'Backoffice management',false)
                RETURNING id
            """, (a,)).fetchone()[0]
            legacy_system = db.execute("""
                INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,'Existing Backoffice system',true)
                RETURNING id
            """, (a,)).fetchone()[0]
            db.execute("""
                INSERT INTO role_permissions(company_id,role_id,permission_id)
                SELECT %s,%s,id FROM permissions WHERE code IN ('catalog.manage','inventory.read')
            """, (a, office_role))
            db.execute("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (%s,11001,%s)",
                       (a, office_role))
            before = backoffice_snapshot(db)
        alembic("upgrade", "head")
        alembic("upgrade", "head")
        alembic("check")
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
        after = backoffice_snapshot(db)
        for old, new in zip(before, after):
            assert set(old) <= set(new), (old, new)
        assert after[2:] == before[2:]  # No Backoffice assignment/warehouse grant changes.
        roles = dict(db.execute("SELECT company_id,id FROM roles WHERE system_key=%s", (KEY,)).fetchall())
        assert set(roles) == {a, b, empty}
        grants = set(db.execute(
            "SELECT company_id,field_representative_id,role_id FROM field_representative_roles"
        ).fetchall())
        assert grants == {(a,21001,roles[a]),(a,21002,roles[a]),(a,21003,roles[a]),(b,22001,roles[b])}
        assert db.execute("SELECT count(*) FROM roles WHERE id=%s AND system_key IS NULL AND is_system_role",
                          (legacy_system,)).fetchone()[0] == 1
        yield dict(a=a, b=b, empty=empty, roles=roles, office_role=office_role)


@pytest.fixture
def db(gate):
    with psycopg.connect(url("DATABASE_URL_MIGRATION"), autocommit=True) as conn:
        with conn.transaction(force_rollback=True):
            yield conn


@pytest.fixture
def runtime(gate):
    with psycopg.connect(url("DATABASE_URL"), autocommit=True) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute("SELECT set_config('app.current_tenant', %s, true)", (str(gate["a"]),))
            yield conn


def rejected(db, sql, args=(), code="23503"):
    with pytest.raises(psycopg.Error) as caught:
        with db.transaction():
            db.execute(sql, args)
    assert caught.value.sqlstate == code


def field_codes(db, tenant, representative):
    return {row[0] for row in db.execute("""
        SELECT p.code FROM field_representative_roles f
        JOIN role_permissions rp ON rp.company_id=f.company_id AND rp.role_id=f.role_id
        JOIN permissions p ON p.id=rp.permission_id
        WHERE f.company_id=%s AND f.field_representative_id=%s
    """, (tenant, representative))}


def test_catalog_default_roles_and_model_parity(gate, db):
    assert len(FIELD_ASSIGNABLE_PERMISSIONS) == 12
    assert FIELD_ASSIGNABLE_PERMISSIONS == EXPECTED <= PERMISSIONS
    assert set(data_module().FIELD_CODES) == EXPECTED
    assert {row[0] for row in db.execute("SELECT code FROM permissions")} >= PERMISSIONS
    for tenant, role in gate["roles"].items():
        codes = {r[0] for r in db.execute("""
            SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id=rp.permission_id
            WHERE rp.company_id=%s AND rp.role_id=%s
        """, (tenant, role))}
        assert codes == EXPECTED
    # Authentication active-state enforcement remains separate; inactive profiles
    # are not accidentally locked out of future legitimate reactivation.
    assert field_codes(db, gate["a"], 21001) == EXPECTED
    assert field_codes(db, gate["a"], 21002) == EXPECTED
    table = FieldRepresentativeRole.__table__
    assert set(table.c.keys()) == {"company_id","field_representative_id","role_id","created_at"}
    assert {fk.column.table.name for fk in table.foreign_keys} == {"companies","field_representatives","roles"}
    actual = {r[0] for r in db.execute("""
        SELECT conname FROM pg_constraint WHERE conrelid='field_representative_roles'::regclass
    """)}
    assert actual == {str(c.name) for c in table.constraints}


@pytest.mark.parametrize("subject,company_side,role_side", [
    (22001, "a", "a"), (21001, "a", "b"), (21001, "b", "b"),
    (11001, "a", "a"), (31001, "a", "a"), (51001, "a", "a"),
])
def test_fk_rejects_foreign_profiles_roles_and_legacy_aliases(gate, db, subject, company_side, role_side):
    rejected(db, "INSERT INTO field_representative_roles(company_id,field_representative_id,role_id) VALUES (%s,%s,%s)",
             (gate[company_side], subject, gate["roles"][gate[role_side]]))


def test_same_company_assignment_uniqueness_and_independent_roles(gate, runtime):
    custom = runtime.execute("""
        INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,'FIELD custom safe',false) RETURNING id
    """, (gate["a"],)).fetchone()[0]
    runtime.execute("INSERT INTO field_representative_roles(company_id,field_representative_id,role_id) VALUES (%s,21001,%s)",
                    (gate["a"], custom))
    rejected(runtime, "INSERT INTO field_representative_roles(company_id,field_representative_id,role_id) VALUES (%s,21001,%s)",
             (gate["a"], custom), "23505")


def test_rls_force_privileges_and_missing_context_fail_closed(gate, db, runtime):
    assert db.execute("""
        SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='field_representative_roles'::regclass
    """).fetchone() == (True, True)
    policies = db.execute("SELECT permissive,qual,with_check FROM pg_policies WHERE tablename='field_representative_roles'").fetchall()
    assert len(policies) == 2 and {p[0] for p in policies} == {"PERMISSIVE","RESTRICTIVE"}
    assert all("app.current_tenant" in p[1] and "app.current_tenant" in p[2] for p in policies)
    who = runtime.execute("SELECT current_user").fetchone()[0]
    assert runtime.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False)
    assert runtime.execute("SELECT has_table_privilege(%s,'field_representative_roles','SELECT,INSERT,DELETE')", (who,)).fetchone()[0]
    for privilege in ("UPDATE","TRUNCATE","TRIGGER","REFERENCES"):
        assert not runtime.execute("SELECT has_table_privilege(%s,'field_representative_roles',%s)", (who,privilege)).fetchone()[0]
    assert {r[0] for r in runtime.execute("SELECT DISTINCT company_id FROM field_representative_roles")} == {gate["a"]}
    rejected(runtime, "INSERT INTO field_representative_roles(company_id,field_representative_id,role_id) VALUES (%s,22001,%s)",
             (gate["b"],gate["roles"][gate["b"]]), "42501")
    assert runtime.execute("DELETE FROM field_representative_roles WHERE company_id=%s", (gate["b"],)).rowcount == 0
    runtime.execute("SELECT set_config('app.current_tenant','',true)")
    assert runtime.execute("SELECT count(*) FROM field_representative_roles").fetchone()[0] == 0
    rejected(runtime, "INSERT INTO field_representative_roles(company_id,field_representative_id,role_id) VALUES (%s,21001,%s)",
             (gate["a"],gate["office_role"]), "42501")


@pytest.mark.parametrize("mutation", [
    "UPDATE roles SET name='changed' WHERE id=%s",
    "UPDATE roles SET system_key=NULL WHERE id=%s",
    "UPDATE roles SET is_system_role=false WHERE id=%s",
    "DELETE FROM roles WHERE id=%s",
])
def test_default_role_identity_is_immutable(gate, runtime, mutation):
    rejected(runtime, mutation, (gate["roles"][gate["a"]],), "42501")


def test_role_system_key_uniqueness_shape_and_no_promotion(gate, runtime):
    rejected(runtime, "INSERT INTO roles(company_id,name,is_system_role,system_key) VALUES (%s,'duplicate',true,%s)",
             (gate["a"],KEY), "23505")
    rejected(runtime, "INSERT INTO roles(company_id,name,is_system_role,system_key) VALUES (%s,'bad',false,%s)",
             (gate["a"],KEY), "23514")
    rejected(runtime, "INSERT INTO roles(company_id,name,is_system_role,system_key) VALUES (%s,'unknown',true,'OTHER')",
             (gate["a"],), "23514")
    rejected(runtime, "UPDATE roles SET system_key=%s,is_system_role=true WHERE id=%s",
             (KEY, gate["office_role"]), "42501")
    for name in ("ordinary null 1","ordinary null 2"):
        runtime.execute("INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,%s,false)", (gate["a"],name))


@pytest.mark.parametrize("sql", [
    "DELETE FROM role_permissions WHERE company_id=%s AND role_id=%s",
    "UPDATE role_permissions SET permission_id=permission_id WHERE company_id=%s AND role_id=%s",
    "INSERT INTO role_permissions(company_id,role_id,permission_id) SELECT %s,%s,id FROM permissions WHERE code='catalog.manage'",
])
def test_default_permissions_cannot_change(gate, runtime, sql):
    rejected(runtime, sql, (gate["a"], gate["roles"][gate["a"]]), "42501")


def test_catalog_identity_cannot_reinterpret_default_grants(runtime):
    rejected(runtime, "UPDATE permissions SET code='field.hijacked' WHERE code='visit.read'", code="42501")
    rejected(runtime, "DELETE FROM permissions WHERE code='visit.read'", code="42501")


def test_new_system_role_requires_complete_bundle_at_commit(gate, db):
    tenant = company(db, "FIELD-P1-INCOMPLETE")
    with pytest.raises(psycopg.Error) as caught:
        with db.transaction():
            db.execute("INSERT INTO roles(company_id,name,is_system_role,system_key) "
                       "VALUES (%s,'FIELD_REPRESENTATIVE_V1',true,%s)", (tenant,KEY))
            db.execute("SET CONSTRAINTS field_system_role_exact_bundle IMMEDIATE")
    assert caught.value.sqlstate == "23514"


def test_new_company_can_provision_exact_bundle_atomically(gate, db):
    tenant = company(db, "FIELD-P1-NEW")
    role = db.execute("""
        INSERT INTO roles(company_id,name,is_system_role,system_key) VALUES (%s,'FIELD_REPRESENTATIVE_V1',true,%s) RETURNING id
    """, (tenant,KEY)).fetchone()[0]
    db.execute("""
        INSERT INTO role_permissions(company_id,role_id,permission_id)
        SELECT %s,%s,id FROM permissions WHERE code=ANY(%s)
    """, (tenant,role,sorted(EXPECTED)))
    db.execute("SET CONSTRAINTS field_system_role_exact_bundle IMMEDIATE")


def test_backfill_repeat_and_upgrade_never_regrant_revoked_assignment(gate):
    with psycopg.connect(url("DATABASE_URL_MIGRATION"), autocommit=True) as db:
        with db.transaction():
            db.execute("DELETE FROM field_representative_roles WHERE company_id=%s AND field_representative_id=21003", (gate["a"],))
        # A genuinely new profile after the snapshot is not opportunistically
        # claimed by rerunning migration data; Phase 2 creation must grant it.
        with db.transaction():
            profile(db, gate["a"], principal_id=31004, representative_id=21004)
        rerun_data()
        rerun_data()
        alembic("upgrade", "head")
        assert db.execute("""
            SELECT count(*) FROM field_representative_roles
            WHERE company_id=%s AND field_representative_id IN (21003,21004)
        """, (gate["a"],)).fetchone()[0] == 0
        assert field_codes(db,gate["a"],21001) == EXPECTED


def test_backfill_name_collision_fails_without_adopting_or_partial_grants(gate):
    with psycopg.connect(url("DATABASE_URL_MIGRATION"), autocommit=True) as db:
        tenant = company(db, "FIELD-P1-COLLISION")
        role = db.execute("""
            INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,%s,false) RETURNING id
        """, (tenant,KEY)).fetchone()[0]
        with pytest.raises(Exception):
            rerun_data()
        assert db.execute("SELECT system_key,is_system_role FROM roles WHERE id=%s", (role,)).fetchone() == (None,False)
        assert db.execute("SELECT count(*) FROM role_permissions WHERE role_id=%s", (role,)).fetchone()[0] == 0


def test_dual_split_backoffice_and_field_grants_remain_independent(gate, db):
    assert field_codes(db,gate["a"],21001) == EXPECTED
    assert "catalog.manage" not in field_codes(db,gate["a"],21001)
    async def check():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                await session.execute(text("SELECT set_config('app.current_tenant', :tenant, true)"),
                                      {"tenant":str(gate["a"])})
                subject = BackofficeAuthorizationSubject(principal_id=41001, backoffice_user_id=51001,
                    company_id=gate["a"], is_company_owner=False, legacy_grant_driver_id=11001)
                access = BackofficeCapabilityAccess(session, subject)
                assert set(await access.codes()) == {"catalog.manage","inventory.read"}
                await access.require("catalog.manage")
                from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
                with pytest.raises(BackofficeCapabilityAccessRejected):
                    await access.require("visit.execute")
        finally:
            await engine.dispose()
    asyncio.run(check())
    db.execute("DELETE FROM user_roles WHERE company_id=%s AND driver_id=11001", (gate["a"],))
    assert field_codes(db,gate["a"],21001) == EXPECTED
    db.execute("DELETE FROM field_representative_roles WHERE company_id=%s AND field_representative_id=21001", (gate["a"],))
    assert db.execute("SELECT count(*) FROM role_permissions WHERE company_id=%s AND role_id=%s",
                      (gate["a"],gate["office_role"])).fetchone()[0] == 2


def test_forward_only_preserves_revocation_marker():
    with pytest.raises(RuntimeError, match="forward-only"):
        data_module().downgrade()

def test_force_rls_applies_even_to_restricted_table_owner(gate, db):
    db.execute("ALTER TABLE field_representative_roles OWNER TO field_auth_runtime")
    db.execute("SET LOCAL ROLE field_auth_runtime")
    db.execute("SELECT set_config('app.current_tenant','',true)")
    assert db.execute("SELECT count(*) FROM field_representative_roles").fetchone()[0] == 0
    db.execute("SELECT set_config('app.current_tenant',%s,true)", (str(gate["a"]),))
    assert {row[0] for row in db.execute("SELECT DISTINCT company_id FROM field_representative_roles")} == {gate["a"]}
    db.execute("RESET ROLE")
