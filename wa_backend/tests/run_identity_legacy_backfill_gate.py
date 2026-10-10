"""Frozen Phase 3/4 gate in a NEW synthetic localhost PostgreSQL 16 cluster.

No existing DB URL is accepted, no developer .env is read, no packages installed.
Run from wa_backend: python tests/run_identity_legacy_backfill_gate.py --run
"""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

import psycopg
from psycopg import sql

import run_identity_schema_expand_gate as fixture_tools

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "a4d2e7c9b630"
PREVIOUS = "e9c4b1a7d620"
BRIDGE = "identity_legacy_driver_map"
IDENTITY = ("company_principals", "backoffice_users", "field_representatives", "company_owners")
ADMIN, RUNTIME, DATABASE = "identity_backfill_admin", "identity_backfill_runtime", "identity_backfill_test"
# Synthetic values only; assert that none occurs in operator output.
SECRET = "synthetic-hash-do-not-report-Phase34"


def legacy_data(conn):
    tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    digest = hashlib.sha256()
    for (table,) in tables:
        if table in (*IDENTITY, BRIDGE, "alembic_version"):
            continue
        rows = conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(table))).fetchall()
        digest.update(json.dumps([table, rows], sort_keys=True, default=str).encode())
    return digest.hexdigest()


def empty_targets(conn):
    assert all(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0 for table in (*IDENTITY, BRIDGE))


