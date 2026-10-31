"""R2 final 50k performance gate.

Runs only against the explicitly isolated disposable PostgreSQL target. The seed
creates one immutable 50,000-stocked-variant fixture; main and R2 then perform
read-only measurements against that exact same database state.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

CODE_ROOT = Path(os.environ["WANASAH_CODE_ROOT"]).resolve()
sys.path.insert(0, str(CODE_ROOT))

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import live_stock
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.live_stock_projection.service import (
    assert_live_stock_projection_ready,
    rebuild_live_stock_company,
)
from models import Permission, Role, UserLocationAccess, role_permissions
from tests.canonical_actor_fixtures import (
    load_company_owner_fixture,
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)

TARGET_DB = "wanasah_r2_perf_50k"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 55439
PRODUCTS = 50_000


def checked_url(name: str):
    from sqlalchemy.engine import make_url

    url = make_url(os.environ[name])
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host != TARGET_HOST
        or url.port != TARGET_PORT
        or url.database != TARGET_DB
    ):
        raise RuntimeError(f"{name} is not the isolated R2 performance database")
    return url


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def summary(values: list[float]) -> dict[str, float]:
    return {
        "min_ms": round(min(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


async def seed_fixture(fixture_path: Path) -> None:
    admin_url = checked_url("DATABASE_URL_MIGRATION")
    engine = create_async_engine(admin_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await db.begin()
            uom_id = (
                await db.execute(
                    text(
                        """
                        INSERT INTO uom (name, code)
                        VALUES ('R2 performance each', 'EACH')
                        ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name
                        RETURNING id
                        """
                    )
                )
            ).scalar_one()
            company_id = int(
                (
                    await db.execute(
                        text(
                            """
                            INSERT INTO companies
                                (name, company_code, is_active,
                                 subscription_status, currency_code,
                                 timezone, created_at)
                            VALUES
                                ('R2 Performance 50k', :code, true,
                                 'active', 'JOD', 'Asia/Amman', NOW())
                            RETURNING id
                            """
                        ),
                        {"code": "R2P-" + uuid4().hex[:16]},
                    )
                ).scalar_one()
            )
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_id)},
            )
            branch_id = int(
                (
                    await db.execute(
                        text(
                            """
                            INSERT INTO branches
                                (company_id, name, branch_code, is_active, created_at)
                            VALUES (:c, 'R2 Perf Branch', :code, true, NOW())
                            RETURNING id
                            """
                        ),
                        {"c": company_id, "code": "R2B-" + uuid4().hex[:12]},
                    )
                ).scalar_one()
            )
            warehouse_id = int(
                (
                    await db.execute(
                        text(
                            """
                            INSERT INTO inventory_locations
                                (company_id, branch_id, name, code,
                                 location_type, vehicle_id, system_role,
                                 is_system_managed, version, is_active,
                                 created_at, updated_at)
                            VALUES
                                (:c, :b, 'R2 Perf Warehouse', :code,
                                 'WAREHOUSE', NULL, NULL, false, 1, true,
                                 NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "b": branch_id,
                            "code": "R2W-" + uuid4().hex[:12],
                        },
                    )
                ).scalar_one()
            )
            product_id = int(
                (
                    await db.execute(
                        text(
                            """
                            INSERT INTO products
                                (company_id, code, name, version, created_at, updated_at)
                            VALUES (:c, :code, 'R2 Performance Family', 1, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {"c": company_id, "code": "R2P-" + uuid4().hex[:12]},
                    )
                ).scalar_one()
            )

            owner = await seed_company_owner_fixture(
                db, company_id, password="R2PerfOwner123"
            )
            ordinary = await seed_ordinary_backoffice_fixture(
                db, company_id, password="R2PerfReader123"
            )
            permission_id = await db.scalar(
                select(Permission.id).where(Permission.code == "inventory.read")
            )
            if permission_id is None:
                raise RuntimeError("inventory.read permission is missing")
            role = Role(company_id=company_id, name="R2 perf restricted reader")
            db.add(role)
            await db.flush()
            await db.execute(
                role_permissions.insert().values(
                    company_id=company_id,
                    role_id=role.id,
                    permission_id=int(permission_id),
                )
            )
            db.add(
                UserLocationAccess(
                    company_id=company_id,
                    driver_id=ordinary.driver_id,
                    location_id=warehouse_id,
                    role_id=role.id,
                )
            )
            await db.flush()

            await db.execute(
                text(
                    """
                    INSERT INTO product_variants
                        (company_id, product_id, base_uom_id, name, sku,
                         quantity_scale, quantity_step,
                         lot_control_mode, expiry_control_mode,
                         lifecycle_status, operational_hold,
                         lifecycle_revision, version, published_at,
                         packs_per_carton, package_uses_base_barcode,
                         default_max_samples_per_day,
                         created_at, updated_at)
                    SELECT
                        :c, :p, :u,
                        'Common R2 ' || lpad(g::text, 6, '0'),
                        'R2-50K-' || lpad(g::text, 6, '0'),
                        6, 1.000000,
                        'OPTIONAL', 'OPTIONAL',
                        'ACTIVE', 'NONE',
                        1, 1, NOW(),
                        50, false, 0,
                        NOW(), NOW()
                    FROM generate_series(1, :products) AS g
                    """
                ),
                {"c": company_id, "p": product_id, "u": int(uom_id), "products": PRODUCTS},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO product_batches
                        (company_id, product_variant_id, batch_number,
                         production_date, expiry_date, disposition,
                         disposition_revision, is_active, created_at, updated_at)
                    SELECT
                        :c, id, 'R2-B-' || id::text,
                        NULL, NULL, 'RELEASED', 1, true, NOW(), NOW()
                    FROM product_variants
                    WHERE company_id=:c
                    """
                ),
                {"c": company_id},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO inventory_balances
                        (company_id, location_id, product_variant_id,
                         batch_id, stock_status, on_hand_quantity,
                         reserved_quantity, last_updated)
                    SELECT
                        :c, :w, v.id, b.id, 'AVAILABLE',
                        1.000000, 0.000000, NOW()
                    FROM product_variants v
                    JOIN product_batches b
                      ON b.company_id=v.company_id
                     AND b.product_variant_id=v.id
                    WHERE v.company_id=:c
                    """
                ),
                {"c": company_id, "w": warehouse_id},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO inventory_live_stock_projection
                        (company_id, warehouse_location_id, product_variant_id,
                         variant_name, lifecycle_status, operational_hold,
                         warehouse_on_hand, warehouse_reserved,
                         warehouse_sellable_on_hand, warehouse_sellable_reserved,
                         blocked_status_packs, recalled_packs, damaged_packs,
                         vehicle_packs, minimum_quantity, has_active_policy,
                         is_low_stock, has_warehouse_presence, has_vehicle_presence,
                         next_transition_date, computed_for_date, revision, updated_at)
                    SELECT
                        :c, :w, v.id,
                        v.name, 'ACTIVE', 'NONE',
                        1.000000, 0.000000,
                        1.000000, 0.000000,
                        0.000000, 0.000000, 0.000000,
                        0.000000, 0.000000, false,
                        false, true, false,
                        NULL,
                        (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Amman')::date,
                        1, NOW()
                    FROM product_variants v
                    WHERE v.company_id=:c
                    """
                ),
                {"c": company_id, "w": warehouse_id},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO inventory_live_stock_company_summaries
                        (company_id, active_variant_count,
                         projection_state, projection_version, revision,
                         last_rebuilt_at, last_verified_at, updated_at)
                    VALUES
                        (:c, :products, 'READY', 1, 1, NOW(), NOW(), NOW())
                    """
                ),
                {"c": company_id, "products": PRODUCTS},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO inventory_live_stock_warehouse_summaries
                        (company_id, warehouse_location_id,
                         alert_count, nonactive_visible_count,
                         projected_row_count, projection_state,
                         projection_version, revision,
                         last_rebuilt_at, last_verified_at, updated_at)
                    VALUES
                        (:c, :w, 0, 0, :products, 'READY',
                         1, 1, NOW(), NOW(), NOW())
                    """
                ),
                {"c": company_id, "w": warehouse_id, "products": PRODUCTS},
            )
            await db.commit()

        async with engine.connect() as conn:
            for table in (
                "product_variants",
                "product_batches",
                "inventory_balances",
                "inventory_live_stock_projection",
                "inventory_live_stock_company_summaries",
                "inventory_live_stock_warehouse_summaries",
            ):
                await conn.execute(text(f"ANALYZE {table}"))
            await conn.commit()

        fixture = {
            "products": PRODUCTS,
            "company_id": company_id,
            "warehouse_id": warehouse_id,
            "owner_driver_id": owner.driver_id,
            "ordinary_driver_id": ordinary.driver_id,
            "ordinary_principal_id": ordinary.context.principal_id,
            "ordinary_backoffice_user_id": ordinary.context.backoffice_user_id,
        }
        fixture_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
        print("R2_PERF_SEED " + json.dumps(fixture, sort_keys=True), flush=True)
    finally:
        await engine.dispose()


