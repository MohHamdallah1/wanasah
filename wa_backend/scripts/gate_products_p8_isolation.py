from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

import gate_products_read_contract_p2 as p2_gate
from api import catalog
from api.simple_products import (
    SimpleProductCreate,
    create_simple_product,
    list_simple_products,
)
from models import Driver
from product_import_worker import (
    _close as close_worker_tenant_session,
    _tenant_session as worker_tenant_session,
)


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
        f"[{'PASS' if ok else 'FAIL'}] "
        f"{name}"
        + (
            f" — {detail}"
            if detail
            else ""
        )
    )


def error_code(
    exc: HTTPException,
) -> str | None:
    detail = exc.detail
    if isinstance(detail, dict):
        value = detail.get("code")
        if isinstance(value, str):
            return value
    return None


async def ensure_permission(
    su,
    code: str,
) -> tuple[int, bool]:
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
    if inserted is not None:
        return int(inserted), True

    existing = (
        await su.execute(
            text(
                "SELECT id FROM permissions "
                "WHERE code = :code"
            ),
            {"code": code},
        )
    ).scalar_one()
    return int(existing), False


async def seed_isolation_fixture(
    ids: dict[str, int],
) -> dict[str, int | UUID | bool]:
    company_id = int(
        ids["company_id"]
    )
    foreign_company_id = int(
        ids["foreign_company_id"]
    )
    foreign_variant_id = int(
        ids["foreign_variant_id"]
    )
    each_uom_id = int(
        ids["each_uom_id"]
    )

    async with p2_gate.SessionSU() as su:
        await su.begin()

        manage_permission_id, manage_created = (
            await ensure_permission(
                su,
                "catalog.manage",
            )
        )

        carton_uom_id = int(
            (
                await su.execute(
                    text(
                        "SELECT id FROM uom "
                        "WHERE code = 'CARTON'"
                    )
                )
            ).scalar_one()
        )

        foreign_product_id = int(
            (
                await su.execute(
                    text(
                        "SELECT product_id "
                        "FROM product_variants "
                        "WHERE company_id = :company_id "
                        "AND id = :variant_id"
                    ),
                    {
                        "company_id":
                            foreign_company_id,
                        "variant_id":
                            foreign_variant_id,
                    },
                )
            ).scalar_one()
        )

        actor_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO drivers "
                        "(company_id, username, password_hash, "
                        "full_name, is_active, is_admin, "
                        "created_at) "
                        "VALUES "
                        "(:company_id, :username, 'x', "
                        "'P8 Isolation Actor', true, false, "
                        "NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "username": (
                            "p8_iso_"
                            + uuid4().hex[:10]
                        ),
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
                        "VALUES "
                        "(:company_id, :name, false) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "name": (
                            "P8 Isolation "
                            + uuid4().hex[:8]
                        ),
                    },
                )
            ).scalar_one()
        )

        for permission_id in (
            int(
                ids[
                    "catalog_permission_id"
                ]
            ),
            manage_permission_id,
        ):
            await su.execute(
                text(
                    "INSERT INTO role_permissions "
                    "(company_id, role_id, permission_id) "
                    "VALUES "
                    "(:company_id, :role_id, "
                    ":permission_id)"
                ),
                {
                    "company_id": company_id,
                    "role_id": role_id,
                    "permission_id":
                        permission_id,
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

        foreign_barcode_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO product_barcodes "
                        "(company_id, product_variant_id, "
                        "uom_id, barcode, barcode_type, "
                        "is_primary, valid_from, valid_to, "
                        "is_active, version, created_at, "
                        "updated_at) "
                        "VALUES "
                        "(:company_id, :variant_id, "
                        ":uom_id, :barcode, 'INTERNAL', "
                        "true, NOW() - INTERVAL '1 day', "
                        "NULL, true, 1, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id":
                            foreign_company_id,
                        "variant_id":
                            foreign_variant_id,
                        "uom_id":
                            each_uom_id,
                        "barcode": (
                            "P8-FOREIGN-"
                            + uuid4().hex[:16]
                        ),
                    },
                )
            ).scalar_one()
        )

        foreign_conversion_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO product_uom_conversions "
                        "(company_id, product_variant_id, "
                        "from_uom_id, to_uom_id, "
                        "numerator, denominator, "
                        "quantity_scale, version, "
                        "created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :variant_id, "
                        ":from_uom_id, :to_uom_id, "
                        "10, 1, 0, 1, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id":
                            foreign_company_id,
                        "variant_id":
                            foreign_variant_id,
                        "from_uom_id":
                            carton_uom_id,
                        "to_uom_id":
                            each_uom_id,
                    },
                )
            ).scalar_one()
        )

        foreign_import_driver = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO drivers "
                        "(company_id, username, password_hash, "
                        "full_name, is_active, is_admin, "
                        "created_at) "
                        "VALUES "
                        "(:company_id, :username, 'x', "
                        "'P8 Foreign Import Actor', "
                        "true, false, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id":
                            foreign_company_id,
                        "username": (
                            "p8_iso_foreign_"
                            + uuid4().hex[:8]
                        ),
                    },
                )
            ).scalar_one()
        )

        own_job_id = uuid4()
        foreign_job_id = uuid4()

        for (
            import_company_id,
            created_by,
            job_id,
            request_id,
            marker,
        ) in (
            (
                company_id,
                actor_id,
                own_job_id,
                uuid4(),
                "OWN",
            ),
            (
                foreign_company_id,
                foreign_import_driver,
                foreign_job_id,
                uuid4(),
                "FOREIGN",
            ),
        ):
            await su.execute(
                text(
                    "INSERT INTO product_import_jobs "
                    "(id, company_id, request_id, "
                    "created_by, file_name, content_type, "
                    "source_payload, source_sha256, file_size, "
                    "status, detected_headers, "
                    "suggested_mapping, column_mapping, "
                    "default_lot_control_mode, "
                    "default_expiry_control_mode, "
                    "error_summary, total_rows, "
                    "processed_rows, valid_rows, "
                    "failed_rows, version, "
                    "created_at, updated_at) "
                    "VALUES "
                    "(:job_id, :company_id, :request_id, "
                    ":created_by, :file_name, 'text/csv', "
                    "NULL, :sha, 1, 'QUEUED', "
                    "'[]'::jsonb, '{}'::jsonb, "
                    "'{}'::jsonb, 'NONE', 'NONE', "
                    "'{}'::jsonb, 1, 0, 0, 0, 1, "
                    "NOW(), NOW())"
                ),
                {
                    "job_id": job_id,
                    "company_id":
                        import_company_id,
                    "request_id": request_id,
                    "created_by": created_by,
                    "file_name":
                        f"p8-{marker.lower()}.csv",
                    "sha": (
                        marker.lower()
                        .ljust(64, "0")[:64]
                    ),
                },
            )
            await su.execute(
                text(
                    "INSERT INTO product_import_rows "
                    "(company_id, job_id, row_number, "
                    "raw_data, normalized_data, "
                    "status, version, created_at, "
                    "updated_at) "
                    "VALUES "
                    "(:company_id, :job_id, 2, "
                    "CAST(:raw_data AS jsonb), '{}'::jsonb, "
                    "'STAGED', 1, NOW(), NOW())"
                ),
                {
                    "company_id":
                        import_company_id,
                    "job_id": job_id,
                    "raw_data": (
                        '{"marker":"'
                        + marker
                        + '"}'
                    ),
                },
            )

        await su.commit()

    return {
        "actor_id": actor_id,
        "foreign_product_id":
            foreign_product_id,
        "foreign_variant_id":
            foreign_variant_id,
        "foreign_barcode_id":
            foreign_barcode_id,
        "foreign_conversion_id":
            foreign_conversion_id,
        "carton_uom_id":
            carton_uom_id,
        "own_job_id": own_job_id,
        "foreign_job_id":
            foreign_job_id,
        "manage_permission_id":
            manage_permission_id,
        "manage_permission_created":
            manage_created,
    }