def seed(conn):
    a, b = fixture_tools.company(conn, "BACKFILL-A"), fixture_tools.company(conn, "BACKFILL-B")
    drivers = {}
    specs = [(a, "owner", True, True, False, "0.000"), (a, "field", False, True, True, "321.123"),
             (a, "dual", True, True, True, "456.789"), (a, "granted", False, True, False, "0.000"),
             (a, "weak", False, False, True, "999.999"), (b, "owner", True, True, False, "0.000"),
             (b, "field", False, True, False, "0.000")]
    for company_id, username, admin, active, debt, limit in specs:
        driver_id = conn.execute(
            "INSERT INTO drivers(company_id,username,password_hash,full_name,phone_number,is_admin,is_active,can_allow_debt,max_debt_limit,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) RETURNING id",
            (company_id, username, SECRET, "Synthetic " + username, "+96200000", admin, active, debt, limit),
        ).fetchone()[0]
        drivers[(company_id, username)] = driver_id
    # Generate visibly independent IDs through each table's normal sequence.
    for table, value in zip(IDENTITY[:3], (10000, 20000, 30000)):
        conn.execute("SELECT setval(%s,%s,true)", (table + "_id_seq", value))
    role = conn.execute("INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,'reviewed-office',false) RETURNING id", (a,)).fetchone()[0]
    other_role = conn.execute("INSERT INTO roles(company_id,name,is_system_role) VALUES (%s,'alternate-office',false) RETURNING id", (a,)).fetchone()[0]
    conn.execute("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (%s,%s,%s)", (a, drivers[(a, "granted")], role))
    locations = []
    for code in ("SRC", "DST"):
        locations.append(conn.execute("INSERT INTO inventory_locations(company_id,name,code,location_type,created_at,updated_at) "
                                      "VALUES (%s,%s,%s,'WAREHOUSE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id", (a, code, code)).fetchone()[0])
    conn.execute("INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) VALUES (%s,%s,%s,%s)",
                 (a, drivers[(a, "granted")], locations[0], role))
    sessions = {}
    for company_id, username in ((a, "field"), (a, "dual"), (b, "field")):
        sessions[(company_id, username)] = conn.execute("INSERT INTO work_sessions(company_id,driver_id,start_time,session_date) "
            "VALUES (%s,%s,CURRENT_TIMESTAMP,CURRENT_DATE) RETURNING id", (company_id, drivers[(company_id, username)])).fetchone()[0]
    zone = conn.execute("INSERT INTO zones(company_id,name,is_active) VALUES (%s,'synthetic-zone',true) RETURNING id", (a,)).fetchone()[0]
    vehicle = conn.execute("INSERT INTO vehicles(company_id,plate_number,current_mileage,maintenance_status,is_active) "
                           "VALUES (%s,'synthetic-plate',0,'Active',true) RETURNING id", (a,)).fetchone()[0]
    conn.execute("INSERT INTO dispatch_routes(company_id,zone_id,driver_id,vehicle_id,work_session_id,source_location_id,dispatch_date,status,created_at) "
                 "VALUES (%s,%s,%s,%s,%s,%s,CURRENT_DATE,'active',CURRENT_TIMESTAMP)",
                 (a, zone, drivers[(a, "field")], vehicle, sessions[(a, "field")], locations[0]))
    shop = conn.execute("INSERT INTO shops(company_id,name,zone_id,added_by_driver_id,created_at) "
                        "VALUES (%s,'synthetic-shop',%s,%s,CURRENT_TIMESTAMP) RETURNING id", (a, zone, drivers[(a, "dual")])).fetchone()[0]
    conn.execute("INSERT INTO visits(company_id,driver_id,shop_id,work_session_id,operational_date,visit_timestamp,status,is_emergency) "
                 "VALUES (%s,%s,%s,%s,CURRENT_DATE,CURRENT_TIMESTAMP,'Pending',false)",
                 (a, drivers[(a, "field")], shop, sessions[(a, "field")]))
    product = conn.execute("INSERT INTO products(company_id,code,name,created_at,updated_at) "
                           "VALUES (%s,'SYNTHETIC','Synthetic',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id", (a,)).fetchone()[0]
    uom = conn.execute("INSERT INTO uom(name,code) VALUES ('Synthetic pack','SYN-PACK') RETURNING id").fetchone()[0]
    variant = conn.execute("INSERT INTO product_variants(company_id,product_id,base_uom_id,name,sku,created_at,updated_at) "
                           "VALUES (%s,%s,%s,'Synthetic','SYNTHETIC-V',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id", (a, product, uom)).fetchone()[0]
    conn.execute("INSERT INTO shortage_requests(company_id,zone_id,shop_id,driver_id,product_variant_id,quantity,status,created_at) "
                 "VALUES (%s,%s,%s,%s,%s,1,'pending',CURRENT_TIMESTAMP)", (a, zone, shop, drivers[(a, "field")], variant))
    conn.execute("INSERT INTO inventory_transfer_headers(company_id,reference_number,source_location_id,destination_location_id,workflow_type,status,"
                 "transfer_purpose,commercial_context,work_session_id,expected_receiver_id,dispatched_by,created_at,updated_at) "
                 "VALUES (%s,'SYNTHETIC-HANDSHAKE',%s,%s,'HANDSHAKE','DRAFT','REPLENISHMENT','{}',%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                 (a, *locations, sessions[(a, "field")], drivers[(a, "field")], drivers[(a, "owner")]))
    conn.execute("INSERT INTO refresh_tokens(driver_id,token,expires_at,is_revoked,created_at) "
                 "VALUES (%s,'synthetic-refresh',CURRENT_TIMESTAMP + interval '1 day',false,CURRENT_TIMESTAMP)", (drivers[(a, "owner")],))
    return {"a": a, "b": b, "drivers": drivers, "role": role, "other_role": other_role}


def reviewed(conn, fixture, service):
    proposal = service.report(conn)
    assert SECRET not in json.dumps(proposal)
    assert proposal["reviewed"] is False
    rows = {(entry["company_id"], entry["legacy_driver_id"]): entry for entry in proposal["entries"]}
    a = fixture["a"]
    assert rows[(a, fixture["drivers"][(a, "dual")])]["classification"] == "DUAL_SPLIT"
    assert rows[(a, fixture["drivers"][(a, "weak")])]["classification"] is None
    assert rows[(a, fixture["drivers"][(a, "granted")])]["classification"] == "BACKOFFICE_ONLY"
    assert all(value == 1 for value in rows[(a, fixture["drivers"][(a, "field")])]["expected_source"]["field_references"].values())
    document = copy.deepcopy(proposal)
    document["reviewed"] = True
    for entry in document["entries"]:
        name = entry["expected_source"]["username"]
        entry["company_owner"] = name == "owner"
        if name == "weak":
            entry.update(classification="BACKOFFICE_ONLY", backoffice_username="reviewed-weak")
        if name == "dual":
            entry["field_username"] = "dual-field"
    return document


def reject(conn, service, document, code=None):
    from domains.identity.migration.errors import BackfillError
    try:
        service.apply(conn, document)
    except BackfillError as exc:
        assert SECRET not in str(exc)
        if code:
            assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError("Invalid backfill unexpectedly applied")


def validation_failures(conn, fixture, service, document):
    a = fixture["a"]
    dual_index = next(i for i, e in enumerate(document["entries"]) if e["classification"] == "DUAL_SPLIT")
    field_index = next(i for i, e in enumerate(document["entries"]) if e["classification"] == "FIELD_ONLY")
    cases = [
        lambda d: d.update(reviewed=False),
        lambda d: d["entries"].pop(),
        lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])),
        lambda d: d["entries"][0].update(classification="UNRESOLVED"),
        lambda d: d["entries"][dual_index].update(field_username=None),
        lambda d: d["entries"][dual_index].update(field_username="dual"),
        lambda d: d["entries"][dual_index].update(field_username="owner"),
        lambda d: [e.update(company_owner=False) for e in d["entries"] if e["company_id"] == a],
        lambda d: d["entries"][dual_index].update(company_owner=True),
        lambda d: d["entries"][field_index].update(company_owner=True),
        lambda d: d["entries"][0].update(password_hash=SECRET),
    ]
    for mutate in cases:
        bad = copy.deepcopy(document)
        mutate(bad)
        reject(conn, service, bad)
        empty_targets(conn)
    # Extra source key, valid owner/usernames/expected facts/digest: rejected live.
    from domains.identity.migration.mapping import fingerprint
    bad = copy.deepcopy(document)
    extra = copy.deepcopy(bad["entries"][0])
    extra.update(legacy_driver_id=999999, company_owner=False, backoffice_username="extra")
    extra["expected_source"]["legacy_driver_id"] = 999999
    extra["source_fingerprint"] = fingerprint(extra["expected_source"])
    bad["entries"].append(extra)
    reject(conn, service, bad, "INCOMPLETE_OR_EXTRA_LEGACY_ROWS")
    # Live source edits invalidate the reviewed fingerprint, including same-count grants.
    driver = fixture["drivers"][(a, "owner")]
    conn.execute("UPDATE drivers SET username='changed-owner' WHERE id=%s", (driver,))
    reject(conn, service, document, "STALE_MAPPING")
    conn.execute("UPDATE drivers SET username='owner' WHERE id=%s", (driver,))
    granted = fixture["drivers"][(a, "granted")]
    conn.execute("UPDATE user_roles SET role_id=%s WHERE driver_id=%s", (fixture["other_role"], granted))
    reject(conn, service, document, "STALE_MAPPING")
    conn.execute("UPDATE user_roles SET role_id=%s WHERE driver_id=%s", (fixture["role"], granted))
    # New legacy rows after review must be covered before apply.
    extra_id = conn.execute("INSERT INTO drivers(company_id,username,password_hash,full_name,created_at) "
                            "VALUES (%s,'new-after-review',%s,'Synthetic',CURRENT_TIMESTAMP) RETURNING id", (a, SECRET)).fetchone()[0]
    reject(conn, service, document, "INCOMPLETE_OR_EXTRA_LEGACY_ROWS")
    conn.execute("DELETE FROM drivers WHERE id=%s", (extra_id,))
    empty_targets(conn)
    return len(cases) + 4