@asynccontextmanager
async def runtime_session(engine, company_id: int):
    async with engine.connect() as conn:
        db = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            await db.begin()
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_id)},
            )
            await db.execute(text("SET LOCAL statement_timeout='60000ms'"))
            yield db
            await db.rollback()
        finally:
            await db.close()


def restricted_access(db, fixture):
    return BackofficeCapabilityAccess(
        db,
        BackofficeAuthorizationSubject(
            principal_id=int(fixture["ordinary_principal_id"]),
            backoffice_user_id=int(fixture["ordinary_backoffice_user_id"]),
            company_id=int(fixture["company_id"]),
            is_company_owner=False,
            legacy_grant_driver_id=int(fixture["ordinary_driver_id"]),
        ),
    )


def cursor_args(fixture, db, access, *, search=None):
    return dict(
        location_id=int(fixture["warehouse_id"]),
        cursor=None,
        limit=50,
        search=search,
        only_alerts=False,
        stock_state="all",
        family_id=None,
        has_reserved=False,
        has_unavailable=False,
        has_damaged=False,
        has_recalled=False,
        has_vehicle=False,
        minimum_unset=False,
        sort="name_asc",
        db=db,
        access=access,
    )


async def invoke(engine, fixture, kind: str, actor: str, *, search=None, capture=False):
    records = []
    starts = []

    def before(_conn, _cursor, statement, parameters, _context, _many):
        starts.append(perf_counter())
        records.append({"sql": statement, "parameters": parameters})

    def after(*_args):
        records[-1]["driver_wall_ms"] = (perf_counter() - starts.pop()) * 1000

    async with runtime_session(engine, int(fixture["company_id"])) as db:
        access = (
            (await load_company_owner_fixture(db, int(fixture["company_id"]))).access(db)
            if actor == "owner"
            else restricted_access(db, fixture)
        )
        if capture:
            event.listen(engine.sync_engine, "before_cursor_execute", before)
            event.listen(engine.sync_engine, "after_cursor_execute", after)
        try:
            started = perf_counter()
            if kind == "readiness":
                await assert_live_stock_projection_ready(
                    db,
                    company_id=int(fixture["company_id"]),
                    warehouse_location_id=int(fixture["warehouse_id"]),
                )
                result_count = None
            else:
                page = await live_stock.get_warehouse_inventory(
                    **cursor_args(fixture, db, access, search=search)
                )
                result_count = len(page["items"])
                if result_count != 50:
                    raise AssertionError(f"expected 50 cursor rows, got {result_count}")
            wall_ms = (perf_counter() - started) * 1000
        finally:
            if capture:
                event.remove(engine.sync_engine, "before_cursor_execute", before)
                event.remove(engine.sync_engine, "after_cursor_execute", after)
        return {
            "wall_ms": wall_ms,
            "sql_driver_ms": sum(float(r.get("driver_wall_ms", 0.0)) for r in records),
            "sql_count": len(records) if capture else None,
            "records": records,
            "returned": result_count,
        }


