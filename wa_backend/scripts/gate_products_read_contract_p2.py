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

        catalog_permission = (
            await su.execute(
                text(
                    "SELECT id FROM permissions "
                    "WHERE code = 'catalog.read'"
                )
            )
        ).scalar_one_or_none()
        if catalog_permission is None:
            raise RuntimeError(
                "catalog.read permission is missing"
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

        company_id = int(
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
                        "name": "P2 Read Contract Gate",
                        "code": "P2READ-" + uuid4().hex[:10],
                    },
                )
            ).scalar_one()
        )

        driver_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO drivers "
                        "(company_id, username, password_hash, "
                        "full_name, is_active, is_admin, "
                        "created_at) "
                        "VALUES "
                        "(:company_id, :username, 'x', "
                        "'P2 Catalog Reader', true, false, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "username": "p2_" + uuid4().hex[:10],
                    },
                )
            ).scalar_one()
        )

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
                        "name": "P2 Catalog Reader",
                    },
                )
            ).scalar_one()
        )

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
                "permission_id": int(catalog_permission),
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
                "driver_id": driver_id,
                "role_id": role_id,
            },
        )

        product_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO products "
                        "(company_id, code, name, version, "
                        "created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :code, :name, 1, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "code": "P2-P-" + uuid4().hex[:8],
                        "name": "P2 Family",
                    },
                )
            ).scalar_one()
        )

        variant_id = int(
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
                        "name": "P2 Catalog Item",
                        "sku": "P2-SKU-" + uuid4().hex[:8],
                    },
                )
            ).scalar_one()
        )

        await su.commit()

    return {
        "company_id": company_id,
        "driver_id": driver_id,
        "variant_id": variant_id,
    }


async def cleanup(
    company_id: int | None,
) -> tuple[bool, str]:
    if company_id is None:
        return True, ""
    try:
        async with SessionSU() as su:
            await su.begin()
            await su.execute(
                text(
                    "DELETE FROM companies "
                    "WHERE id = :company_id"
                ),
                {"company_id": int(company_id)},
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
                company_id=company_id + 1,
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
            actor = await app.get(
                Driver,
                ids["driver_id"],
            )
            if actor is None:
                raise RuntimeError(
                    "seeded catalog reader is not visible"
                )

            page = await list_simple_products(
                search=None,
                cursor=None,
                limit=50,
                db=app,
                actor=actor,
            )
            await app.rollback()

        items = page.get("items")
        row = (
            items[0]
            if isinstance(items, list)
            and len(items) == 1
            else {}
        )
        record(
            "catalog-only user can read product identity without pricing.view",
            page.get("pricing_visible") is False
            and isinstance(row, dict)
            and row.get("id") == variant_id,
        )
        record(
            "catalog-only read exposes SKU tracking and lifecycle identity",
            isinstance(row, dict)
            and isinstance(row.get("sku"), str)
            and row.get("lot_control_mode") == "OPTIONAL"
            and row.get("expiry_control_mode") == "NONE"
            and row.get("lifecycle_status") == "ACTIVE",
        )
        record(
            "catalog-only read cannot receive hidden pricing",
            isinstance(row, dict)
            and row.get("package_price") is None
            and row.get("unit_price") is None,
        )

    except Exception as exc:
        record(
            "P2 runtime gate completed without unexpected exception",
            False,
            repr(exc),
        )
    finally:
        cleanup_ok, cleanup_detail = await cleanup(
            ids.get("company_id")
        )
        record(
            "P2 runtime gate removes seeded tenant",
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