def atomic_fault(conn, fixture, service, document):
    # A real DB error late in company B, after company A was written, rolls all rows back.
    conn.execute("CREATE FUNCTION identity_gate_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                 f"IF NEW.company_id={fixture['b']} THEN RAISE EXCEPTION 'synthetic late failure'; END IF; RETURN NEW; END $$")
    conn.execute(f"CREATE TRIGGER identity_gate_fault BEFORE INSERT ON {BRIDGE} FOR EACH ROW EXECUTE FUNCTION identity_gate_fault()")
    try:
        reject(conn, service, document, "ATOMIC_APPLY_DATABASE_FAILED")
        empty_targets(conn)
    finally:
        conn.execute(f"DROP TRIGGER identity_gate_fault ON {BRIDGE}")
        conn.execute("DROP FUNCTION identity_gate_fault()")


def verify_result(conn, fixture, document, service):
    result = service.apply(conn, document)
    assert result["status"] == "APPLIED" and result["legacy_driver_count"] == 7
    assert result["classifications"] == {"BACKOFFICE_ONLY": 4, "FIELD_ONLY": 2, "DUAL_SPLIT": 1}
    assert [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in (*IDENTITY, BRIDGE)] == [8, 5, 3, 2, 7]
    assert conn.execute("SELECT count(*) FROM company_principals WHERE password_hash<>%s", (SECRET,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM company_principals WHERE id<=10000").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM backoffice_users WHERE id<=20000").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM field_representatives WHERE id<=30000").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM identity_legacy_driver_map m JOIN field_representatives f "
                        "ON f.company_id=m.company_id AND f.id=m.field_representative_id JOIN drivers d "
                        "ON d.company_id=m.company_id AND d.id=m.legacy_driver_id "
                        "WHERE f.can_allow_debt<>d.can_allow_debt OR f.max_debt_limit<>d.max_debt_limit").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_name IN ('company_principals','backoffice_users') "
                        "AND column_name IN ('can_allow_debt','max_debt_limit')").fetchone()[0] == 0
    assert conn.execute("SELECT is_active FROM company_principals WHERE username='reviewed-weak'").fetchone() == (False,)
    before = conn.execute("SELECT to_jsonb(m) FROM identity_legacy_driver_map m ORDER BY company_id,legacy_driver_id").fetchall()
    seq = [conn.execute(f"SELECT last_value FROM {table}_id_seq").fetchone()[0] for table in IDENTITY[:3]]
    assert service.validate(conn, document)["status"] == "VALID_EXACT_RERUN"
    assert service.apply(conn, document)["status"] == "EXACT_RERUN"
    assert before == conn.execute("SELECT to_jsonb(m) FROM identity_legacy_driver_map m ORDER BY company_id,legacy_driver_id").fetchall()
    assert seq == [conn.execute(f"SELECT last_value FROM {table}_id_seq").fetchone()[0] for table in IDENTITY[:3]]


