from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from sqlalchemy import text

import gate_products_read_contract_p2 as p2_gate
from audit_products_p4_performance import (
    QueryProbe,
    bounded_env_int,
    call_endpoint,
    cleanup_committed_catalog,
    endpoint_kwargs,
    main_product_query,
    seed_committed_catalog,
    summarize_plan,
    walk_plan,
)
from models import Driver


DEFAULT_PUBLICATIONS = 10_000
MIN_PUBLICATIONS = 1_000
MAX_PUBLICATIONS = 50_000


async def explain_raw(session, sample):
    connection = await session.connection()
    result = await connection.exec_driver_sql(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        + sample.statement,
        sample.parameters,
    )
    raw = result.scalar_one()
    document = (
        json.loads(raw)
        if isinstance(raw, str)
        else raw
    )
    root_document = (
        document[0]
        if isinstance(document, list)
        and document
        else document
    )
    if not isinstance(root_document, dict):
        raise RuntimeError(
            "EXPLAIN JSON document is invalid."
        )
    root = root_document.get("Plan")
    if not isinstance(root, dict):
        raise RuntimeError(
            "EXPLAIN JSON plan root is missing."
        )
    return root, summarize_plan(document)


def publication_scan_nodes(root):
    nodes = []
    for node in walk_plan(root):
        if (
            node.get("Relation Name")
            != "price_publications"
        ):
            continue
        node_type = str(
            node.get("Node Type", "")
        )
        if "Scan" not in node_type:
            continue
        nodes.append(
            {
                "node_type": node_type,
                "index": node.get(
                    "Index Name"
                ),
                "loops": int(
                    node.get(
                        "Actual Loops",
                        0,
                    )
                    or 0
                ),
                "actual_rows": int(
                    node.get(
                        "Actual Rows",
                        0,
                    )
                    or 0
                ),
                "rows_removed": int(
                    node.get(
                        "Rows Removed by Filter",
                        0,
                    )
                    or 0
                ),
            }
        )
    return nodes


async def seed_committed_publication_scale(
    *,
    company_id: int,
    publication_rows: int,
) -> int:
    marker = uuid4().hex
    async with p2_gate.SessionSU() as su:
        await su.begin()

        existing = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM price_publications "
                        "WHERE company_id = :company_id"
                    ),
                    {
                        "company_id": company_id,
                    },
                )
            ).scalar_one()
        )
        if existing != 0:
            raise RuntimeError(
                "Publication scale company is not clean before seeding."
            )

        actor_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO drivers "
                        "(company_id, username, password_hash, "
                        "full_name, is_active, is_admin, created_at) "
                        "VALUES "
                        "(:company_id, :username, 'x', "
                        "'P8 Publication Scale Seeder', "
                        "true, false, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "username": (
                            "p8pub_"
                            + marker[:10]
                        ),
                    },
                )
            ).scalar_one()
        )

        book_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO price_books "
                        "(company_id, code, name, currency_code, "
                        "status, applicability_metadata, version, "
                        "created_by, created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :code, "
                        "'P8 Publication Scale Book', 'JOD', "
                        "'ACTIVE', '{}'::jsonb, 1, :actor_id, "
                        "NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "code": (
                            "P8PUB-"
                            + marker[:10].upper()
                        ),
                        "actor_id": actor_id,
                    },
                )
            ).scalar_one()
        )

        await su.execute(
            text(
                "INSERT INTO price_publications "
                "(company_id, price_book_id, revision, status, "
                "effective_at, created_by, approved_by, "
                "approved_at, published_at, request_id, "
                "version, created_at, updated_at) "
                "SELECT :company_id, :book_id, "
                "gs + 1, 'DRAFT', "
                "NULL, :actor_id, NULL, "
                "NULL, NULL, "
                "md5(:request_prefix || ':' || gs::text)::uuid, "
                "1, NOW(), NOW() "
                "FROM generate_series(1, :row_count) AS gs"
            ),
            {
                "company_id": company_id,
                "book_id": book_id,
                "actor_id": actor_id,
                "request_prefix": (
                    "p8-price-publication-scale-"
                    + marker
                ),
                "row_count": publication_rows,
            },
        )
        await su.commit()

    async with p2_gate.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                "ANALYZE price_publications"
            )
        )
        count = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM price_publications "
                        "WHERE company_id = :company_id"
                    ),
                    {
                        "company_id": company_id,
                    },
                )
            ).scalar_one()
        )
        await su.commit()
    return count