async def api_actor(
    company_id: int,
    actor_id: int,
):
    app = p2_gate.SessionApp()
    await app.begin()
    await p2_gate.set_tenant(
        app,
        company_id,
    )
    actor = await app.get(
        Driver,
        actor_id,
    )
    if actor is None:
        await app.close()
        raise RuntimeError(
            "P8 isolation actor is not visible."
        )
    return app, actor


async def expect_http_code(
    name: str,
    expected_status: int,
    expected_code: str,
    coroutine_factory,
) -> None:
    try:
        await coroutine_factory()
    except HTTPException as exc:
        record(
            name,
            exc.status_code
            == expected_status
            and error_code(exc)
            == expected_code,
            (
                f"status={exc.status_code} "
                f"code={error_code(exc)}"
            ),
        )
        return
    record(
        name,
        False,
        "operation unexpectedly succeeded",
    )


async def verify_direct_product_family_isolation(
    *,
    company_id: int,
    actor_id: int,
    foreign_product_id: int,
    each_uom_id: int,
) -> None:
    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        payload = catalog.VariantCreate(
            request_id=uuid4(),
            product_id=foreign_product_id,
            sku=(
                "P8-ISO-SKU-"
                + uuid4().hex[:10]
            ),
            gtin=None,
            name="P8 Cross Tenant Variant",
            base_uom_id=each_uom_id,
            quantity_scale=0,
            quantity_step=Decimal("1"),
            lot_control_mode="NONE",
            expiry_control_mode="NONE",
        )
        await expect_http_code(
            "cross-company Product ID lookup fails closed",
            404,
            "PRODUCT_NOT_FOUND",
            lambda: catalog.create_variant(
                payload=payload,
                db=app,
                actor=actor,
            ),
        )
    finally:
        await app.close()

    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        payload = SimpleProductCreate(
            request_id=uuid4(),
            name="P8 Cross Tenant Family Probe",
            family_id=foreign_product_id,
            family_name=None,
            package_uom_code=None,
            units_per_package=1,
            package_price=None,
            unit_price=Decimal("1.000000"),
            unit_barcode=None,
            package_barcode=None,
            lot_control_mode="NONE",
            expiry_control_mode="NONE",
        )
        await expect_http_code(
            "cross-company Family ID fails closed",
            404,
            "SIMPLE_PRODUCT_FAMILY_NOT_FOUND",
            lambda: create_simple_product(
                payload=payload,
                db=app,
                actor=actor,
            ),
        )
    finally:
        await app.close()