def divergent_reruns(conn, fixture, document, service):
    bad = copy.deepcopy(document)
    bad["entries"][0]["backoffice_username"] = "divergent-owner"
    reject(conn, service, bad, "DIVERGENT_PRINCIPAL")
    bad = copy.deepcopy(document)
    for entry in bad["entries"]:
        if entry["company_id"] == fixture["a"]:
            entry["company_owner"] = entry["classification"] == "DUAL_SPLIT"
    reject(conn, service, bad, "DIVERGENT_OWNER")
    principal_id = conn.execute("SELECT backoffice_principal_id FROM identity_legacy_driver_map WHERE company_id=%s AND legacy_driver_id=%s",
                                (fixture["a"], fixture["drivers"][(fixture["a"], "owner")])).fetchone()[0]
    for column, wrong, original, code in (("username", "divergent-owner", "owner", "DIVERGENT_PRINCIPAL"),
                                         ("password_hash", "synthetic-other-hash", SECRET, "DIVERGENT_PRINCIPAL"),
                                         ("auth_revision", 2, 1, "DIVERGENT_PRINCIPAL")):
        query = sql.SQL("UPDATE company_principals SET {}=%s WHERE id=%s").format(sql.Identifier(column))
        conn.execute(query, (wrong, principal_id))
        reject(conn, service, document, code)
        conn.execute(query, (original, principal_id))
    conn.execute("UPDATE field_representatives SET max_debt_limit=max_debt_limit+1 WHERE max_debt_limit=321.123")
    reject(conn, service, document, "DIVERGENT_FIELD_DEBT")
    conn.execute("UPDATE field_representatives SET max_debt_limit=321.123 WHERE max_debt_limit=322.123")
    extra = fixture_tools.principal(conn, fixture["a"], "unmapped-new-root", "BACKOFFICE")
    reject(conn, service, document, "DIVERGENT_OR_UNMAPPED_TARGETS")
    conn.execute("DELETE FROM company_principals WHERE id=%s", (extra,))
    key = fixture["a"], fixture["drivers"][(fixture["a"], "dual")]
    saved = conn.execute("SELECT field_principal_id,field_representative_id FROM identity_legacy_driver_map "
                         "WHERE company_id=%s AND legacy_driver_id=%s", key).fetchone()
    conn.execute("UPDATE identity_legacy_driver_map SET classification='BACKOFFICE_ONLY',field_principal_id=NULL,field_representative_id=NULL "
                 "WHERE company_id=%s AND legacy_driver_id=%s", key)
    reject(conn, service, document, "DIVERGENT_OR_UNMAPPED_TARGETS")
    conn.execute("UPDATE identity_legacy_driver_map SET classification='DUAL_SPLIT',field_principal_id=%s,field_representative_id=%s "
                 "WHERE company_id=%s AND legacy_driver_id=%s", (*saved, *key))
    assert service.apply(conn, document)["status"] == "EXACT_RERUN"


def verify_bridge_schema(conn):
    from domains.identity.migration.models import IdentityLegacyDriverMap
    expected = {str(c.name) for c in IdentityLegacyDriverMap.__table__.constraints}
    actual = {row[0] for row in conn.execute("SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass", (BRIDGE,))}
    assert actual == expected
    assert conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND tablename=%s", (BRIDGE,)).fetchone()[0] == 5
    assert conn.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (BRIDGE,)).fetchone()[0]
    policies = conn.execute("SELECT permissive FROM pg_policies WHERE schemaname='public' AND tablename=%s", (BRIDGE,)).fetchall()
    assert sorted(policies) == [("PERMISSIVE",), ("RESTRICTIVE",)]
    assert conn.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')", (RUNTIME, BRIDGE)).fetchone()[0]
    assert not conn.execute("SELECT has_table_privilege(%s,%s,'TRUNCATE')", (RUNTIME, BRIDGE)).fetchone()[0]


