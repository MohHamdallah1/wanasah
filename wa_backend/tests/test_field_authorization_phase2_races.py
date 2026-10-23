"""Real PostgreSQL interleavings over separate restricted runtime connections."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event
import time
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url

from tests.field_authorization_phase2_fixture import gate

pytestmark=pytest.mark.skipif(os.getenv("WANASAH_FIELD_AUTH_PHASE2_GATE")!="1",reason="isolated migrated Phase 2 gate")


def url(admin=False):
    value=make_url(os.environ["DATABASE_URL_MIGRATION" if admin else "DATABASE_URL"])
    assert value.database=="field_auth_phase2_gate"
    return value.set(drivername="postgresql").render_as_string(hide_password=False)


def permission(db,code):
    return db.execute("SELECT id FROM permissions WHERE code=%s",(code,)).fetchone()[0]


def seed_role(tenant):
    with psycopg.connect(url(True),autocommit=True) as db:
        with db.transaction():
            role=db.execute("INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,%s,false) RETURNING id",
                (tenant,"race-"+uuid4().hex)).fetchone()[0]
            db.execute("INSERT INTO role_permissions(company_id,role_id,permission_id) VALUES (%s,%s,%s)",
                (tenant,role,permission(db,"visit.execute")))
        return role


def write(db,g,role,grant):
    if grant:
        db.execute("INSERT INTO field_representative_roles(company_id,field_representative_id,role_id) VALUES (%s,%s,%s)",
                   (g.a,g.rep,role))
    else:
        db.execute("INSERT INTO role_permissions(company_id,role_id,permission_id) VALUES (%s,%s,%s)",
                   (g.a,role,permission(db,"catalog.manage")))


@pytest.mark.parametrize("grant_first",[True,False])
@pytest.mark.parametrize("isolation",["READ COMMITTED","REPEATABLE READ"])
def test_grant_and_permission_edit_race_cannot_commit_unsafe_bundle(gate,grant_first,isolation):
    g=gate
    role=seed_role(g.a)
    ready=Event()
    app="field-p2-race-"+uuid4().hex
    def second():
        try:
            with psycopg.connect(url(),autocommit=True,application_name=app) as db:
                with db.transaction():
                    db.execute("SET TRANSACTION ISOLATION LEVEL "+isolation)
                    db.execute("SELECT set_config('app.current_tenant',%s,true)",(str(g.a),))
                    db.execute("SET LOCAL statement_timeout='15000ms'")
                    db.execute("SELECT count(*) FROM role_permissions WHERE company_id=%s",(g.a,)).fetchone()
                    ready.set()
                    write(db,g,role,not grant_first)
            return "committed"
        except psycopg.Error as exc:
            return exc.sqlstate
    with psycopg.connect(url(),autocommit=True) as first, psycopg.connect(url(True),autocommit=True) as admin:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first.execute("BEGIN")
            try:
                first.execute("SELECT set_config('app.current_tenant',%s,true)",(str(g.a),))
                write(first,g,role,grant_first)
                future=pool.submit(second)
                assert ready.wait(8),"Second transaction did not start"
                deadline=time.monotonic()+8
                blocked=False
                while time.monotonic()<deadline:
                    row=admin.execute("SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s",(app,)).fetchone()
                    if row and row[0]=="Lock":
                        blocked=True
                        break
                    time.sleep(0.02)
                assert blocked,"Concurrent writer did not wait on policy serialization"
                first.execute("COMMIT")
            finally:
                first.execute("ROLLBACK")
            outcome=future.result(timeout=20)
            assert outcome in {"42501","40001"},outcome
        assert admin.execute("""
            SELECT count(*) FROM field_representative_roles f
            JOIN role_permissions rp ON rp.company_id=f.company_id AND rp.role_id=f.role_id
            JOIN permissions p ON p.id=rp.permission_id
            WHERE f.company_id=%s AND f.role_id=%s AND p.code='catalog.manage'
        """,(g.a,role)).fetchone()[0]==0


def test_direct_sql_update_cannot_escalate_field_assigned_role(gate):
    g=gate
    role=seed_role(g.a)
    with psycopg.connect(url(),autocommit=True) as db:
        with db.transaction(force_rollback=True):
            db.execute("SELECT set_config('app.current_tenant',%s,true)",(str(g.a),))
            write(db,g,role,True)
            with pytest.raises(psycopg.Error) as caught:
                with db.transaction():
                    db.execute("UPDATE role_permissions SET permission_id=%s WHERE company_id=%s AND role_id=%s",
                        (permission(db,"catalog.manage"),g.a,role))
            assert caught.value.sqlstate=="42501"