async def verify_barcode_uom_isolation(
    *,
    company_id: int,
    actor_id: int,
    foreign_variant_id: int,
    foreign_barcode_id: int,
    foreign_conversion_id: int,
    each_uom_id: int,
    carton_uom_id: int,
) -> None:
    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        await expect_http_code(
            "cross-company barcode read fails closed",
            404,
            "VARIANT_NOT_FOUND",
            lambda: catalog.list_barcodes(
                variant_id=foreign_variant_id,
                cursor=None,
                limit=100,
                db=app,
                actor=actor,
            ),
        )
    finally:
        await app.close()

    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        payload = catalog.BarcodeUpdate(
            request_id=uuid4(),
            expected_version=1,
            is_primary=False,
            valid_to=(
                datetime.utcnow()
                + timedelta(days=1)
            ),
            is_active=False,
        )
        await expect_http_code(
            "cross-company barcode modification fails closed",
            404,
            "BARCODE_NOT_FOUND",
            lambda: catalog.update_barcode(
                barcode_id=foreign_barcode_id,
                payload=payload,
                db=app,
                actor=actor,
            ),
        )
    finally:
        await app.close()

    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        await expect_http_code(
            "cross-company UOM conversion read fails closed",
            404,
            "VARIANT_NOT_FOUND",
            lambda: catalog.list_conversions(
                variant_id=foreign_variant_id,
                db=app,
                actor=actor,
            ),
        )
    finally:
        await app.close()

    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        payload = catalog.ConversionUpdate(
            request_id=uuid4(),
            from_uom_id=carton_uom_id,
            to_uom_id=each_uom_id,
            numerator=Decimal("10"),
            denominator=Decimal("1"),
            quantity_scale=0,
            expected_version=1,
        )
        await expect_http_code(
            "cross-company UOM conversion modification fails closed",
            404,
            "UOM_CONVERSION_NOT_FOUND",
            lambda: catalog.update_conversion(
                conversion_id=
                    foreign_conversion_id,
                payload=payload,
                db=app,
                actor=actor,
            ),
        )
    finally:
        await app.close()