def classify_sql(sql: str) -> str:
    lowered = sql.lower()
    if "live_stock_expected_truth" in lowered or "live_stock_truth_keys" in lowered:
        return "truth_parity"
    if "inventory_page_candidates" in lowered and "inventory_detail_keys" in lowered:
        return "cursor_page"
    if "inventory_live_stock_company_summaries" in lowered and "has_due_transition" in lowered:
        return "readiness_summary"
    if "user_location_access" in lowered or "role_permissions" in lowered:
        return "authorization"
    return "other"


def plan_resources(node: dict) -> dict[str, float]:
    keys = (
        "Shared Hit Blocks",
        "Shared Read Blocks",
        "Shared Dirtied Blocks",
        "Shared Written Blocks",
        "Local Hit Blocks",
        "Local Read Blocks",
        "Temp Read Blocks",
        "Temp Written Blocks",
    )
    result = {k: float(node.get(k, 0) or 0) for k in keys}
    result["Actual Rows Sum"] = float(node.get("Actual Rows", 0) or 0)
    result["Plan Rows Sum"] = float(node.get("Plan Rows", 0) or 0)
    for child in node.get("Plans", []) or []:
        child_result = plan_resources(child)
        for key, value in child_result.items():
            result[key] = result.get(key, 0.0) + value
    return result