def verify_rls(conn, connect, fixture, service, document):
    from domains.identity.migration.errors import BackfillError
    with psycopg.connect(**connect, user=RUNTIME, autocommit=True) as runtime:
        try:
            service.report(runtime)
        except BackfillError as exc:
            assert exc.code == "MIGRATION_ROLE_FULL_VISIBILITY_REQUIRED"
        else:
            raise AssertionError("Tenant role incorrectly accepted as complete source authority")
    # Reuse the prior focused gate's existing four-table cross-tenant checks.
    fixture_tools.RUNTIME = RUNTIME
    p, f, b = conn.execute("SELECT m.backoffice_principal_id,other.field_principal_id,m.backoffice_user_id "
                           "FROM identity_legacy_driver_map m JOIN identity_legacy_driver_map other ON other.company_id=m.company_id "
                           "WHERE m.company_id=%s AND m.classification='BACKOFFICE_ONLY' AND other.classification='FIELD_ONLY'",
                           (fixture["b"],)).fetchone()
    fixture_tools.verify_rls(conn, connect, {"a": fixture["a"], "b": fixture["b"], "pb": p, "fb": f, "bb": b})
    conn.execute(f"CREATE POLICY identity_gate_permissive ON {BRIDGE} USING (true) WITH CHECK (true)")
    try:
        with psycopg.connect(**connect, user=RUNTIME, autocommit=True) as runtime:
            assert runtime.execute(f"SELECT count(*) FROM {BRIDGE}").fetchone()[0] == 0
            for tenant in (fixture["a"], fixture["b"]):
                with runtime.transaction():
                    runtime.execute("SELECT set_config('app.current_tenant',%s,true)", (str(tenant),))
                    assert runtime.execute(f"SELECT DISTINCT company_id FROM {BRIDGE}").fetchall() == [(tenant,)]
            with runtime.transaction():
                runtime.execute("SELECT set_config('app.current_tenant',%s,true)", (str(fixture["a"]),))
                assert runtime.execute(f"UPDATE {BRIDGE} SET classification=classification WHERE company_id=%s", (fixture["b"],)).rowcount == 0
                assert runtime.execute(f"DELETE FROM {BRIDGE} WHERE company_id=%s", (fixture["b"],)).rowcount == 0
                fixture_tools.expect_error(runtime, f"INSERT INTO {BRIDGE}(company_id,legacy_driver_id,classification,backoffice_principal_id,backoffice_user_id) "
                                           "VALUES (%s,%s,'BACKOFFICE_ONLY',%s,%s)",
                                           (fixture["b"], fixture["drivers"][(fixture["b"], "owner")], p, b), "42501")
            with runtime.transaction():
                runtime.execute("SELECT set_config('app.current_tenant','',true)")
                assert runtime.execute(f"SELECT count(*) FROM {BRIDGE}").fetchone()[0] == 0
    finally:
        conn.execute(f"DROP POLICY identity_gate_permissive ON {BRIDGE}")
    # Every bridge FK rejects tenant mismatch independently of RLS.
    key = fixture["a"], fixture["drivers"][(fixture["a"], "dual")]
    for column, value in (("legacy_driver_id", fixture["drivers"][(fixture["b"], "owner")]),
                          ("backoffice_principal_id", p), ("backoffice_user_id", b),
                          ("field_principal_id", f), ("field_representative_id", conn.execute(
                              "SELECT field_representative_id FROM identity_legacy_driver_map WHERE company_id=%s AND classification='FIELD_ONLY'", (fixture["b"],)).fetchone()[0])):
        query = sql.SQL("UPDATE identity_legacy_driver_map SET {}=%s WHERE company_id=%s AND legacy_driver_id=%s").format(sql.Identifier(column))
        fixture_tools.expect_error(conn, query, (value, *key), "23503")
    fixture_tools.expect_error(conn, "UPDATE identity_legacy_driver_map SET classification='FIELD_ONLY' WHERE company_id=%s AND legacy_driver_id=%s", key, "23514")
    fixture_tools.expect_error(conn, "UPDATE identity_legacy_driver_map SET classification='UNKNOWN' WHERE company_id=%s AND legacy_driver_id=%s", key, "23514")