async def verify_search_isolation(
    *,
    company_id: int,
    actor_id: int,
) -> None:
    app, actor = await api_actor(
        company_id,
        actor_id,
    )
    try:
        page = await list_simple_products(
            search="P2 Foreign",
            cursor=None,
            limit=50,
            family_id=None,
            lifecycle=None,
            tracking_type=None,
            simple_compatible=None,
            has_barcode=None,
            has_price=None,
            lot_tracked=None,
            expiry_tracked=None,
            sort_by="id",
            sort_dir="asc",
            db=app,
            actor=actor,
        )
        items = page.get("items")
        leaked = [
            item
            for item in (
                items
                if isinstance(items, list)
                else []
            )
            if "foreign"
            in (
                str(
                    item.get("name", "")
                )
                + " "
                + str(
                    item.get(
                        "family_name",
                        "",
                    )
                )
            ).lower()
        ]
        record(
            "Product search never leaks foreign Product names",
            isinstance(items, list)
            and not leaked,
            f"items={len(items) if isinstance(items, list) else -1}",
        )
    finally:
        await app.rollback()
        await app.close()


async def verify_import_isolation(
    *,
    company_id: int,
    foreign_company_id: int,
    own_job_id: UUID,
) -> None:
    async with p2_gate.SessionSU() as su:
        await su.begin()
        rows = (
            await su.execute(
                text(
                    "SELECT relname, "
                    "relrowsecurity, "
                    "relforcerowsecurity "
                    "FROM pg_class "
                    "WHERE relname IN "
                    "('product_import_jobs', "
                    "'product_import_rows')"
                )
            )
        ).mappings().all()
        await su.rollback()

    rls = {
        str(row["relname"]): (
            bool(row["relrowsecurity"]),
            bool(
                row[
                    "relforcerowsecurity"
                ]
            ),
        )
        for row in rows
    }
    jobs_rls = rls.get(
        "product_import_jobs"
    )
    rows_rls = rls.get(
        "product_import_rows"
    )
    record(
        "Product import job RLS remains ENABLE + FORCE",
        jobs_rls == (True, True),
        f"state={jobs_rls}",
    )
    record(
        "Product import row RLS remains ENABLE + FORCE",
        rows_rls == (True, True),
        f"state={rows_rls}",
    )

    token, db = await worker_tenant_session(
        company_id
    )
    try:
        current_tenant = str(
            (
                await db.execute(
                    text(
                        "SELECT current_setting("
                        "'app.current_tenant', true)"
                    )
                )
            ).scalar_one()
        )
        own_jobs = int(
            (
                await db.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM product_import_jobs "
                        "WHERE company_id = :company_id "
                        "AND id = :job_id"
                    ),
                    {
                        "company_id":
                            company_id,
                        "job_id":
                            own_job_id,
                    },
                )
            ).scalar_one()
        )
        foreign_jobs = int(
            (
                await db.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM product_import_jobs "
                        "WHERE company_id = "
                        ":foreign_company_id"
                    ),
                    {
                        "foreign_company_id":
                            foreign_company_id,
                    },
                )
            ).scalar_one()
        )
        foreign_rows = int(
            (
                await db.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM product_import_rows "
                        "WHERE company_id = "
                        ":foreign_company_id"
                    ),
                    {
                        "foreign_company_id":
                            foreign_company_id,
                    },
                )
            ).scalar_one()
        )

        record(
            "Product import worker sets exact tenant context",
            current_tenant
            == str(company_id)
            and own_jobs == 1,
            (
                f"current_tenant={current_tenant} "
                f"own_jobs={own_jobs}"
            ),
        )
        record(
            "Product import jobs remain tenant-isolated at runtime",
            foreign_jobs == 0,
            f"visible_foreign_jobs={foreign_jobs}",
        )
        record(
            "Product import rows remain tenant-isolated at runtime",
            foreign_rows == 0,
            f"visible_foreign_rows={foreign_rows}",
        )
    finally:
        await close_worker_tenant_session(
            token,
            db,
        )


async def verify_direct_rls_barcode_uom(
    *,
    company_id: int,
    foreign_company_id: int,
    foreign_barcode_id: int,
    foreign_conversion_id: int,
) -> None:
    async with p2_gate.SessionApp() as app:
        await app.begin()
        await p2_gate.set_tenant(
            app,
            company_id,
        )

        barcode_count = int(
            (
                await app.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM product_barcodes "
                        "WHERE company_id = "
                        ":foreign_company_id "
                        "AND id = :row_id"
                    ),
                    {
                        "foreign_company_id":
                            foreign_company_id,
                        "row_id":
                            foreign_barcode_id,
                    },
                )
            ).scalar_one()
        )
        conversion_count = int(
            (
                await app.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM product_uom_conversions "
                        "WHERE company_id = "
                        ":foreign_company_id "
                        "AND id = :row_id"
                    ),
                    {
                        "foreign_company_id":
                            foreign_company_id,
                        "row_id":
                            foreign_conversion_id,
                    },
                )
            ).scalar_one()
        )

        record(
            "barcode RLS hides foreign rows",
            barcode_count == 0,
            f"visible={barcode_count}",
        )
        record(
            "UOM conversion RLS hides foreign rows",
            conversion_count == 0,
            f"visible={conversion_count}",
        )

        await app.rollback()


