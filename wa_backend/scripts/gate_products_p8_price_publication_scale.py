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
    seed_benchmark_prices,
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

            book_id = int(
                (
                    await app.execute(
                        text(
                            "SELECT id "
                            "FROM price_books "
                            "WHERE company_id = :company_id "
                            "ORDER BY id DESC LIMIT 1"
                        ),
                        {
                            "company_id": company_id,
                        },
                    )
                ).scalar_one()
            )

            await seed_benchmark_prices(
                app,
                company_id=company_id,
                each_uom_id=int(
                    ids["each_uom_id"]
                ),
                prefix=prefix,
            )

            base_revision = int(
                (
                    await app.execute(
                        text(
                            "SELECT COALESCE(MAX(revision), 0) "
                            "FROM price_publications "
                            "WHERE company_id = :company_id"
                        ),
                        {
                            "company_id": company_id,
                        },
                    )
                ).scalar_one()
            )
            request_prefix = (
                "p8-price-publication-scale-"
                + uuid4().hex
            )

            await app.execute(
                text(
                    "INSERT INTO price_publications "
                    "(company_id, price_book_id, revision, status, "
                    "effective_at, created_by, approved_by, "
                    "approved_at, published_at, request_id, "
                    "version, created_at, updated_at) "
                    "SELECT :company_id, :book_id, "
                    ":base_revision + gs, 'SUPERSEDED', "
                    "NOW() - INTERVAL '2 days', :actor_id, :actor_id, "
                    "NOW() - INTERVAL '2 days', "
                    "NOW() - INTERVAL '2 days', "
                    "md5(:request_prefix || ':' || gs::text)::uuid, "
                    "1, NOW(), NOW() "
                    "FROM generate_series(1, :row_count) AS gs"
                ),
                {
                    "company_id": company_id,
                    "book_id": book_id,
                    "base_revision": base_revision,
                    "actor_id": int(
                        pricing_actor.id
                    ),
                    "request_prefix": request_prefix,
                    "row_count": publication_rows,
                },
            )

            await app.execute(
                text(
                    "ANALYZE price_publications"
                )
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
                >= publication_rows
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
