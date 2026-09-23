from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=False)

from api.simple_products import (
    _cursor,
    _next_cursor,
    list_simple_products,
)
from models import Driver


MIGRATION_URL = os.environ["DATABASE_URL_MIGRATION"]
APP_URL = os.environ["DATABASE_URL"]

engine_su = create_async_engine(
    MIGRATION_URL,
    pool_size=2,
    max_overflow=0,
)
engine_app = create_async_engine(
    APP_URL,
    pool_size=2,
    max_overflow=0,
)
SessionSU = async_sessionmaker(
    bind=engine_su,
    expire_on_commit=False,
    autobegin=False,
)
SessionApp = async_sessionmaker(
    bind=engine_app,
    expire_on_commit=False,
    autobegin=False,
)

RESULTS: list[tuple[str, bool, str]] = []


def record(
    name: str,
    ok: bool,
    detail: str = "",
) -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def set_tenant(
    session,
    company_id: int,
) -> None:
    await session.execute(
        text(
            "SELECT set_config("
            "'app.current_tenant', :tenant, true)"
        ),
        {"tenant": str(company_id)},
    )


def invalid_cursor(
    token: str,
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> bool:
    try:
        _cursor(
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
            and detail.get("code") == "INVALID_CURSOR"
        )
    return False


async def seed() -> dict[str, int]:
    async with SessionSU() as su:
        await su.begin()

        permission_meta: dict[str, tuple[int, bool]] = {}
        for code in ("catalog.read", "pricing.view"):
            inserted = (
                await su.execute(
                    text(
                        "INSERT INTO permissions (code) "
                        "VALUES (:code) "
                        "ON CONFLICT (code) DO NOTHING "
                        "RETURNING id"
                    ),
                    {"code": code},
                )
            ).scalar_one_or_none()
            created = inserted is not None
            permission_id = (
                int(inserted)
                if inserted is not None
                else int(
                    (
                        await su.execute(
                            text(
                                "SELECT id FROM permissions "
                                "WHERE code = :code"
                            ),
                            {"code": code},
                        )
                    ).scalar_one()
                )
            )
            permission_meta[code] = (
                permission_id,
                created,
            )

        each_uom = (
            await su.execute(
                text(
                    "SELECT id FROM uom "
                    "WHERE code = 'EACH'"
                )
            )
        ).scalar_one_or_none()
        if each_uom is None:
            raise RuntimeError(
                "EACH UOM is missing"
            )

        async def company(
            name: str,
        ) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            "INSERT INTO companies "
                            "(name, company_code, is_active, "
                            "subscription_status, currency_code, "
                            "timezone, created_at) "
                            "VALUES "
                            "(:name, :code, true, 'active', "
                            "'JOD', 'Asia/Amman', NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "name": name,
                            "code": (
                                "P2READ-"
                                + uuid4().hex[:10]
                            ),
                        },
                    )
                ).scalar_one()
            )

        async def driver(
            company_id: int,
            name: str,
        ) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            "INSERT INTO drivers "
                            "(company_id, username, password_hash, "
                            "full_name, is_active, is_admin, "
                            "created_at) "
                            "VALUES "
                            "(:company_id, :username, 'x', "
                            ":name, true, false, NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "username": (
                                "p2_"
                                + uuid4().hex[:10]
                            ),
                            "name": name,
                        },
                    )
                ).scalar_one()
            )

        async def role_with_permissions(
            company_id: int,
            actor_id: int,
            name: str,
            codes: tuple[str, ...],
        ) -> None:
            role_id = int(
                (
                    await su.execute(
                        text(
                            "INSERT INTO roles "
                            "(company_id, name, is_system_role) "
                            "VALUES (:company_id, :name, false) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "name": name,
                        },
                    )
                ).scalar_one()
            )
            for code in codes:
                await su.execute(
                    text(
                        "INSERT INTO role_permissions "
                        "(company_id, role_id, permission_id) "
                        "VALUES "
                        "(:company_id, :role_id, :permission_id)"
                    ),
                    {
                        "company_id": company_id,
                        "role_id": role_id,
                        "permission_id": (
                            permission_meta[code][0]
                        ),
                    },
                )
            await su.execute(
                text(
                    "INSERT INTO user_roles "
                    "(company_id, driver_id, role_id) "
                    "VALUES "
                    "(:company_id, :driver_id, :role_id)"
                ),
                {
                    "company_id": company_id,
                    "driver_id": actor_id,
                    "role_id": role_id,
                },
            )

        async def product_variant(
            company_id: int,
            name: str,
        ) -> int:
            product_id = int(
                (
                    await su.execute(
                        text(
                            "INSERT INTO products "
                            "(company_id, code, name, version, "
                            "created_at, updated_at) "
                            "VALUES "
                            "(:company_id, :code, :name, 1, "
                            "NOW(), NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "code": (
                                "P2-P-"
                                + uuid4().hex[:8]
                            ),
                            "name": name + " Family",
                        },
                    )
                ).scalar_one()
            )
            return int(
                (
                    await su.execute(
                        text(
                            "INSERT INTO product_variants "
                            "(company_id, product_id, base_uom_id, "
                            "name, sku, quantity_scale, quantity_step, "
                            "lot_control_mode, expiry_control_mode, "
                            "lifecycle_status, operational_hold, "
                            "lifecycle_revision, version, published_at, "
                            "packs_per_carton, package_uses_base_barcode, "
                            "default_max_samples_per_day, "
                            "created_at, updated_at) "
                            "VALUES "
                            "(:company_id, :product_id, :uom_id, "
                            ":name, :sku, 0, 1, "
                            "'OPTIONAL', 'NONE', "
                            "'ACTIVE', 'NONE', 1, 1, NOW(), "
                            "1, false, 0, NOW(), NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "product_id": product_id,
                            "uom_id": int(each_uom),
                            "name": name,
                            "sku": (
                                "P2-SKU-"
                                + uuid4().hex[:8]
                            ),
                        },
                    )
                ).scalar_one()
            )

        company_id = await company(
            "P2 Read Contract Gate A"
        )
        foreign_company_id = await company(
            "P2 Read Contract Gate B"
        )
        catalog_driver_id = await driver(
            company_id,
            "P2 Catalog Reader",
        )
        pricing_driver_id = await driver(
            company_id,
            "P2 Pricing Reader",
        )

        await role_with_permissions(
            company_id,
            catalog_driver_id,
            "P2 Catalog Reader",
            ("catalog.read",),
        )
        await role_with_permissions(
            company_id,
            pricing_driver_id,
            "P2 Pricing Reader",
            ("catalog.read", "pricing.view"),
        )

        variant_id = await product_variant(
            company_id,
            "P2 Catalog Item",
        )
        foreign_variant_id = await product_variant(
            foreign_company_id,
            "P2 Foreign Item",
        )

        price_book_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO price_books "
                        "(company_id, code, name, currency_code, "
                        "status, applicability_metadata, version, "
                        "created_by, created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :code, 'P2 Prices', 'JOD', "
                        "'ACTIVE', '{}'::jsonb, 1, :actor_id, "
                        "NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "code": (
                            "P2-BOOK-"
                            + uuid4().hex[:8]
                        ),
                        "actor_id": pricing_driver_id,
                    },
                )
            ).scalar_one()
        )
        publication_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO price_publications "
                        "(company_id, price_book_id, revision, status, "
                        "effective_at, created_by, approved_by, "
                        "approved_at, published_at, request_id, "
                        "version, created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :book_id, 1, 'PUBLISHED', "
                        "NOW() - INTERVAL '1 day', :actor_id, "
                        ":actor_id, NOW() - INTERVAL '1 day', "
                        "NOW() - INTERVAL '1 day', :request_id, "
                        "1, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "book_id": price_book_id,
                        "actor_id": pricing_driver_id,
                        "request_id": uuid4(),
                    },
                )
            ).scalar_one()
        )
        await su.execute(
            text(
                "INSERT INTO price_book_assignments "
                "(company_id, price_book_id, scope_type, scope_id, "
                "allow_offers, priority, effectivity, revision, "
                "version, created_by, created_at, updated_at) "
                "VALUES "
                "(:company_id, :book_id, 'COMPANY_DEFAULT', NULL, "
                "true, 0, "
                "tstzrange(NOW() - INTERVAL '1 day', NULL, '[)'), "
                "1, 1, :actor_id, NOW(), NOW())"
            ),
            {
                "company_id": company_id,
                "book_id": price_book_id,
                "actor_id": pricing_driver_id,
            },
        )
        await su.execute(
            text(
                "INSERT INTO price_book_entries "
                "(company_id, price_book_id, publication_id, "
                "product_variant_id, uom_id, amount, effectivity, "
                "priority, is_published, metadata, version, "
                "created_at, updated_at) "
                "VALUES "
                "(:company_id, :book_id, :publication_id, "
                ":variant_id, :uom_id, 12.345000, "
                "tstzrange(NOW() - INTERVAL '1 day', NULL, '[)'), "
                "0, true, '{}'::jsonb, 1, NOW(), NOW())"
            ),
            {
                "company_id": company_id,
                "book_id": price_book_id,
                "publication_id": publication_id,
                "variant_id": variant_id,
                "uom_id": int(each_uom),
            },
        )

        await su.commit()

    return {
        "company_id": company_id,
        "foreign_company_id": foreign_company_id,
        "catalog_driver_id": catalog_driver_id,
        "pricing_driver_id": pricing_driver_id,
        "variant_id": variant_id,
        "foreign_variant_id": foreign_variant_id,
        "catalog_permission_id": (
            permission_meta["catalog.read"][0]
        ),
        "catalog_permission_created": int(
            permission_meta["catalog.read"][1]
        ),
        "pricing_permission_id": (
            permission_meta["pricing.view"][0]
        ),
        "pricing_permission_created": int(
            permission_meta["pricing.view"][1]
        ),
    }