async def cleanup_fixture(
    ids: dict[str, int],
    fixture: dict[str, int | UUID | bool],
) -> tuple[bool, str]:
    try:
        foreign_company_id = int(
            ids["foreign_company_id"]
        )
        async with p2_gate.SessionSU() as su:
            await su.begin()
            await su.execute(
                text(
                    "DELETE FROM product_barcodes "
                    "WHERE company_id = :company_id "
                    "AND id = :row_id"
                ),
                {
                    "company_id":
                        foreign_company_id,
                    "row_id": int(
                        fixture[
                            "foreign_barcode_id"
                        ]
                    ),
                },
            )
            await su.execute(
                text(
                    "DELETE FROM product_uom_conversions "
                    "WHERE company_id = :company_id "
                    "AND id = :row_id"
                ),
                {
                    "company_id":
                        foreign_company_id,
                    "row_id": int(
                        fixture[
                            "foreign_conversion_id"
                        ]
                    ),
                },
            )
            await su.commit()

        base_ok, base_detail = (
            await p2_gate.cleanup(ids)
        )
        if not base_ok:
            return False, base_detail

        if bool(
            fixture.get(
                "manage_permission_created",
                False,
            )
        ):
            async with p2_gate.SessionSU() as su:
                await su.begin()
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
                            fixture[
                                "manage_permission_id"
                            ]
                        )
                    },
                )
                await su.commit()

        return True, ""
    except Exception as exc:
        return (
            False,
            f"{type(exc).__name__}: {exc}",
        )


async def main() -> None:
    ids: dict[str, int] = {}
    fixture: dict[
        str,
        int | UUID | bool,
    ] = {}

    try:
        ids = await p2_gate.bootstrap()
        fixture = await seed_isolation_fixture(
            ids
        )

        company_id = int(
            ids["company_id"]
        )
        foreign_company_id = int(
            ids["foreign_company_id"]
        )
        actor_id = int(
            fixture["actor_id"]
        )

        await verify_direct_product_family_isolation(
            company_id=company_id,
            actor_id=actor_id,
            foreign_product_id=int(
                fixture[
                    "foreign_product_id"
                ]
            ),
            each_uom_id=int(
                ids["each_uom_id"]
            ),
        )

        await verify_barcode_uom_isolation(
            company_id=company_id,
            actor_id=actor_id,
            foreign_variant_id=int(
                fixture[
                    "foreign_variant_id"
                ]
            ),
            foreign_barcode_id=int(
                fixture[
                    "foreign_barcode_id"
                ]
            ),
            foreign_conversion_id=int(
                fixture[
                    "foreign_conversion_id"
                ]
            ),
            each_uom_id=int(
                ids["each_uom_id"]
            ),
            carton_uom_id=int(
                fixture[
                    "carton_uom_id"
                ]
            ),
        )

        await verify_direct_rls_barcode_uom(
            company_id=company_id,
            foreign_company_id=
                foreign_company_id,
            foreign_barcode_id=int(
                fixture[
                    "foreign_barcode_id"
                ]
            ),
            foreign_conversion_id=int(
                fixture[
                    "foreign_conversion_id"
                ]
            ),
        )

        await verify_search_isolation(
            company_id=company_id,
            actor_id=actor_id,
        )

        await verify_import_isolation(
            company_id=company_id,
            foreign_company_id=
                foreign_company_id,
            own_job_id=fixture[
                "own_job_id"
            ],
        )

    except Exception as exc:
        record(
            "P8 Product isolation gate completed without unexpected exception",
            False,
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        cleanup_ok, cleanup_detail = (
            await cleanup_fixture(
                ids,
                fixture,
            )
            if ids and fixture
            else await p2_gate.cleanup(
                ids
            )
        )
        record(
            "P8 Product isolation gate removes test data",
            cleanup_ok,
            cleanup_detail,
        )
        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()

    failures = [
        name
        for name, ok, _
        in RESULTS
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
            "PRODUCTS_P8_ISOLATION_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        "PRODUCTS_P8_ISOLATION_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
