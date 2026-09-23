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
    _product_cursor,
    _product_next_cursor,
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



def invalid_product_cursor(
    token: str,
    **scope,
) -> bool:
    try:
        _product_cursor(
            token,
            **scope,
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
            sort_name="alpha family",
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

        long_family_name = "ع" * 150
        long_family_token = _family_next_cursor(
            sort_name=long_family_name,
            family_id=202,
            company_id=company_id,
            search=None,
            limit=50,
        )
        record(
            "family cursor bound supports maximum Unicode family names",
            len(long_family_token) <= 2048
            and _family_cursor(
                long_family_token,
                company_id=company_id,
                search=None,
                limit=50,
            )
            == (
                long_family_name,
                202,
            ),
        )


        product_scope = {
            "company_id": company_id,
            "search": "  P4   Filter ",
            "family_id": 77,
            "lifecycle": "ACTIVE",
            "tracking_type": "LOT",
            "simple_compatible": True,
            "has_barcode": False,
            "has_price": None,
            "lot_tracked": True,
            "expiry_tracked": False,
            "sort_by": "name",
            "sort_dir": "asc",
            "limit": 2,
        }
        product_token = _product_next_cursor(
            sort_key="alpha p4 filter item",
            variant_id=303,
            **product_scope,
        )
        record(
            "product cursor round-trips composite key in normalized scope",
            _product_cursor(
                product_token,
                **{
                    **product_scope,
                    "search": "p4 filter",
                },
            )
            == (
                "alpha p4 filter item",
                303,
            ),
        )
        record(
            "product cursor rejects another filter scope",
            invalid_product_cursor(
                product_token,
                **{
                    **product_scope,
                    "family_id": 78,
                },
            ),
        )
        record(
            "product cursor rejects another sort direction",
            invalid_product_cursor(
                product_token,
                **{
                    **product_scope,
                    "sort_dir": "desc",
                },
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

            pricing_actor = await app.get(
                Driver,
                ids["pricing_driver_id"],
            )
            if pricing_actor is None:
                raise RuntimeError(
                    "seeded pricing actor is not visible"
                )

            async def seed_filter_variant(
                *,
                code: str,
                family_name: str,
                name: str,
                sku: str,
                lot_mode: str,
                expiry_mode: str,
                lifecycle: str,
                packs_per_carton: int,
            ) -> tuple[int, int]:
                product_id = int(
                    (
                        await app.execute(
                            text(
                                "INSERT INTO products "
                                "(company_id, code, name, "
                                "version, created_at, updated_at) "
                                "VALUES "
                                "(:company_id, :code, :name, "
                                "1, NOW(), NOW()) "
                                "RETURNING id"
                            ),
                            {
                                "company_id": company_id,
                                "code": code,
                                "name": family_name,
                            },
                        )
                    ).scalar_one()
                )
                variant_id = int(
                    (
                        await app.execute(
                            text(
                                "INSERT INTO product_variants "
                                "(company_id, product_id, base_uom_id, "
                                "name, sku, quantity_scale, quantity_step, "
                                "lot_control_mode, expiry_control_mode, "
                                "lifecycle_status, operational_hold, "
                                "lifecycle_revision, version, published_at, "
                                "retired_at, archived_at, packs_per_carton, "
                                "package_uses_base_barcode, "
                                "default_max_samples_per_day, "
                                "created_at, updated_at) "
                                "VALUES "
                                "(:company_id, :product_id, :uom_id, "
                                ":name, :sku, 0, 1, :lot_mode, "
                                ":expiry_mode, :lifecycle, 'NONE', "
                                "1, 1, NOW() - INTERVAL '2 days', "
                                "CASE WHEN :retiring_lifecycle = 'RETIRING' "
                                "THEN NOW() - INTERVAL '1 day' "
                                "ELSE NULL END, NULL, :packs, false, 0, "
                                "NOW(), NOW()) "
                                "RETURNING id"
                            ),
                            {
                                "company_id": company_id,
                                "product_id": product_id,
                                "uom_id": ids[
                                    "each_uom_id"
                                ],
                                "name": name,
                                "sku": sku,
                                "lot_mode": lot_mode,
                                "expiry_mode":
                                    expiry_mode,
                                "lifecycle":
                                    lifecycle,
                                "retiring_lifecycle":
                                    lifecycle,
                                "packs":
                                    packs_per_carton,
                            },
                        )
                    ).scalar_one()
                )
                return product_id, variant_id

            (
                alpha_family_id,
                alpha_variant_id,
            ) = await seed_filter_variant(
                code="P4-FILTER-A",
                family_name=
                    "Alpha P4 Filter Family",
                name="Alpha P4 Filter Item",
                sku="P4-A-FILTER",
                lot_mode="REQUIRED",
                expiry_mode="NONE",
                lifecycle="ACTIVE",
                packs_per_carton=1,
            )
            (
                beta_family_id,
                beta_variant_id,
            ) = await seed_filter_variant(
                code="P4-FILTER-B",
                family_name=
                    "Beta P4 Filter Family",
                name="Beta P4 Filter Item",
                sku="P4-B-FILTER",
                lot_mode="NONE",
                expiry_mode="REQUIRED",
                lifecycle="ACTIVE",
                packs_per_carton=1,
            )
            (
                delta_family_id,
                delta_variant_id,
            ) = await seed_filter_variant(
                code="P4-FILTER-D",
                family_name=
                    "Delta P4 Filter Family",
                name="Delta P4 Filter Item",
                sku="P4-D-FILTER",
                lot_mode="NONE",
                expiry_mode="NONE",
                lifecycle="ACTIVE",
                packs_per_carton=1,
            )
            (
                gamma_family_id,
                gamma_variant_id,
            ) = await seed_filter_variant(
                code="P4-FILTER-G",
                family_name=
                    "Gamma P4 Filter Family",
                name="Gamma P4 Filter Item",
                sku="P4-G-FILTER",
                lot_mode="REQUIRED",
                expiry_mode="REQUIRED",
                lifecycle="RETIRING",
                packs_per_carton=2,
            )

            barcode_value = (
                "998877665544"
            )
            future_barcode_value = (
                "887766554433"
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
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
                    "- INTERVAL '1 minute', NULL, "
                    "true, 1, "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'), "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))"
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
            await app.execute(
                text(
                    "INSERT INTO product_barcodes "
                    "(company_id, product_variant_id, "
                    "uom_id, barcode, barcode_type, "
                    "is_primary, valid_from, valid_to, "
                    "is_active, version, created_at, updated_at) "
                    "VALUES "
                    "(:company_id, :variant_id, :uom_id, "
                    ":barcode, 'INTERNAL', false, "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
                    "+ INTERVAL '1 day', NULL, "
                    "true, 1, "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'), "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))"
                ),
                {
                    "company_id": company_id,
                    "variant_id": ids[
                        "variant_id"
                    ],
                    "uom_id": ids[
                        "each_uom_id"
                    ],
                    "barcode": future_barcode_value,
                },
            )


            beta_future_barcode = (
                "776655443322"
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
                    ":barcode, 'INTERNAL', false, "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
                    "+ INTERVAL '1 day', NULL, "
                    "true, 1, "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'), "
                    "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))"
                ),
                {
                    "company_id": company_id,
                    "variant_id": beta_variant_id,
                    "uom_id": ids[
                        "each_uom_id"
                    ],
                    "barcode":
                        beta_future_barcode,
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
                "product search finds currently effective active barcode",
                ids["variant_id"]
                in await search_ids(
                    barcode_value
                ),
            )
            record(
                "product search ignores future-dated barcode before validity begins",
                await search_ids(
                    future_barcode_value
                )
                == [],
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
            record(
                "product search never leaks a foreign-tenant identity",
                await search_ids(
                    "P2 Foreign Item"
                )
                == [],
            )


            async def product_page(
                *,
                actor: Driver = catalog_actor,
                **overrides,
            ) -> dict:
                params = {
                    "search": None,
                    "cursor": None,
                    "limit": 50,
                }
                params.update(overrides)
                return await list_simple_products(
                    db=app,
                    actor=actor,
                    **params,
                )

            def page_ids(page: dict) -> list[int]:
                items = page.get("items")
                if not isinstance(items, list):
                    return []
                return [
                    int(item["id"])
                    for item in items
                    if isinstance(item, dict)
                    and isinstance(
                        item.get("id"),
                        int,
                    )
                ]

            def page_names(page: dict) -> list[str]:
                items = page.get("items")
                if not isinstance(items, list):
                    return []
                return [
                    str(item["name"])
                    for item in items
                    if isinstance(item, dict)
                    and isinstance(
                        item.get("name"),
                        str,
                    )
                ]

            record(
                "family filter runs server-side before pagination",
                page_ids(
                    await product_page(
                        family_id=alpha_family_id,
                        limit=1,
                    )
                )
                == [alpha_variant_id],
            )
            record(
                "lifecycle filter runs before pagination",
                page_ids(
                    await product_page(
                        search="P4 Filter",
                        lifecycle="RETIRING",
                        limit=1,
                    )
                )
                == [gamma_variant_id],
            )
            record(
                "tracking type derives LOT_EXPIRY from authoritative modes",
                page_ids(
                    await product_page(
                        search="P4 Filter",
                        tracking_type=
                            "LOT_EXPIRY",
                    )
                )
                == [gamma_variant_id],
            )
            record(
                "tracking type NONE is deterministic",
                page_ids(
                    await product_page(
                        search="P4 Filter",
                        tracking_type="NONE",
                    )
                )
                == [delta_variant_id],
            )
            record(
                "lot-tracked filter uses non-NONE lot authority",
                page_ids(
                    await product_page(
                        search="Alpha P4 Filter",
                        lot_tracked=True,
                        expiry_tracked=False,
                    )
                )
                == [alpha_variant_id],
            )
            record(
                "expiry-tracked filter uses non-NONE expiry authority",
                page_ids(
                    await product_page(
                        search="Beta P4 Filter",
                        lot_tracked=False,
                        expiry_tracked=True,
                    )
                )
                == [beta_variant_id],
            )
            record(
                "simple-compatible filter is evaluated before pagination",
                page_ids(
                    await product_page(
                        search="P4 Filter",
                        simple_compatible=False,
                        limit=1,
                    )
                )
                == [gamma_variant_id],
            )
            record(
                "future-only barcode counts as missing",
                page_ids(
                    await product_page(
                        search="Beta P4 Filter",
                        has_barcode=False,
                    )
                )
                == [beta_variant_id]
                and page_ids(
                    await product_page(
                        search="Beta P4 Filter",
                        has_barcode=True,
                    )
                )
                == [],
            )
            record(
                "current effective barcode satisfies has-barcode",
                ids["variant_id"]
                in page_ids(
                    await product_page(
                        search="Catalog Item",
                        has_barcode=True,
                    )
                ),
            )
            record(
                "price filter uses current resolved simple price",
                page_ids(
                    await product_page(
                        actor=pricing_actor,
                        search="Catalog Item",
                        has_price=True,
                    )
                )
                == [ids["variant_id"]]
                and page_ids(
                    await product_page(
                        actor=pricing_actor,
                        search="Catalog Item",
                        has_price=False,
                    )
                )
                == [],
            )
            record(
                "missing-price filter finds unpriced simple product",
                page_ids(
                    await product_page(
                        actor=pricing_actor,
                        search="Alpha P4 Filter",
                        has_price=False,
                    )
                )
                == [alpha_variant_id],
            )
            price_filter_forbidden = False
            try:
                await product_page(
                    search="Catalog Item",
                    has_price=True,
                )
            except HTTPException as exc:
                detail = exc.detail
                price_filter_forbidden = (
                    exc.status_code == 403
                    and isinstance(
                        detail,
                        dict,
                    )
                    and detail.get("code")
                    == "SIMPLE_PRODUCT_PRICE_FILTER_FORBIDDEN"
                )
            record(
                "price filter is forbidden without pricing.view",
                price_filter_forbidden,
            )
            record(
                "search and family filter compose before pagination",
                page_ids(
                    await product_page(
                        search="Alpha",
                        family_id=beta_family_id,
                        limit=1,
                    )
                )
                == [],
            )

            expected_asc = [
                "Alpha P4 Filter Item",
                "Beta P4 Filter Item",
                "Delta P4 Filter Item",
                "Gamma P4 Filter Item",
            ]
            first_sorted = await product_page(
                search="P4 Filter",
                sort_by="name",
                sort_dir="asc",
                limit=2,
            )
            sorted_cursor = first_sorted.get(
                "next_cursor"
            )
            second_sorted = await product_page(
                search="P4 Filter",
                cursor=(
                    sorted_cursor
                    if isinstance(
                        sorted_cursor,
                        str,
                    )
                    else None
                ),
                sort_by="name",
                sort_dir="asc",
                limit=2,
            )
            record(
                "name sort uses bounded composite keyset continuation",
                page_names(first_sorted)
                + page_names(second_sorted)
                == expected_asc
                and isinstance(
                    sorted_cursor,
                    str,
                ),
            )
            first_again = await product_page(
                search="P4 Filter",
                sort_by="name",
                sort_dir="asc",
                limit=2,
            )
            record(
                "first page can be reconstructed for frontend previous history",
                page_names(first_again)
                == page_names(first_sorted),
            )

            changed_sort_rejected = False
            if isinstance(
                sorted_cursor,
                str,
            ):
                try:
                    await product_page(
                        search="P4 Filter",
                        cursor=sorted_cursor,
                        sort_by="name",
                        sort_dir="desc",
                        limit=2,
                    )
                except HTTPException as exc:
                    detail = exc.detail
                    changed_sort_rejected = (
                        exc.status_code == 400
                        and isinstance(
                            detail,
                            dict,
                        )
                        and detail.get("code")
                        == "INVALID_CURSOR"
                    )
            record(
                "cursor rejects changed sort scope",
                changed_sort_rejected,
            )

            changed_filter_rejected = False
            if isinstance(
                sorted_cursor,
                str,
            ):
                try:
                    await product_page(
                        search="P4 Filter",
                        cursor=sorted_cursor,
                        family_id=alpha_family_id,
                        sort_by="name",
                        sort_dir="asc",
                        limit=2,
                    )
                except HTTPException as exc:
                    detail = exc.detail
                    changed_filter_rejected = (
                        exc.status_code == 400
                        and isinstance(
                            detail,
                            dict,
                        )
                        and detail.get("code")
                        == "INVALID_CURSOR"
                    )
            record(
                "cursor rejects changed filter scope",
                changed_filter_rejected,
            )

            record(
                "name descending sort is deterministic",
                page_names(
                    await product_page(
                        search="P4 Filter",
                        sort_by="name",
                        sort_dir="desc",
                    )
                )
                == list(
                    reversed(expected_asc)
                ),
            )
            record(
                "family sort is deterministic",
                page_ids(
                    await product_page(
                        search="P4 Filter",
                        sort_by="family",
                        sort_dir="asc",
                    )
                )
                == [
                    alpha_variant_id,
                    beta_variant_id,
                    delta_variant_id,
                    gamma_variant_id,
                ],
            )
            record(
                "SKU sort is deterministic",
                page_ids(
                    await product_page(
                        search="P4 Filter",
                        sort_by="sku",
                        sort_dir="asc",
                    )
                )
                == [
                    alpha_variant_id,
                    beta_variant_id,
                    delta_variant_id,
                    gamma_variant_id,
                ],
            )
            lifecycle_sorted = page_ids(
                await product_page(
                    search="P4 Filter",
                    sort_by="lifecycle",
                    sort_dir="asc",
                )
            )
            record(
                "lifecycle sort is deterministic with id tie-breaker",
                len(lifecycle_sorted) == 4
                and lifecycle_sorted[-1]
                == gamma_variant_id
                and set(
                    lifecycle_sorted[:-1]
                )
                == {
                    alpha_variant_id,
                    beta_variant_id,
                    delta_variant_id,
                },
            )
            record(
                "P4.2 filters stay tenant-scoped",
                page_ids(
                    await product_page(
                        search=
                            "P2 Foreign Item",
                        simple_compatible=False,
                    )
                )
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
            record(
                "family API does not expose internal database sort keys",
                isinstance(
                    first_items,
                    list,
                )
                and all(
                    isinstance(item, dict)
                    and "_sort_name"
                    not in item
                    for item in first_items
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

            foreign_family_page = (
                await list_families_endpoint(
                    search="P2 Foreign Family",
                    cursor=None,
                    limit=2,
                    db=app,
                    actor=catalog_actor,
                )
            )
            record(
                "family search never leaks a foreign-tenant family",
                foreign_family_page.get(
                    "items"
                )
                == [],
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