async def explain_records(db: AsyncSession, records: list[dict]) -> list[dict]:
    explained = []
    connection = await db.connection()
    for index, record in enumerate(records):
        sql = str(record["sql"]).lstrip()
        if not (sql.upper().startswith("SELECT") or sql.upper().startswith("WITH")):
            continue
        result = await connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
            record["parameters"],
        )
        raw = result.scalar_one()
        document = raw if isinstance(raw, list) else json.loads(raw)
        top = document[0]
        resources = plan_resources(top["Plan"])
        explained.append(
            {
                "index": index,
                "role": classify_sql(sql),
                "execution_ms": round(float(top["Execution Time"]), 3),
                "planning_ms": round(float(top["Planning Time"]), 3),
                "driver_wall_ms": round(float(record.get("driver_wall_ms", 0.0)), 3),
                "resources": {k: int(v) for k, v in resources.items()},
                "plan": top,
            }
        )
    return explained


async def capture_with_explain(engine, fixture, kind, actor, *, search=None):
    async with runtime_session(engine, int(fixture["company_id"])) as db:
        access = (
            (await load_company_owner_fixture(db, int(fixture["company_id"]))).access(db)
            if actor == "owner"
            else restricted_access(db, fixture)
        )
        records = []
        starts = []

        def before(_conn, _cursor, statement, parameters, _context, _many):
            starts.append(perf_counter())
            records.append({"sql": statement, "parameters": parameters})

        def after(*_args):
            records[-1]["driver_wall_ms"] = (perf_counter() - starts.pop()) * 1000

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        event.listen(engine.sync_engine, "after_cursor_execute", after)
        try:
            if kind == "readiness":
                await assert_live_stock_projection_ready(
                    db,
                    company_id=int(fixture["company_id"]),
                    warehouse_location_id=int(fixture["warehouse_id"]),
                )
            else:
                page = await live_stock.get_warehouse_inventory(
                    **cursor_args(fixture, db, access, search=search)
                )
                if len(page["items"]) != 50:
                    raise AssertionError("cursor explain call did not return 50 rows")
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
            event.remove(engine.sync_engine, "after_cursor_execute", after)

        plans = await explain_records(db, records)
        return {
            "sql_count": len(records),
            "captured_driver_ms": round(
                sum(float(r.get("driver_wall_ms", 0.0)) for r in records), 3
            ),
            "plans": plans,
        }


