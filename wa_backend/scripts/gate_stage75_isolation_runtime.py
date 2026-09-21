from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=False)

from api.warehouse.inbound import _ensure_first_inbound_product_locations

MIGRATION_URL = os.environ["DATABASE_URL_MIGRATION"]
APP_URL = os.environ["DATABASE_URL"]

engine_su = create_async_engine(MIGRATION_URL, pool_size=5, max_overflow=5)
engine_app = create_async_engine(APP_URL, pool_size=10, max_overflow=10)
SessionSU = async_sessionmaker(bind=engine_su, expire_on_commit=False, autobegin=False)
SessionApp = async_sessionmaker(bind=engine_app, expire_on_commit=False, autobegin=False)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def set_tenant(session, company_id: int) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(company_id)},
    )


async def cleanup_company(company_id: int | None) -> None:
    if not company_id:
        return
    try:
        async with SessionSU() as su:
            await su.begin()
            await su.execute(text("DELETE FROM companies WHERE id=:id"), {"id": company_id})
            await su.commit()
    except Exception:
        pass


async def seed() -> dict[str, int]:
    async with SessionSU() as su:
        await su.begin()
        uom_id = (await su.execute(text("SELECT id FROM uom ORDER BY id LIMIT 1"))).scalar_one_or_none()
        if uom_id is None:
            raise RuntimeError("No UOM row exists; Stage 7.5 isolation gate cannot seed variants.")

        async def company(name: str) -> int:
            return int((await su.execute(text(
                "INSERT INTO companies (name, company_code, is_active, subscription_status, currency_code, timezone, created_at) "
                "VALUES (:n,:c,true,'active','JOD','Asia/Amman',NOW()) RETURNING id"
            ), {"n": name, "c": f"ISO-{uuid4().hex[:10]}"})).scalar_one())

        async def branch(company_id: int, name: str) -> int:
            return int((await su.execute(text(
                "INSERT INTO branches (company_id,name,branch_code,is_active,created_at) "
                "VALUES (:c,:n,:bc,true,NOW()) RETURNING id"
            ), {"c": company_id, "n": name, "bc": f"B-{uuid4().hex[:8]}"})).scalar_one())

        async def location(company_id: int, branch_id: int, name: str) -> int:
            return int((await su.execute(text(
                "INSERT INTO inventory_locations "
                "(company_id,branch_id,name,code,location_type,is_system_managed,version,is_active,created_at,updated_at) "
                "VALUES (:c,:b,:n,:code,'WAREHOUSE',false,1,true,NOW(),NOW()) RETURNING id"
            ), {"c": company_id, "b": branch_id, "n": name, "code": f"WH-{uuid4().hex[:8]}"})).scalar_one())

        async def driver(company_id: int, name: str) -> int:
            return int((await su.execute(text(
                "INSERT INTO drivers (company_id,username,password_hash,full_name,phone_number,is_active,is_admin,created_at) "
                "VALUES (:c,:u,'$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',:n,:p,true,true,NOW()) RETURNING id"
            ), {"c": company_id, "u": f"u{uuid4().hex[:10]}", "n": name, "p": f"+9627{uuid4().hex[:7]}"})).scalar_one())

        async def product(company_id: int, name: str) -> int:
            return int((await su.execute(text(
                "INSERT INTO products (company_id,code,name,created_at,updated_at) "
                "VALUES (:c,:code,:n,NOW(),NOW()) RETURNING id"
            ), {"c": company_id, "code": f"P-{uuid4().hex[:8]}", "n": name})).scalar_one())

        async def variant(company_id: int, product_id: int, name: str) -> int:
            return int((await su.execute(text(
                "INSERT INTO product_variants "
                "(company_id,product_id,base_uom_id,name,sku,quantity_scale,quantity_step,lot_control_mode,expiry_control_mode,lifecycle_status,operational_hold,lifecycle_revision,version,published_at,created_at,updated_at) "
                "VALUES (:c,:p,:u,:n,:sku,0,'1','REQUIRED','REQUIRED','ACTIVE','NONE',1,1,NOW(),NOW(),NOW()) RETURNING id"
            ), {"c": company_id, "p": product_id, "u": int(uom_id), "n": name, "sku": f"SKU-{uuid4().hex[:10]}"})).scalar_one())

        a = await company("ISO Company A")
        b = await company("ISO Company B")
        a_branch = await branch(a, "A HQ")
        b_branch = await branch(b, "B HQ")
        a_wh1 = await location(a, a_branch, "A Warehouse 1")
        a_wh2 = await location(a, a_branch, "A Warehouse 2")
        b_wh1 = await location(b, b_branch, "B Warehouse 1")
        a_driver = await driver(a, "A Admin")
        b_driver = await driver(b, "B Admin")
        a_product = await product(a, "A Product")
        b_product = await product(b, "B Product")
        a_var1 = await variant(a, a_product, "A Variant 1")
        a_var2 = await variant(a, a_product, "A Variant 2")
        a_var3 = await variant(a, a_product, "A Variant 3")
        b_var1 = await variant(b, b_product, "B Variant 1")
        b_var2 = await variant(b, b_product, "B Variant 2")

        # Existing explicit deny: lazy assignment must never overwrite this row.
        await su.execute(text(
            "INSERT INTO product_locations "
            "(company_id,location_id,product_variant_id,operational_flags,version,created_by,created_at,updated_at) "
            "VALUES (:c,:l,:v,CAST(:flags AS jsonb),1,:d,NOW(),NOW())"
        ), {
            "c": a,
            "l": a_wh1,
            "v": a_var2,
            "d": a_driver,
            "flags": '{"inbound_enabled": false, "outbound_enabled": true}',
        })

        # A real B row exists so RLS read isolation is tested against data, not emptiness.
        await su.execute(text(
            "INSERT INTO product_locations "
            "(company_id,location_id,product_variant_id,version,created_by,created_at,updated_at) "
            "VALUES (:c,:l,:v,1,:d,NOW(),NOW())"
        ), {"c": b, "l": b_wh1, "v": b_var1, "d": b_driver})

        await su.commit()
        return {
            "a": a, "b": b,
            "a_wh1": a_wh1, "a_wh2": a_wh2, "b_wh1": b_wh1,
            "a_driver": a_driver, "b_driver": b_driver,
            "a_var1": a_var1, "a_var2": a_var2, "a_var3": a_var3,
            "b_var1": b_var1, "b_var2": b_var2,
        }