async def seed_endpoint_benchmark_prices(
    app,
    *,
    company_id: int,
    each_uom_id: int,
    prefix: str,
) -> None:
    book_id = int(
        (
            await app.execute(
                text(
                    "SELECT id FROM price_books "
                    "WHERE company_id = :company_id "
                    "AND code LIKE 'P2-BOOK-%' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {
                    "company_id": company_id,
                },
            )
        ).scalar_one()
    )
    publication_id = int(
        (
            await app.execute(
                text(
                    "SELECT id FROM price_publications "
                    "WHERE company_id = :company_id "
                    "AND price_book_id = :book_id "
                    "AND status = 'PUBLISHED' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {
                    "company_id": company_id,
                    "book_id": book_id,
                },
            )
        ).scalar_one()
    )

    await app.execute(
        text(
            "WITH seeded AS ("
            "SELECT pv.id AS variant_id, "
            "RIGHT(p.code, 6)::integer AS n "
            "FROM product_variants AS pv "
            "JOIN products AS p "
            "ON p.company_id = pv.company_id "
            "AND p.id = pv.product_id "
            "WHERE pv.company_id = :company_id "
            "AND p.code LIKE :prefix_like"
            ") "
            "INSERT INTO price_book_entries "
            "(company_id, price_book_id, publication_id, "
            "product_variant_id, uom_id, amount, effectivity, "
            "priority, is_published, metadata, version, "
            "created_at, updated_at) "
            "SELECT :company_id, :book_id, :publication_id, "
            "seeded.variant_id, :uom_id, "
            "(1 + (seeded.n % 100))::numeric(20, 6), "
            "tstzrange(NOW() - INTERVAL '1 day', NULL, '[)'), "
            "0, true, "
            "'{\"managed_by\":\"p8_publication_scale\"}'::jsonb, "
            "1, NOW(), NOW() "
            "FROM seeded "
            "WHERE seeded.n % 2 = 0"
        ),
        {
            "company_id": company_id,
            "book_id": book_id,
            "publication_id": publication_id,
            "uom_id": each_uom_id,
            "prefix_like": prefix + "-%",
        },
    )


async def restore_publication_stats() -> None:
    async with p2_gate.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                "ANALYZE price_publications"
            )
        )
        await su.commit()