async def benchmark(label: str, fixture_path: Path, output: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    runtime_url = checked_url("DATABASE_URL")
    engine = create_async_engine(
        runtime_url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    scenarios = [
        ("readiness_owner", "readiness", "owner", None, 9),
        ("cursor_owner", "cursor", "owner", None, 7),
        ("cursor_restricted", "cursor", "restricted", None, 7),
        ("cursor_restricted_broad_search", "cursor", "restricted", "Common", 5),
    ]
    results = {}
    try:
        # R3 raises the semantic projection version so stale v1 Route-attributed
        # rows fail closed. The R2 comparison intentionally reuses one seeded DB;
        # prepare the candidate code's canonical projection outside timed samples.
        if label == "r2":
            async with runtime_session(
                engine, int(fixture["company_id"])
            ) as db:
                # Projection-v2 deployment preparation is outside every timed
                # sample. The 50k rebuild can legitimately exceed the normal
                # 60s read-query ceiling, so widen only this one transaction;
                # measured Live Stock calls continue to use the original limit.
                await db.execute(
                    text("SET LOCAL statement_timeout='300000ms'")
                )
                await rebuild_live_stock_company(
                    db,
                    company_id=int(fixture["company_id"]),
                )
                await db.commit()
        for name, kind, actor, search, runs in scenarios:
            for _ in range(3):
                await invoke(engine, fixture, kind, actor, search=search)
            wall = []
            for _ in range(runs):
                result = await invoke(engine, fixture, kind, actor, search=search)
                wall.append(float(result["wall_ms"]))
            capture = await invoke(
                engine, fixture, kind, actor, search=search, capture=True
            )
            explained = await capture_with_explain(
                engine, fixture, kind, actor, search=search
            )
            results[name] = {
                "wall": summary(wall),
                "sample_count": runs,
                "captured_sql_count": capture["sql_count"],
                "captured_sql_driver_ms": round(float(capture["sql_driver_ms"]), 3),
                "explain": explained,
            }
            print(
                "R2_PERF_SAMPLE "
                + json.dumps(
                    {
                        "label": label,
                        "scenario": name,
                        "wall": results[name]["wall"],
                        "sql_count": capture["sql_count"],
                        "sql_driver_ms": results[name]["captured_sql_driver_ms"],
                        "plan_roles": [
                            {
                                "role": p["role"],
                                "execution_ms": p["execution_ms"],
                                "shared_hit": p["resources"]["Shared Hit Blocks"],
                                "shared_read": p["resources"]["Shared Read Blocks"],
                                "temp_read": p["resources"]["Temp Read Blocks"],
                                "temp_written": p["resources"]["Temp Written Blocks"],
                                "actual_rows_sum": p["resources"]["Actual Rows Sum"],
                            }
                            for p in explained["plans"]
                        ],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        payload = {
            "label": label,
            "products": int(fixture["products"]),
            "code_root": str(CODE_ROOT),
            "results": results,
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    finally:
        await engine.dispose()


def ratio(new, old):
    if old == 0:
        return None
    return round(float(new) / float(old), 3)


def compare(main_path: Path, r2_path: Path, output: Path) -> None:
    main = json.loads(main_path.read_text(encoding="utf-8"))
    r2 = json.loads(r2_path.read_text(encoding="utf-8"))
    scenarios = {}
    for name in main["results"]:
        m = main["results"][name]
        n = r2["results"][name]
        scenarios[name] = {
            "main_median_ms": m["wall"]["median_ms"],
            "r2_median_ms": n["wall"]["median_ms"],
            "median_ratio": ratio(n["wall"]["median_ms"], m["wall"]["median_ms"]),
            "main_p95_ms": m["wall"]["p95_ms"],
            "r2_p95_ms": n["wall"]["p95_ms"],
            "p95_ratio": ratio(n["wall"]["p95_ms"], m["wall"]["p95_ms"]),
            "main_sql_count": m["captured_sql_count"],
            "r2_sql_count": n["captured_sql_count"],
        }
    payload = {
        "products": main["products"],
        "scenarios": scenarios,
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("R2_PERF_COMPARISON " + json.dumps(payload, sort_keys=True), flush=True)


def parse_args():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("--fixture", type=Path, required=True)
    bench = sub.add_parser("bench")
    bench.add_argument("--label", required=True)
    bench.add_argument("--fixture", type=Path, required=True)
    bench.add_argument("--output", type=Path, required=True)
    comp = sub.add_parser("compare")
    comp.add_argument("--main", type=Path, required=True)
    comp.add_argument("--r2", type=Path, required=True)
    comp.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


async def async_main(args):
    if args.command == "seed":
        await seed_fixture(args.fixture)
    elif args.command == "bench":
        await benchmark(args.label, args.fixture, args.output)


def main():
    args = parse_args()
    if args.command == "compare":
        compare(args.main, args.r2, args.output)
    else:
        asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
