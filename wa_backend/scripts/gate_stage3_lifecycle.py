"""
Stage 3 Gate — ProductLocation, Lifecycle, Holds and Archive
==============================================================
Invariants checked:
  1. RLS read/write isolation (product_locations, domain_audit_events)
  2. Lifecycle advisory lock race — session_1 holds EXCLUSIVE advisory lock;
     session_2 is verified WAITING for the SAME lock (same classid/objid) in pg_locks.
  3. Audit append-only: UPDATE/DELETE on domain_audit_events raises 55000.
  4. ProductLocation unique constraint (company, location, variant).
  5. RLS catalog audit: Stage 3 tables have ENABLE + FORCE.

Cleanup guarantee: every test uses a dedicated company created inside the run.
All companies seeded by this gate are deleted via CASCADE in a finally block.
Even when advisory-lock workers fail mid-way, the seeded company is removed.

Run:  python wa_backend/scripts/gate_stage3_lifecycle.py
Exit 0 = PASS, non-zero = FAIL.
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=False)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

_migration_url = os.environ["DATABASE_URL_MIGRATION"]
_app_url       = os.environ["DATABASE_URL"]

engine_su  = create_async_engine(_migration_url, echo=False, pool_size=5, max_overflow=5)
engine_app = create_async_engine(_app_url,       echo=False, pool_size=5, max_overflow=5)

Session_su  = async_sessionmaker(bind=engine_su,  expire_on_commit=False, autobegin=False)
Session_app = async_sessionmaker(bind=engine_app, expire_on_commit=False, autobegin=False)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def set_tenant(conn, company_id: int) -> None:
    await conn.execute(text(f"SET app.current_tenant = '{company_id}'"))


# ---------------------------------------------------------------------------
# Cleanup: delete company by id (CASCADE removes all child rows)
# ---------------------------------------------------------------------------
async def cleanup_company(company_id: int) -> None:
    """Best-effort delete; never raises so cleanup never masks test errors."""
    try:
        async with Session_su() as su:
            await su.begin()
            await su.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company_id})
            await su.commit()
    except Exception:
        pass  # best-effort only


# ---------------------------------------------------------------------------
# Helpers: seed minimal tenant using actual DB schema
# ---------------------------------------------------------------------------
async def make_company(conn) -> int:
    code = f"C{uuid4().hex[:8]}"
    row = (await conn.execute(text(
        "INSERT INTO companies (name, company_code, is_active, subscription_status, currency_code, timezone, created_at) "
        "VALUES (:n, :c, true, 'active', 'JOD', 'Asia/Riyadh', NOW()) RETURNING id"
    ), {"n": f"Co-{code}", "c": code})).fetchone()
    return row[0]


async def make_branch(conn, company_id: int) -> int:
    code = f"B{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO branches (company_id, name, branch_code, is_active, created_at) "
        "VALUES (:c, 'HQ', :bc, true, NOW()) RETURNING id"
    ), {"c": company_id, "bc": code})).fetchone()
    return row[0]


async def make_location(conn, company_id: int, branch_id: int) -> int:
    code = f"L{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO inventory_locations "
        "(company_id, branch_id, name, code, location_type, is_system_managed, version, is_active, created_at, updated_at) "
        "VALUES (:c, :b, 'WH', :code, 'WAREHOUSE', false, 1, true, NOW(), NOW()) RETURNING id"
    ), {"c": company_id, "b": branch_id, "code": code})).fetchone()
    return row[0]


async def make_product(conn, company_id: int) -> int:
    code = f"P{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO products (company_id, code, name, created_at, updated_at) "
        "VALUES (:c, :code, 'Prod', NOW(), NOW()) RETURNING id"
    ), {"c": company_id, "code": code})).fetchone()
    return row[0]


async def make_variant(conn, company_id: int, product_id: int) -> int:
    sku = f"SKU-{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO product_variants "
        "(company_id, product_id, sku, name, base_uom_id, quantity_scale, quantity_step, "
        " lot_control_mode, expiry_control_mode, lifecycle_status, operational_hold, lifecycle_revision, version, created_at, updated_at) "
        "VALUES (:c, :p, :sku, 'SKU', 1, 0, '1', 'NONE', 'NONE', 'DRAFT', 'NONE', 1, 1, NOW(), NOW()) RETURNING id"
    ), {"c": company_id, "p": product_id, "sku": sku})).fetchone()
    return row[0]


async def make_driver(conn, company_id: int) -> int:
    uname = f"d{uuid4().hex[:8]}"
    row = (await conn.execute(text(
        "INSERT INTO drivers (company_id, username, password_hash, full_name, phone_number, is_active, is_admin, created_at) "
        "VALUES (:c, :u, '$2b$12$xxx', 'Admin', :ph, true, true, NOW()) RETURNING id"
    ), {"c": company_id, "u": uname, "ph": f"+9627{uuid4().hex[:7]}"})).fetchone()
    return row[0]


async def make_tenant(conn):
    """Returns (company_id, location_id, variant_id, driver_id).
    All rows belong to company_id; deleting that company cascades everything."""
    co  = await make_company(conn)
    br  = await make_branch(conn, co)
    loc = await make_location(conn, co, br)
    prd = await make_product(conn, co)
    var = await make_variant(conn, co, prd)
    drv = await make_driver(conn, co)
    return co, loc, var, drv


# ===========================================================================
# Test 1 — RLS isolation: tenant B cannot read / write tenant A's rows
# ===========================================================================
async def test_rls_isolation() -> None:
    print("\n[1] RLS isolation on product_locations")
    a_co = b_co = None
    try:
        # --- seed both tenants ---
        async with Session_su() as su:
            await su.begin()
            try:
                a_co, a_loc, a_var, a_drv = await make_tenant(su)
                b_co, *_ = await make_tenant(su)
                a_pl_id = (await su.execute(text(
                    "INSERT INTO product_locations "
                    "(company_id, location_id, product_variant_id, created_by, created_at, updated_at) "
                    "VALUES (:c,:l,:v,:d,NOW(),NOW()) RETURNING id"
                ), {"c": a_co, "l": a_loc, "v": a_var, "d": a_drv})).scalar()
                await su.commit()
            except Exception as e:
                await su.rollback()
                record("RLS isolation (seed)", False, str(e))
                return

        # --- B reads A's row — should see 0 ---
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, b_co)
            count = (await app.execute(text(
                "SELECT COUNT(*) FROM product_locations WHERE id = :id"
            ), {"id": a_pl_id})).scalar()
            await app.rollback()
        record("RLS read isolation (B cannot see A's product_location)", count == 0,
               f"rows_visible={count}")

        # --- B tries to write into A's company — must be blocked ---
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, b_co)
            try:
                await app.execute(text(
                    "INSERT INTO product_locations "
                    "(company_id, location_id, product_variant_id, created_by, created_at, updated_at) "
                    "VALUES (:c,:l,:v,:d,NOW(),NOW())"
                ), {"c": a_co, "l": a_loc, "v": a_var, "d": a_drv})
                await app.rollback()
                record("RLS write isolation (B cannot insert into A)", False, "INSERT succeeded — FAIL")
            except Exception as ex:
                await app.rollback()
                record("RLS write isolation (B cannot insert into A)", True, type(ex).__name__)

    finally:
        # always clean up, regardless of pass/fail
        if a_co:
            await cleanup_company(a_co)
        if b_co:
            await cleanup_company(b_co)


# ===========================================================================
# Test 2 — Lifecycle advisory lock race, synchronized via pg_locks
# ===========================================================================
async def test_lifecycle_advisory_lock_race() -> None:
    """
    Synchronization protocol:
      - ready_event:   session_1 signals it has acquired the exclusive advisory lock.
      - release_event: main test signals session_1 to rollback (releasing the lock).
      - main polls pg_locks (up to 3 s) to confirm session_2 is waiting for the
        SAME lock (identical classid + objid, granted=false) held by session_1 —
        not just any advisory lock in the database.
    """
    print("\n[2] Lifecycle advisory lock race — pg_locks waiting verification")
    co = None
    t1 = t2 = None
    release_event = asyncio.Event()
    try:
        # --- seed ---
        async with Session_su() as su:
            await su.begin()
            try:
                co, _, var, _ = await make_tenant(su)
                await su.commit()
            except Exception as e:
                await su.rollback()
                record("Lifecycle lock race (seed)", False, str(e))
                return

        lock_key = f"product-lifecycle:{co}:{var}"

        ready_event = asyncio.Event()
        s1_pid_box: list[int] = []

        async def session1_worker():
            async with engine_su.connect() as conn:
                await conn.execute(text("BEGIN"))
                pid = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar()
                s1_pid_box.append(pid)
                await conn.execute(text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"
                ).bindparams(k=lock_key))
                ready_event.set()           # lock held — tell main
                await release_event.wait()  # hold until told to release
                await conn.execute(text("ROLLBACK"))

        async def session2_worker():
            async with engine_su.connect() as conn:
                await conn.execute(text("BEGIN"))
                # blocks until session1 releases
                await conn.execute(text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"
                ).bindparams(k=lock_key))
                await conn.execute(text("ROLLBACK"))

        t1 = asyncio.create_task(session1_worker())
        await asyncio.wait_for(ready_event.wait(), timeout=10)

        t2 = asyncio.create_task(session2_worker())
        await asyncio.sleep(0.2)  # give session_2 time to block

        # --- resolve the exact lock coordinates held by session_1 ---
        s1_pid = s1_pid_box[0] if s1_pid_box else -1

        # First obtain classid/objid of the lock session_1 currently HOLDS
        # so we can assert session_2 is waiting for THAT same lock.
        async with engine_su.connect() as chk:
            lock_coords = (await chk.execute(text("""
                SELECT classid, objid
                FROM pg_locks
                WHERE locktype = 'advisory'
                  AND granted = true
                  AND pid = :s1_pid
                LIMIT 1
            """), {"s1_pid": s1_pid})).fetchone()

        if not lock_coords:
            record(
                "session_2 blocked in pg_locks while session_1 holds exclusive advisory lock",
                False,
                f"session_1 (pid={s1_pid}) has no advisory lock recorded in pg_locks",
            )
            record("Both sessions completed cleanly after lock release", False, "aborted before release")
            return

        held_classid, held_objid = lock_coords

        # Poll: session_2 must appear with granted=false on the SAME classid/objid
        waiting_confirmed = False
        waiting_rows = 0
        for _ in range(30):  # up to 3 s
            async with engine_su.connect() as chk:
                row = (await chk.execute(text("""
                    SELECT COUNT(*) FROM pg_locks
                    WHERE locktype = 'advisory'
                      AND granted = false
                      AND pid <> :s1_pid
                      AND classid = :classid
                      AND objid   = :objid
                """), {"s1_pid": s1_pid, "classid": held_classid, "objid": held_objid})).scalar()
            waiting_rows = row or 0
            if waiting_rows > 0:
                waiting_confirmed = True
                break
            await asyncio.sleep(0.1)

        record(
            "session_2 blocked in pg_locks while session_1 holds exclusive advisory lock",
            waiting_confirmed,
            f"s1_pid={s1_pid} classid={held_classid} objid={held_objid} waiting_rows={waiting_rows}",
        )

        release_event.set()
        try:
            await asyncio.wait_for(asyncio.gather(t1, t2), timeout=10)
            record("Both sessions completed cleanly after lock release", True)
        except Exception as e:
            record("Both sessions completed cleanly after lock release", False, str(e))

    finally:
        # ensure workers don't hang if we return early
        release_event.set()
        if t1 and not t1.done():
            t1.cancel()
        if t2 and not t2.done():
            t2.cancel()
        if co:
            await cleanup_company(co)


# ===========================================================================
# Test 3 — Audit append-only
# ===========================================================================
async def test_audit_append_only() -> None:
    print("\n[3] Audit append-only enforcement on domain_audit_events")
    co = None
    try:
        async with Session_su() as su:
            await su.begin()
            try:
                co, _, _, drv = await make_tenant(su)
                ev_id = (await su.execute(text(
                    "INSERT INTO domain_audit_events "
                    "(external_id, company_id, event_type, entity_type, entity_id, actor_user_id, actor_context, "
                    " reason_code, reason_text, request_id, before_snapshot, after_snapshot, schema_version, occurred_at) "
                    "VALUES (:eid,:c,'ProductPublished','ProductVariant','1',:d,'{}','ProductPublished','test',:rid,NULL,NULL,1,NOW()) "
                    "RETURNING id"
                ), {"eid": str(uuid4()), "c": co, "d": drv, "rid": str(uuid4())})).scalar()
                await su.commit()
            except Exception as e:
                await su.rollback()
                record("Audit append-only (seed)", False, str(e))
                return

        # UPDATE must be blocked
        async with Session_su() as su:
            await su.begin()
            try:
                await su.execute(text(
                    "UPDATE domain_audit_events SET reason_text='mutated' WHERE id=:id"
                ), {"id": ev_id})
                await su.rollback()
                record("domain_audit_events UPDATE blocked", False, "UPDATE succeeded — trigger absent!")
            except Exception as ex:
                await su.rollback()
                blocked = "55000" in str(ex) or "append-only" in str(ex).lower()
                record("domain_audit_events UPDATE blocked", blocked, type(ex).__name__)

        # DELETE must be blocked
        async with Session_su() as su:
            await su.begin()
            try:
                await su.execute(text(
                    "DELETE FROM domain_audit_events WHERE id=:id"
                ), {"id": ev_id})
                await su.rollback()
                record("domain_audit_events DELETE blocked", False, "DELETE succeeded — trigger absent!")
            except Exception as ex:
                await su.rollback()
                blocked = "55000" in str(ex) or "append-only" in str(ex).lower()
                record("domain_audit_events DELETE blocked", blocked, type(ex).__name__)

    finally:
        if co:
            await cleanup_company(co)


# ===========================================================================
# Test 4 — ProductLocation unique constraint
# ===========================================================================
async def test_product_location_unique() -> None:
    print("\n[4] ProductLocation unique constraint (company, location, variant)")
    co = None
    try:
        async with Session_su() as su:
            await su.begin()
            try:
                co, loc, var, drv = await make_tenant(su)
                await su.execute(text(
                    "INSERT INTO product_locations "
                    "(company_id, location_id, product_variant_id, created_by, created_at, updated_at) "
                    "VALUES (:c,:l,:v,:d,NOW(),NOW())"
                ), {"c": co, "l": loc, "v": var, "d": drv})
                await su.commit()
                record("ProductLocation first insert", True)
            except Exception as e:
                await su.rollback()
                record("ProductLocation first insert", False, str(e))
                return

        # Duplicate must fail
        async with Session_su() as su:
            await su.begin()
            try:
                await su.execute(text(
                    "INSERT INTO product_locations "
                    "(company_id, location_id, product_variant_id, created_by, created_at, updated_at) "
                    "VALUES (:c,:l,:v,:d,NOW(),NOW())"
                ), {"c": co, "l": loc, "v": var, "d": drv})
                await su.rollback()
                record("ProductLocation duplicate blocked", False, "Duplicate succeeded!")
            except Exception as ex:
                await su.rollback()
                record("ProductLocation duplicate blocked", True, type(ex).__name__)

    finally:
        if co:
            await cleanup_company(co)


# ===========================================================================
# Test 5 — RLS catalog audit (no tenant data; no cleanup needed)
# ===========================================================================
async def test_rls_catalog() -> None:
    print("\n[5] RLS catalog audit for Stage 3 tables")
    stage3_tables = [
        "product_locations",
        "domain_audit_events",
        "transactional_outbox",
    ]
    async with Session_su() as su:
        await su.begin()
        rows = (await su.execute(text("""
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND c.relname = ANY(:tables)
            ORDER BY relname
        """), {"tables": stage3_tables})).all()
        await su.rollback()

    found = {r[0]: (r[1], r[2]) for r in rows}
    for tbl in stage3_tables:
        if tbl not in found:
            record(f"RLS exists on {tbl}", False, "table not found")
        else:
            enabled, forced = found[tbl]
            record(f"RLS ENABLE+FORCE on {tbl}", enabled and forced,
                   f"enabled={enabled} forced={forced}")

    async with Session_su() as su:
        await su.begin()
        row = (await su.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='wanasah_app'"
        ))).fetchone()
        await su.rollback()
    if row:
        record("App role: no superuser", not row[0], f"rolsuper={row[0]}")
        record("App role: no BYPASSRLS",  not row[1], f"rolbypassrls={row[1]}")
    else:
        record("App role exists", False, "wanasah_app not found")


# ===========================================================================
# main
# ===========================================================================
async def main() -> int:
    print("=" * 60)
    print("Stage 3 Gate — PRODUCT_LIFECYCLE_GATE")
    print("=" * 60)

    await test_rls_isolation()
    await test_lifecycle_advisory_lock_race()
    await test_audit_append_only()
    await test_product_location_unique()
    await test_rls_catalog()

    await engine_su.dispose()
    await engine_app.dispose()

    print("\n" + "=" * 60)
    total  = len(RESULTS)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = total - passed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\nPRODUCT_LIFECYCLE_GATE=PASS")
        return 0
    else:
        print("\nPRODUCT_LIFECYCLE_GATE=FAIL")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAILED: {name} — {detail}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