async def main() -> None:
    ids: dict[str, int] = {}
    prefix = (
        "P8PUB"
        + uuid4().hex[:8].upper()
    )
    publication_rows = bounded_env_int(
        "P8_PRICE_PUBLICATION_ROWS",
        DEFAULT_PUBLICATIONS,
        MIN_PUBLICATIONS,
        MAX_PUBLICATIONS,
    )
    probe = QueryProbe()
    attached = False
    passed = False

    print(
        "PRICE_PUBLICATION_SCALE_ROWS="
        f"{publication_rows}"
    )

    try:
        ids = await p2_gate.bootstrap()
        await seed_committed_catalog(
            ids,
            prefix=prefix,
            row_count=1_000,
        )
        company_id = int(
            ids["company_id"]
        )
        committed_count = (
            await seed_committed_publication_scale(
                company_id=company_id,
                publication_rows=publication_rows,
            )
        )
        print(
            "PRICE_PUBLICATION_SCALE_COMMITTED_COUNT="
            f"{committed_count}"
        )

        async with p2_gate.SessionApp() as app:
            await app.begin()
            await p2_gate.set_tenant(
                app,
                company_id,
            )
            await app.execute(
                text(
                    "SET LOCAL statement_timeout = '30s'"
                )
            )
            ids.update(
                await p2_gate.seed_tenant_transaction(
                    app,
                    ids,
                )
            )

            pricing_actor = await app.get(
                Driver,
                ids["pricing_driver_id"],
            )
            if pricing_actor is None:
                raise RuntimeError(
                    "Pricing scale actor is not visible."
                )

            await seed_endpoint_benchmark_prices(
                app,
                company_id=company_id,
                each_uom_id=int(
                    ids["each_uom_id"]
                ),
                prefix=prefix,
            )

            publication_count = int(
                (
                    await app.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM price_publications "
                            "WHERE company_id = :company_id"
                        ),
                        {
                            "company_id": company_id,
                        },
                    )
                ).scalar_one()
            )
            print(
                "PRICE_PUBLICATION_SCALE_COUNT="
                f"{publication_count}"
            )

            await call_endpoint(
                app,
                pricing_actor,
                endpoint_kwargs(
                    has_price=True,
                    limit=50,
                ),
            )

            probe.attach()
            attached = True
            probe.start()
            page = await call_endpoint(
                app,
                pricing_actor,
                endpoint_kwargs(
                    has_price=True,
                    limit=50,
                ),
            )
            samples = probe.stop()

            captured = main_product_query(
                samples
            )
            if captured is None:
                raise RuntimeError(
                    "Scaled has_price main Product query was not captured."
                )

            root, plan = await explain_raw(
                app,
                captured,
            )
            scans = publication_scan_nodes(
                root
            )

            print(
                "PRICE_PUBLICATION_SCALE_PLAN "
                f"execution_ms={plan['execution_ms']:.3f} "
                f"shared_hit={plan['shared_hit']} "
                f"shared_read={plan['shared_read']} "
                f"scans={'|'.join(plan['scans']) or '-'} "
                f"indexes={'|'.join(plan['indexes']) or '-'}"
            )
            for node in scans:
                print(
                    "PRICE_PUBLICATION_SCAN "
                    f"node={node['node_type']} "
                    f"index={node['index'] or '-'} "
                    f"loops={node['loops']} "
                    f"actual_rows={node['actual_rows']} "
                    f"rows_removed={node['rows_removed']}"
                )

            repeated_full_scan = any(
                node["node_type"]
                == "Seq Scan"
                and int(node["loops"]) > 1
                for node in scans
            )
            page_items = page.get(
                "items"
            )
            enough_rows = (
                publication_count
                >= publication_rows + 1
            )
            page_ok = (
                isinstance(
                    page_items,
                    list,
                )
                and len(page_items)
                == 50
            )

            if not scans:
                raise RuntimeError(
                    "Scaled plan did not expose a price_publications scan node."
                )
            if not enough_rows:
                raise RuntimeError(
                    "Price publication scale seed is incomplete."
                )
            if not page_ok:
                raise RuntimeError(
                    "Scaled has_price page is not the expected 50 rows."
                )
            if repeated_full_scan:
                raise RuntimeError(
                    "Repeated Seq Scan on scaled price_publications detected."
                )

            print(
                "PRICE_PUBLICATION_SCALE_DECISION="
                "NO_REPEATED_FULL_SCAN"
            )
            passed = True
            await app.rollback()

    finally:
        if attached:
            probe.detach()

        cleanup_ok, cleanup_detail = (
            await cleanup_committed_catalog(
                ids,
                prefix=prefix,
            )
        )
        try:
            await restore_publication_stats()
            stats_ok = True
            stats_detail = ""
        except Exception as exc:
            stats_ok = False
            stats_detail = (
                f"{type(exc).__name__}: {exc}"
            )

        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()

        print(
            "PRICE_PUBLICATION_SCALE_CLEANUP="
            + (
                "PASS"
                if cleanup_ok
                else "FAIL"
            )
            + (
                f" detail={cleanup_detail}"
                if cleanup_detail
                else ""
            )
        )
        print(
            "PRICE_PUBLICATION_STATS_RESTORED="
            + (
                "PASS"
                if stats_ok
                else "FAIL"
            )
            + (
                f" detail={stats_detail}"
                if stats_detail
                else ""
            )
        )

        if (
            not passed
            or not cleanup_ok
            or not stats_ok
        ):
            print(
                "PRODUCTS_P8_PRICE_PUBLICATION_SCALE_GATE=FAIL"
            )
            raise SystemExit(1)

    print(
        "PRODUCTS_P8_PRICE_PUBLICATION_SCALE_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