async def cleanup(
    company_ids: tuple[int, ...],
    *,
    permission_meta: tuple[
        tuple[int | None, bool],
        ...,
    ],
) -> tuple[bool, str]:
    try:
        async with SessionSU() as su:
            await su.begin()
            for company_id in company_ids:
                for table_name in (
                    "price_book_entries",
                    "price_book_assignments",
                    "price_publications",
                    "price_books",
                ):
                    await su.execute(
                        text(
                            f"DELETE FROM {table_name} "
                            "WHERE company_id = :company_id"
                        ),
                        {"company_id": int(company_id)},
                    )
                await su.execute(
                    text(
                        "DELETE FROM companies "
                        "WHERE id = :company_id"
                    ),
                    {"company_id": int(company_id)},
                )

            for permission_id, created in permission_meta:
                if (
                    created
                    and permission_id is not None
                ):
                    await su.execute(
                        text(
                            "DELETE FROM permissions AS p "
                            "WHERE p.id = :permission_id "
                            "AND NOT EXISTS ("
                            "SELECT 1 "
                            "FROM role_permissions AS rp "
                            "WHERE rp.permission_id = p.id"
                            ")"
                        ),
                        {
                            "permission_id": int(
                                permission_id
                            )
                        },
                    )
            await su.commit()
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def main() -> None:
    ids: dict[str, int] = {}

    try:
        ids = await seed()
        company_id = ids["company_id"]
        variant_id = ids["variant_id"]

        token = _next_cursor(
            variant_id,
            company_id=company_id,
            search="  Chips  ",
            limit=50,
        )
        record(
            "signed cursor round-trips only in its exact normalized scope",
            _cursor(
                token,
                company_id=company_id,
                search="chips",
                limit=50,
            )
            == variant_id,
        )
        record(
            "cursor rejects reuse under a different search",
            invalid_cursor(
                token,
                company_id=company_id,
                search="other",
                limit=50,
            ),
        )
        record(
            "cursor rejects reuse under a different company",
            invalid_cursor(
                token,
                company_id=ids["foreign_company_id"],
                search="chips",
                limit=50,
            ),
        )
        record(
            "cursor rejects reuse under a different page size",
            invalid_cursor(
                token,
                company_id=company_id,
                search="chips",
                limit=100,
            ),
        )

        tampered = (
            token[:-1]
            + ("A" if token[-1] != "A" else "B")
        )
        record(
            "tampered cursor fails closed",
            invalid_cursor(
                tampered,
                company_id=company_id,
                search="chips",
                limit=50,
            ),
        )

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, company_id)
            catalog_actor = await app.get(
                Driver,
                ids["catalog_driver_id"],
            )
            pricing_actor = await app.get(
                Driver,
                ids["pricing_driver_id"],
            )
            if (
                catalog_actor is None
                or pricing_actor is None
            ):
                raise RuntimeError(
                    "seeded P2 actors are not visible"
                )

            catalog_page = await list_simple_products(
                search=None,
                cursor=None,
                limit=50,
                db=app,
                actor=catalog_actor,
            )
            pricing_page = await list_simple_products(
                search=None,
                cursor=None,
                limit=50,
                db=app,
                actor=pricing_actor,
            )
            await app.rollback()

        catalog_items = catalog_page.get("items")
        pricing_items = pricing_page.get("items")
        catalog_row = (
            catalog_items[0]
            if isinstance(catalog_items, list)
            and len(catalog_items) == 1
            else {}
        )
        pricing_row = (
            pricing_items[0]
            if isinstance(pricing_items, list)
            and len(pricing_items) == 1
            else {}
        )

        record(
            "catalog-only user can read product identity without pricing.view",
            catalog_page.get("pricing_visible") is False
            and isinstance(catalog_row, dict)
            and catalog_row.get("id") == variant_id,
        )
        record(
            "catalog-only read exposes SKU tracking and lifecycle identity",
            isinstance(catalog_row, dict)
            and isinstance(catalog_row.get("sku"), str)
            and catalog_row.get("lot_control_mode") == "OPTIONAL"
            and catalog_row.get("expiry_control_mode") == "NONE"
            and catalog_row.get("lifecycle_status") == "ACTIVE",
        )
        record(
            "pricing-authorized reader receives the seeded real price",
            pricing_page.get("pricing_visible") is True
            and isinstance(pricing_row, dict)
            and pricing_row.get("id") == variant_id
            and pricing_row.get("unit_price")
            == "12.345000",
            (
                "visible="
                f"{pricing_page.get('pricing_visible')} "
                "unit_price="
                f"{pricing_row.get('unit_price') if isinstance(pricing_row, dict) else None}"
            ),
        )
        record(
            "catalog-only read hides an existing real price",
            isinstance(catalog_row, dict)
            and catalog_row.get("package_price") is None
            and catalog_row.get("unit_price") is None,
        )
        record(
            "catalog list request excludes foreign-tenant products",
            isinstance(catalog_items, list)
            and len(catalog_items) == 1
            and all(
                isinstance(item, dict)
                and item.get("id")
                != ids["foreign_variant_id"]
                for item in catalog_items
            ),
        )

    except Exception as exc:
        record(
            "P2 runtime gate completed without unexpected exception",
            False,
            repr(exc),
        )
    finally:
        company_ids = tuple(
            int(value)
            for value in (
                ids.get("company_id"),
                ids.get("foreign_company_id"),
            )
            if value is not None
        )
        cleanup_ok, cleanup_detail = await cleanup(
            company_ids,
            permission_meta=(
                (
                    ids.get("catalog_permission_id"),
                    bool(
                        ids.get(
                            "catalog_permission_created",
                            0,
                        )
                    ),
                ),
                (
                    ids.get("pricing_permission_id"),
                    bool(
                        ids.get(
                            "pricing_permission_created",
                            0,
                        )
                    ),
                ),
            ),
        )
        record(
            "P2 runtime gate removes all seeded tenant data",
            cleanup_ok,
            cleanup_detail,
        )
        await engine_app.dispose()
        await engine_su.dispose()

    failures = [
        name
        for name, ok, _ in RESULTS
        if not ok
    ]
    print()
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")

    if failures:
        print(
            "PRODUCTS_READ_CONTRACT_P2_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        "PRODUCTS_READ_CONTRACT_P2_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