def source_writer_race(conn, connect, fixture, service, document):
    from domains.identity.migration.errors import BackfillError
    with psycopg.connect(**connect, user=ADMIN, autocommit=True) as writer:
        writer.execute("BEGIN")
        writer.execute("UPDATE drivers SET full_name='changed-in-flight' WHERE id=%s", (fixture["drivers"][(fixture["a"], "owner")],))
        def apply_after_wait():
            with psycopg.connect(**connect, user=ADMIN, autocommit=True) as contender:
                return service.apply(contender, document)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(apply_after_wait)
            deadline = time.monotonic() + 4
            while not conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE relation='drivers'::regclass AND mode='ShareLock' AND NOT granted)").fetchone()[0]:
                if future.done() or time.monotonic() > deadline:
                    raise AssertionError("Apply did not wait for concurrent source edit")
                time.sleep(0.05)
            writer.execute("COMMIT")
            try:
                future.result(timeout=10)
            except BackfillError as exc:
                assert exc.code == "STALE_MAPPING"
            else:
                raise AssertionError("Concurrent stale source was applied")
    conn.execute("UPDATE drivers SET full_name='Synthetic owner' WHERE id=%s", (fixture["drivers"][(fixture["a"], "owner")],))
    empty_targets(conn)


def cli_checks(conn, env, cluster, document):
    explicit = cluster / "operator.env"
    explicit.write_text("DATABASE_URL=" + env["DATABASE_URL"] + "\nDATABASE_URL_MIGRATION=" + env["DATABASE_URL_MIGRATION"] + "\n", encoding="utf-8")
    mapping = cluster / "reviewed.json"
    mapping.write_text(json.dumps(document), encoding="utf-8")
    command = [sys.executable, "scripts/backfill_identity_from_legacy.py"]
    out = fixture_tools.run([*command, "report", "--env-file", str(explicit)], env=env)
    assert SECRET not in out and json.loads(out)["reviewed"] is False
    out = fixture_tools.run([*command, "validate", "--env-file", str(explicit), "--mapping-file", str(mapping)], env=env)
    assert SECRET not in out and json.loads(out)["status"] == "VALID_NEW_BACKFILL"
    empty_targets(conn)
    # Invalid secret-bearing operator input is rejected without echo or traceback.
    bad = copy.deepcopy(document)
    invalid = cluster / "invalid.json"
    # Test forbidden secret fields without persisting even a synthetic hash in a map.
    bad["entries"][0]["password_hash"] = "forbidden-field"
    invalid.write_text(json.dumps(bad), encoding="utf-8")
    import subprocess
    failed = subprocess.run([*command, "apply", "--env-file", str(explicit), "--mapping-file", str(invalid)],
                            cwd=BACKEND, env=env, capture_output=True, text=True)
    assert failed.returncode == 2 and SECRET not in failed.stdout + failed.stderr and "Traceback" not in failed.stderr
    empty_targets(conn)
    return command, explicit, mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--pg-bin", type=Path, default=Path(r"C:\Program Files\PostgreSQL\16\bin") if os.name == "nt" else Path("/usr/lib/postgresql/16/bin"))
    args = parser.parse_args()
    if not args.run:
        parser.error("--run required; existing DB URLs are never accepted")
    assert Path.cwd().resolve() == BACKEND
    pg = lambda name: str(args.pg_bin / (name + (".exe" if os.name == "nt" else "")))
    cluster = Path(tempfile.mkdtemp(prefix="wanasah_identity_backfill_")).resolve()
    data = cluster / "data"
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "ENVIRONMENT": "test", "SECRET_KEY": "IdentityBackfillSynthetic123456789012345678901234567",
                "DATABASE_URL": f"postgresql+asyncpg://{RUNTIME}@127.0.0.1:{port}/{DATABASE}",
                "DATABASE_URL_MIGRATION": f"postgresql+asyncpg://{ADMIN}@127.0.0.1:{port}/{DATABASE}"})
    os.environ.update({key: env[key] for key in ("PYTHONDONTWRITEBYTECODE", "ENVIRONMENT", "SECRET_KEY", "DATABASE_URL", "DATABASE_URL_MIGRATION")})
    sys.path.insert(0, str(BACKEND))
    from domains.identity.migration import backfill as service
    checks, started, failure = [], False, None
    def checkpoint(label):
        checks.append(label)
        print(label + "=PASS", flush=True)
    def alembic(*arguments):
        return fixture_tools.run([sys.executable, "-m", "alembic", *arguments], env=env)
    try:
        fixture_tools.run([pg("initdb"), "-D", str(data), "-U", ADMIN, "--auth=trust", "--encoding=UTF8", "--no-locale"])
        fixture_tools.run([pg("pg_ctl"), "-D", str(data), "-l", str(cluster / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], pg_ctl=True)
        started = True
        print(f"ISOLATED_CLUSTER_STARTED={cluster}", flush=True)
        connect = {"host": "127.0.0.1", "port": port, "dbname": DATABASE}
        with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user=ADMIN, autocommit=True) as conn:
            assert Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve() == data
            conn.execute(f"CREATE ROLE {RUNTIME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
            conn.execute(f"CREATE DATABASE {DATABASE}")
        alembic("upgrade", PREVIOUS)
        fixture_tools.TABLES = (BRIDGE,)  # Include all old/Phase-2 definitions in preservation hash.
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            before_schema = fixture_tools.legacy_contract(conn)
        alembic("upgrade", "head")
        checkpoint("CLEAN_BOOTSTRAP_AND_ADDITIVE_BRIDGE_UPGRADE")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            assert fixture_tools.legacy_contract(conn) == before_schema
            verify_bridge_schema(conn)
            assert conn.execute("SELECT count(*) FROM pg_constraint WHERE contype='f' AND confrelid='drivers'::regclass AND conrelid<>'identity_legacy_driver_map'::regclass").fetchone()[0] == 55
        alembic("downgrade", PREVIOUS)
        alembic("upgrade", "head")
        checkpoint("EMPTY_BRIDGE_DOWNGRADE_UPGRADE")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            fixture = seed(conn)
            legacy = legacy_data(conn)
            document = reviewed(conn, fixture, service)
            assert service.validate(conn, document)["status"] == "VALID_NEW_BACKFILL"
            checkpoint("READONLY_EVIDENCE_ALL_FIVE_FIELD_REFERENCES_AND_EXPLICIT_REVIEW")
            commands = cli_checks(conn, env, cluster, document)
            checkpoint("OPERATOR_CLI_REPORT_VALIDATE_SECRET_REDACTION")
            count = validation_failures(conn, fixture, service, document)
            checkpoint(f"PREWRITE_REJECTION_CASES_{count}")
            source_writer_race(conn, connect, fixture, service, document)
            checkpoint("CONCURRENT_SOURCE_COMMIT_CAUSES_STALE_REFUSAL")
            atomic_fault(conn, fixture, service, document)
            checkpoint("LATE_DATABASE_FAILURE_ROLLS_BACK_BOTH_COMPANIES")
            verify_result(conn, fixture, document, service)
            checkpoint("BACKOFFICE_FIELD_DUAL_OWNER_HASH_DEBT_INDEPENDENT_IDS_EXACT_RERUN")
            divergent_reruns(conn, fixture, document, service)
            checkpoint("DIVERGENT_MAPPING_TARGET_OWNER_BRIDGE_RERUNS_REFUSED")
            # Restore reuse fixture scope for its four-table RLS helper only.
            fixture_tools.TABLES = IDENTITY
            verify_rls(conn, connect, fixture, service, document)
            fixture_tools.TABLES = (BRIDGE,)
            checkpoint("BRIDGE_AND_IDENTITY_RLS_FIVE_TENANT_FKS_AND_SHAPE_CHECKS")
            command, explicit, mapping = commands
            output = fixture_tools.run([*command, "apply", "--env-file", str(explicit), "--mapping-file", str(mapping)], env=env)
            assert json.loads(output)["status"] == "EXACT_RERUN" and SECRET not in output
            checkpoint("OPERATOR_CLI_APPLY_EXACT_RERUN")
            assert legacy_data(conn) == legacy
            assert fixture_tools.legacy_contract(conn) == before_schema
            checkpoint("ALL_LEGACY_ROWS_55_FKS_REFRESH_AND_AMBIGUOUS_CONTRACTS_PRESERVED")
        assert "No new upgrade operations detected" in alembic("check")
        checkpoint("ALEMBIC_METADATA_DRIFT_CHECK")
        try:
            alembic("downgrade", PREVIOUS)
        except RuntimeError as exc:
            assert "Cannot downgrade populated identity bridge" in str(exc)
        else:
            raise AssertionError("Populated bridge downgrade erased mappings")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
            assert conn.execute(f"SELECT count(*) FROM {BRIDGE}").fetchone()[0] == 7
        checkpoint("POPULATED_BRIDGE_DOWNGRADE_REFUSED")
    except psycopg.Error as exc:
        failure = f"{type(exc).__name__} SQLSTATE={exc.sqlstate} table={exc.diag.table_name} column={exc.diag.column_name}"
        raise RuntimeError(failure) from None
    except Exception as exc:
        failure = type(exc).__name__  # Never report a DB exception's parameters.
        raise
    finally:
        if started or (data / "postmaster.pid").exists():
            fixture_tools.run([pg("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], pg_ctl=True)
            checkpoint("ISOLATED_CLUSTER_STOPPED")
        evidence = ["# Phase 3/4 legacy identity backfill validation", "",
                    "Source main: c13f4ba5c806f3e030fdd621c7321b1663ffcc7b.",
                    f"Migration: {REVISION}; down_revision: {PREVIOUS}.",
                    "Only existing interpreter/packages; fresh localhost PostgreSQL 16; all rows synthetic.",
                    f"Retained stopped cluster: {cluster}.", "",
                    *[f"- PASS: {label}" for label in checks],
                    *([f"- FAIL: {failure}"] if failure else []), "",
                    "7 legacy rows / 2 companies -> 8 principals, 5 Backoffice profiles, 3 Field profiles, 2 explicit Owners, 7 bridge rows.",
                    "Four BACKOFFICE_ONLY, two FIELD_ONLY, one DUAL_SPLIT. Hashes copied unchanged and excluded from reports/mappings/errors.",
                    "All 55 old Driver FKs preserved; one new bridge FK references Driver. No runtime auth/token/FK cutover.",
                    "All current Driver rows must be covered globally. Companies without Drivers are outside this backfill scope.",
                    "Source and target locks are bounded; atomicity covers rows, while normal PostgreSQL sequences may consume IDs on rollback.",
                    "Password hashes are deliberately excluded from the non-secret review fingerprint; apply copies the current locked source hash,",
                    "and exact rerun compares that source hash against every mapped principal without logging it.",
                    "Bridge composite FKs enforce tenant correspondence. The service additionally verifies typed principal/profile pairs before commit/rerun.",
                    "", "## Reproduction and operator contract", "",
                    "From wa_backend, with the existing backend interpreter:",
                    "- python -m unittest tests/test_identity_legacy_backfill.py -v (6 static/model/offline-DDL checks).",
                    "- python tests/run_identity_legacy_backfill_gate.py --run (new isolated cluster, never an existing DB).",
                    "", "Operator CLI: python scripts/backfill_identity_from_legacy.py MODE --env-file PATH",
                    "where MODE is report, validate or apply. validate/apply additionally require --mapping-file reviewed.json.",
                    "report optionally accepts --output proposal.json; otherwise emits JSON to stdout.",
                    "Explicit env file must declare literal DATABASE_URL_MIGRATION and DATABASE_URL for the same PostgreSQL DB;",
                    "conflicting inherited URLs are rejected. Full-source visibility requires the migration role (superuser/BYPASSRLS).",
                    "No credentials or connection URLs are included in command errors.",
                    "", "JSON format_version=1, reviewed=true, entries=[...]. Each entry requires company_id, legacy_driver_id,",
                    "classification, expected_source, source_fingerprint, backoffice_username, field_username, company_owner.",
                    "Unknown fields (including password_hash) and duplicate JSON keys are rejected. No target IDs are provided;",
                    "PostgreSQL generates them. Usernames are used exactly as reviewed. Owner selection is always explicit.",
                    "Proposal reviewed=false, company_owner=null, weak classification=null; DUAL field_username is deliberately null.",
                    "Review resolves those fields without altering expected_source/source_fingerprint. is_admin is evidence, never Owner proof.",
                    "The reference digest includes sorted row IDs and grant attributes, detecting same-count replacement/role edits.",
                    "", "## Acceptance coverage", "",
                    "| Contract gate | Evidence |", "| --- | --- |",
                    "| Complete one-to-one source; no missing/extra/duplicate/stale rows | 15 prewrite rejections; live username/role/new-row edits; concurrent source commit |",
                    "| Three classifications, explicit unique Owner, distinct DUAL usernames | 4 BO / 2 Field / 1 Dual; 2 Owners; invalid kinds/dual usernames/zero or multiple Owners/Field Owner rejected |",
                    "| Exact credential copying, field-only debt, independent IDs | All 8 principal hashes equal locked source; 3 debt profiles equal source; separate generated sequence ranges |",
                    "| No partial apply | Real trigger failure in second company; all five target tables remain empty |",
                    "| Exact rerun / divergent rerun | Bridge rows and sequences unchanged; changed username/hash/revision/debt/Owner/map/bridge/extra target refused |",
                    "| Tenant-safe bridge and identities | 5 FK tenant rejections, 2 shape rejections; missing/empty/foreign tenant read/write denied, including permissive-policy override attempt |",
                    "| Schema lifecycle and preservation | Clean bootstrap, empty round-trip, populated refusal, Alembic check; all old schema and all legacy row digests unchanged |"]
        (BACKEND / "tests/IDENTITY_PHASE34_BACKFILL_VALIDATION.md").write_text("\n".join(evidence) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