async def count_assignment(company_id: int, location_id: int, variant_id: int) -> int:
    async with SessionSU() as su:
        await su.begin()
        count = int((await su.execute(text(
            "SELECT count(*) FROM product_locations "
            "WHERE company_id=:c AND location_id=:l AND product_variant_id=:v"
        ), {"c": company_id, "l": location_id, "v": variant_id})).scalar_one())
        await su.rollback()
        return count


async def main() -> None:
    ids: dict[str, int] = {}
    try:
        ids = await seed()
        a, b = ids["a"], ids["b"]

        # 1) Company isolation: tenant A cannot even read B's existing assignment.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            visible = int((await app.execute(text(
                "SELECT count(*) FROM product_locations WHERE company_id=:b"
            ), {"b": b})).scalar_one())
            await app.rollback()
        record("company RLS read isolation", visible == 0, f"visible_B_rows={visible}")

        # 2) Company isolation: tenant A cannot write a B-owned assignment.
        blocked = False
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await app.execute(text(
                    "INSERT INTO product_locations "
                    "(company_id,location_id,product_variant_id,created_by,created_at,updated_at) "
                    "VALUES (:c,:l,:v,:d,NOW(),NOW())"
                ), {"c": b, "l": ids["b_wh1"], "v": ids["b_var2"], "d": ids["b_driver"]})
                await app.flush()
            except Exception:
                blocked = True
            finally:
                await app.rollback()
        record("company RLS write isolation", blocked)

        # 3) First inbound assignment is created only for the selected warehouse.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            created = await _ensure_first_inbound_product_locations(
                app,
                company_id=a,
                location_id=ids["a_wh1"],
                variant_ids=[ids["a_var1"]],
                actor_id=ids["a_driver"],
                request_id=uuid4(),
            )
            await app.commit()
        wh1_count = await count_assignment(a, ids["a_wh1"], ids["a_var1"])
        wh2_count = await count_assignment(a, ids["a_wh2"], ids["a_var1"])
        record("selected warehouse gets assignment", created == {ids["a_var1"]} and wh1_count == 1)
        record("sibling warehouse stays isolated", wh2_count == 0, f"warehouse2_rows={wh2_count}")

        # 4) Exact retry is idempotent and does not duplicate the row/event owner.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            created_again = await _ensure_first_inbound_product_locations(
                app,
                company_id=a,
                location_id=ids["a_wh1"],
                variant_ids=[ids["a_var1"]],
                actor_id=ids["a_driver"],
                request_id=uuid4(),
            )
            await app.commit()
        record(
            "repeat assignment is idempotent",
            created_again == set() and await count_assignment(a, ids["a_wh1"], ids["a_var1"]) == 1,
        )

        # 5) An existing explicit deny is never overwritten by the lazy path.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            denied_created = await _ensure_first_inbound_product_locations(
                app,
                company_id=a,
                location_id=ids["a_wh1"],
                variant_ids=[ids["a_var2"]],
                actor_id=ids["a_driver"],
                request_id=uuid4(),
            )
            flags = (await app.execute(text(
                "SELECT operational_flags FROM product_locations "
                "WHERE company_id=:c AND location_id=:l AND product_variant_id=:v"
            ), {"c": a, "l": ids["a_wh1"], "v": ids["a_var2"]})).scalar_one()
            await app.commit()
        record(
            "explicit warehouse deny is preserved",
            denied_created == set() and flags.get("inbound_enabled") is False,
            f"flags={flags}",
        )

        # 6) A failed inbound transaction must not leave a hidden assignment behind.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            rolled_created = await _ensure_first_inbound_product_locations(
                app,
                company_id=a,
                location_id=ids["a_wh2"],
                variant_ids=[ids["a_var3"]],
                actor_id=ids["a_driver"],
                request_id=uuid4(),
            )
            await app.flush()
            await app.rollback()
        record(
            "rollback removes lazy assignment",
            rolled_created == {ids["a_var3"]}
            and await count_assignment(a, ids["a_wh2"], ids["a_var3"]) == 0,
        )

        # 7) Cross-company location must fail even if a caller passes inconsistent ids.
        cross_location_blocked = False
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await _ensure_first_inbound_product_locations(
                    app,
                    company_id=a,
                    location_id=ids["b_wh1"],
                    variant_ids=[ids["a_var3"]],
                    actor_id=ids["a_driver"],
                    request_id=uuid4(),
                )
                await app.flush()
            except Exception:
                cross_location_blocked = True
            finally:
                await app.rollback()
        record("cross-company warehouse assignment blocked", cross_location_blocked)

        # 8) Cross-company variant must fail at DB tenant-safe FK/RLS boundary.
        cross_variant_blocked = False
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await _ensure_first_inbound_product_locations(
                    app,
                    company_id=a,
                    location_id=ids["a_wh2"],
                    variant_ids=[ids["b_var2"]],
                    actor_id=ids["a_driver"],
                    request_id=uuid4(),
                )
                await app.flush()
            except Exception:
                cross_variant_blocked = True
            finally:
                await app.rollback()
        record("cross-company product assignment blocked", cross_variant_blocked)

        # 9) Concurrent first inbound attempts converge to one assignment only.
        async def worker() -> set[int]:
            async with SessionApp() as app:
                await app.begin()
                await set_tenant(app, a)
                created_now = await _ensure_first_inbound_product_locations(
                    app,
                    company_id=a,
                    location_id=ids["a_wh2"],
                    variant_ids=[ids["a_var3"]],
                    actor_id=ids["a_driver"],
                    request_id=uuid4(),
                )
                await app.commit()
                return created_now

        results = await asyncio.gather(worker(), worker())
        final_count = await count_assignment(a, ids["a_wh2"], ids["a_var3"])
        creators = sum(1 for result in results if ids["a_var3"] in result)
        record(
            "concurrent first inbound creates exactly one row",
            final_count == 1 and creators == 1,
            f"rows={final_count} creators={creators}",
        )

        # 10) Creating at warehouse 2 did not create anything at warehouse 1 for var3.
        record(
            "warehouse-to-warehouse isolation remains exact",
            await count_assignment(a, ids["a_wh1"], ids["a_var3"]) == 0,
        )

        # 11) Audit evidence stays tenant-owned and exists for successful creations.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            audit_count = int((await app.execute(text(
                "SELECT count(*) FROM domain_audit_events "
                "WHERE company_id=:c AND reason_text='AUTO_FIRST_INBOUND'"
            ), {"c": a})).scalar_one())
            foreign_audit = int((await app.execute(text(
                "SELECT count(*) FROM domain_audit_events WHERE company_id=:b"
            ), {"b": b})).scalar_one())
            await app.rollback()
        async with SessionSU() as su:
            await su.begin()
            outbox_count = int((await su.execute(text(
                "SELECT count(*) FROM transactional_outbox "
                "WHERE company_id=:c AND event_type='ProductLocationAssigned'"
            ), {"c": a})).scalar_one())
            await su.rollback()
        record("lazy assignments are audited", audit_count == 2, f"audit_rows={audit_count}")
        record("lazy assignments emit tenant-owned outbox evidence", outbox_count == 2, f"outbox_rows={outbox_count}")
        record("audit RLS hides foreign-company evidence", foreign_audit == 0, f"visible_foreign={foreign_audit}")

    finally:
        await cleanup_company(ids.get("a"))
        await cleanup_company(ids.get("b"))
        await engine_app.dispose()
        await engine_su.dispose()

    failures = [name for name, ok, _ in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")
    if failures:
        print("STAGE75_ISOLATION_RUNTIME_GATE=FAIL")
        raise SystemExit(1)
    print("STAGE75_ISOLATION_RUNTIME_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(main())
