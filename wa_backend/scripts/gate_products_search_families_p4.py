from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text


SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BACKEND))

import gate_products_read_contract_p2 as p2_gate
from api.simple_products import (
    _family_cursor,
    _family_next_cursor,
    families as list_families_endpoint,
    list_simple_products,
)
from models import Driver


RESULTS: list[tuple[str, bool, str]] = []


def record(
    name: str,
    ok: bool,
    detail: str = "",
) -> None:
    RESULTS.append(
        (name, bool(ok), detail)
    )
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (
            f" — {detail}"
            if detail
            else ""
        )
    )


def invalid_family_cursor(
    token: str,
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> bool:
    try:
        _family_cursor(
            token,
            company_id=company_id,
            search=search,
            limit=limit,
        )
    except HTTPException as exc:
        detail = exc.detail
        return (
            exc.status_code == 400
            and isinstance(detail, dict)
            and detail.get("code")
            == "INVALID_CURSOR"
        )
    return False


async def main() -> None:
    ids: dict[str, int] = {}

    try:
        ids = await p2_gate.bootstrap()
        company_id = ids["company_id"]

        family_token = _family_next_cursor(
            name="Alpha Family",
            family_id=101,
            company_id=company_id,
            search="  alpha  ",
            limit=2,
        )
        family_after = _family_cursor(
            family_token,
            company_id=company_id,
            search="alpha",
            limit=2,
        )
        record(
            "family cursor round-trips in normalized scope",
            family_after
            == ("alpha family", 101),
        )
        record(
            "family cursor rejects another search",
            invalid_family_cursor(
                family_token,
                company_id=company_id,
                search="beta",
                limit=2,
            ),
        )
        record(
            "family cursor rejects another company",
            invalid_family_cursor(
                family_token,
                company_id=ids[
                    "foreign_company_id"
                ],
                search="alpha",
                limit=2,
            ),
        )
        record(
            "family cursor rejects another page size",
            invalid_family_cursor(
                family_token,
                company_id=company_id,
                search="alpha",
                limit=3,
            ),
        )

        payload_part, signature_part = (
            family_token.split(".", 1)
        )
        tampered_family_token = (
            payload_part
            + "."
            + (
                "A"
                if signature_part[0]
                != "A"
                else "B"
            )
            + signature_part[1:]
        )
        record(
            "tampered family cursor fails closed",
            invalid_family_cursor(
                tampered_family_token,
                company_id=company_id,
                search="alpha",
                limit=2,
            ),
        )

        async with p2_gate.SessionApp() as app:
            await app.begin()
            await p2_gate.set_tenant(
                app,
                company_id,
            )
            tenant_ids = (
                await p2_gate.seed_tenant_transaction(
                    app,
                    ids,
                )
            )
            ids.update(tenant_ids)

            catalog_actor = await app.get(
                Driver,
                ids["catalog_driver_id"],
            )
            if catalog_actor is None:
                raise RuntimeError(
                    "seeded catalog actor is not visible"
                )

            barcode_value = (
                "998877665544"
            )
            await app.execute(
                text(
                    "INSERT INTO product_barcodes "
                    "(company_id, product_variant_id, "
                    "uom_id, barcode, barcode_type, "
                    "is_primary, valid_from, valid_to, "
                    "is_active, version, created_at, updated_at) "
                    "VALUES "
                    "(:company_id, :variant_id, :uom_id, "
                    ":barcode, 'INTERNAL', true, "
                    "NOW() - INTERVAL '1 minute', NULL, "
                    "true, 1, NOW(), NOW())"
                ),
                {
                    "company_id": company_id,
                    "variant_id": ids[
                        "variant_id"
                    ],
                    "uom_id": ids[
                        "each_uom_id"
                    ],
                    "barcode": barcode_value,
                },
            )

            for name in (
                "Alpha P4 Family",
                "Beta P4 Family",
                "Gamma P4 Family",
            ):
                await app.execute(
                    text(
                        "INSERT INTO products "
                        "(company_id, code, name, "
                        "version, created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :code, :name, "
                        "1, NOW(), NOW())"
                    ),
                    {
                        "company_id": company_id,
                        "code": (
                            "P4-"
                            + name.split()[0].upper()
                        ),
                        "name": name,
                    },
                )

            unfiltered = (
                await list_simple_products(
                    search=None,
                    cursor=None,
                    limit=50,
                    db=app,
                    actor=catalog_actor,
                )
            )
            rows = unfiltered.get(
                "items"
            )
            target = next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and row.get("id")
                    == ids["variant_id"]
                ),
                None,
            ) if isinstance(rows, list) else None

            if not isinstance(
                target,
                dict,
            ):
                raise RuntimeError(
                    "seeded product missing from P4 list"
                )
            sku = str(target["sku"])

            async def search_ids(
                value: str,
            ) -> list[int]:
                page = (
                    await list_simple_products(
                        search=value,
                        cursor=None,
                        limit=50,
                        db=app,
                        actor=catalog_actor,
                    )
                )
                items = page.get(
                    "items"
                )
                if not isinstance(
                    items,
                    list,
                ):
                    return []
                return [
                    int(item["id"])
                    for item in items
                    if isinstance(
                        item,
                        dict,
                    )
                    and isinstance(
                        item.get("id"),
                        int,
                    )
                ]

            record(
                "product search finds variant name",
                ids["variant_id"]
                in await search_ids(
                    "Catalog Item"
                ),
            )
            record(
                "product search finds family name",
                ids["variant_id"]
                in await search_ids(
                    "P2 Family"
                ),
            )
            record(
                "product search finds SKU",
                ids["variant_id"]
                in await search_ids(sku),
            )
            record(
                "product search finds active barcode",
                ids["variant_id"]
                in await search_ids(
                    barcode_value
                ),
            )
            record(
                "multi-token search ANDs tokens across identity fields",
                ids["variant_id"]
                in await search_ids(
                    "Catalog 9988"
                ),
            )
            record(
                "LIKE wildcards are escaped instead of broadening search",
                await search_ids("%%")
                == [],
            )

            first_family_page = (
                await list_families_endpoint(
                    search=None,
                    cursor=None,
                    limit=2,
                    db=app,
                    actor=catalog_actor,
                )
            )
            first_items = (
                first_family_page.get(
                    "items"
                )
            )
            next_cursor = (
                first_family_page.get(
                    "next_cursor"
                )
            )
            record(
                "family first page is bounded and advertises continuation",
                isinstance(
                    first_items,
                    list,
                )
                and len(first_items) == 2
                and first_family_page.get(
                    "has_more"
                )
                is True
                and isinstance(
                    next_cursor,
                    str,
                ),
            )

            second_family_page = (
                await list_families_endpoint(
                    search=None,
                    cursor=(
                        next_cursor
                        if isinstance(
                            next_cursor,
                            str,
                        )
                        else None
                    ),
                    limit=2,
                    db=app,
                    actor=catalog_actor,
                )
            )
            second_items = (
                second_family_page.get(
                    "items"
                )
            )
            first_ids = {
                int(item["id"])
                for item in first_items
                if isinstance(
                    item,
                    dict,
                )
            } if isinstance(
                first_items,
                list,
            ) else set()
            second_ids = {
                int(item["id"])
                for item in second_items
                if isinstance(
                    item,
                    dict,
                )
            } if isinstance(
                second_items,
                list,
            ) else set()
            record(
                "family continuation has no page overlap",
                bool(first_ids)
                and bool(second_ids)
                and first_ids.isdisjoint(
                    second_ids
                ),
            )

            family_search_page = (
                await list_families_endpoint(
                    search="Gamma",
                    cursor=None,
                    limit=2,
                    db=app,
                    actor=catalog_actor,
                )
            )
            family_search_items = (
                family_search_page.get(
                    "items"
                )
            )
            record(
                "family search filters before pagination",
                isinstance(
                    family_search_items,
                    list,
                )
                and len(
                    family_search_items
                )
                == 1
                and family_search_items[
                    0
                ].get("name")
                == "Gamma P4 Family",
            )

            await app.rollback()

    except Exception as exc:
        record(
            "P4 runtime gate completed without unexpected exception",
            False,
            repr(exc),
        )
    finally:
        cleanup_ok, cleanup_detail = (
            await p2_gate.cleanup(ids)
        )
        record(
            "P4 runtime gate removes committed seed data",
            cleanup_ok,
            cleanup_detail,
        )
        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()

    failures = [
        name
        for name, ok, _ in RESULTS
        if not ok
    ]
    print()
    print(
        f"CHECKS={len(RESULTS)}"
    )
    print(
        f"FAILURES={len(failures)}"
    )
    for failure in failures:
        print(
            f"FAILED_CHECK={failure}"
        )

    if failures:
        print(
            "PRODUCTS_SEARCH_FAMILIES_P4_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        "PRODUCTS_SEARCH_FAMILIES_P4_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
