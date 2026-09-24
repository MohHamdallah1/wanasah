from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

import gate_products_read_contract_p2 as p2_gate
from api import catalog
from api.simple_products import (
    SimplePriceUpdate,
    SimpleProductCreate,
    create_simple_product,
    update_simple_product_price,
)
from domains.simple_products.service import (
    SimpleProductError,
    create_family,
    rename_family,
)
from models import Driver


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


def http_code(exc: HTTPException) -> str | None:
    if isinstance(exc.detail, dict):
        value = exc.detail.get("code")
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


async def seed_actor(
    ids: dict[str, int],
) -> dict[str, int | bool]:
    company_id = int(ids["company_id"])
    permission_codes = (
        "catalog.manage",
        "catalog.publish",
        "pricing.manage",
    )

    async with p2_gate.SessionSU() as su:
        await su.begin()

        permission_meta: dict[
            str,
            tuple[int, bool],
        ] = {}
        for code in permission_codes:
            permission_meta[code] = (
                await ensure_permission(su, code)
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
                        "'P8 Concurrency Actor', true, false, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "username": (
                            "p8_conc_"
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
                        "VALUES (:company_id, :name, false) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "name": (
                            "P8 Concurrency "
                            + uuid4().hex[:8]
                        ),
                    },
                )
            ).scalar_one()
        )

        for permission_id, _created in (
            permission_meta.values()
        ):
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
                    "permission_id":
                        int(permission_id),
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

        await su.commit()

    result: dict[str, int | bool] = {
        "actor_id": actor_id,
    }
    for code, (
        permission_id,
        created,
    ) in permission_meta.items():
        key = (
            code.replace(".", "_")
        )
        result[
            f"{key}_permission_id"
        ] = int(permission_id)
        result[
            f"{key}_permission_created"
        ] = bool(created)
    return result


async def app_actor(
    company_id: int,
    actor_id: int,
):
    db = p2_gate.SessionApp()
    await db.begin()
    await p2_gate.set_tenant(
        db,
        company_id,
    )
    actor = await db.get(
        Driver,
        actor_id,
    )
    if actor is None:
        await db.close()
        raise RuntimeError(
            "P8 concurrency actor is not visible."
        )
    return db, actor


async def call_with_fresh_session(
    *,
    company_id: int,
    actor_id: int,
    fn,
    **kwargs,
):
    db, actor = await app_actor(
        company_id,
        actor_id,
    )
    try:
        return await fn(
            db=db,
            actor=actor,
            **kwargs,
        )
    finally:
        await db.close()


async def test_product_and_price_idempotency(
    *,
    company_id: int,
    actor_id: int,
) -> int:
    request_id = uuid4()
    payload = SimpleProductCreate(
        request_id=request_id,
        name=(
            "P8 Idempotent Product "
            + uuid4().hex[:8]
        ),
        family_id=None,
        family_name=(
            "P8 Idempotent Family "
            + uuid4().hex[:8]
        ),
        package_uom_code=None,
        units_per_package=1,
        package_price=None,
        unit_price=Decimal("1.250000"),
        unit_barcode=None,
        package_barcode=None,
        lot_control_mode="NONE",
        expiry_control_mode="NONE",
    )

    first = await call_with_fresh_session(
        company_id=company_id,
        actor_id=actor_id,
        fn=create_simple_product,
        payload=payload,
    )
    replay = await call_with_fresh_session(
        company_id=company_id,
        actor_id=actor_id,
        fn=create_simple_product,
        payload=payload,
    )

    variant_id = int(
        first["product_variant_id"]
    )
    record(
        "Product create replay is idempotent",
        first == replay
        and int(
            replay["product_variant_id"]
        )
        == variant_id,
        f"variant_id={variant_id}",
    )

    changed = payload.model_copy(
        update={
            "name": (
                payload.name
                + " changed"
            ),
        }
    )
    changed_failed = False
    changed_status = None
    changed_code = None
    try:
        await call_with_fresh_session(
            company_id=company_id,
            actor_id=actor_id,
            fn=create_simple_product,
            payload=changed,
        )
    except HTTPException as exc:
        changed_failed = True
        changed_status = exc.status_code
        changed_code = http_code(exc)

    record(
        "Changed payload with reused Product request ID fails",
        changed_failed
        and changed_status == 409,
        (
            f"status={changed_status} "
            f"code={changed_code}"
        ),
    )

    async with p2_gate.SessionSU() as su:
        await su.begin()
        create_idem_count = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM operation_idempotency "
                        "WHERE company_id = :company_id "
                        "AND operation = "
                        "'SIMPLE_PRODUCT_CREATE_V3' "
                        "AND request_id = :request_id"
                    ),
                    {
                        "company_id":
                            company_id,
                        "request_id":
                            str(request_id),
                    },
                )
            ).scalar_one()
        )

    record(
        "Product create replay persists one idempotency record",
        create_idem_count == 1,
        f"records={create_idem_count}",
    )

    async with p2_gate.SessionSU() as su:
        await su.begin()
        before_publications = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM price_publications "
                        "WHERE company_id = :company_id"
                    ),
                    {
                        "company_id":
                            company_id,
                    },
                )
            ).scalar_one()
        )

    price_request = uuid4()
    price_payload = SimplePriceUpdate(
        request_id=price_request,
        package_price=None,
        unit_price=Decimal("1.500000"),
    )
    first_price = (
        await call_with_fresh_session(
            company_id=company_id,
            actor_id=actor_id,
            fn=update_simple_product_price,
            variant_id=variant_id,
            payload=price_payload,
        )
    )
    replay_price = (
        await call_with_fresh_session(
            company_id=company_id,
            actor_id=actor_id,
            fn=update_simple_product_price,
            variant_id=variant_id,
            payload=price_payload,
        )
    )

    async with p2_gate.SessionSU() as su:
        await su.begin()
        after_publications = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM price_publications "
                        "WHERE company_id = :company_id"
                    ),
                    {
                        "company_id":
                            company_id,
                    },
                )
            ).scalar_one()
        )

    record(
        "Price update replay is idempotent",
        first_price == replay_price
        and (
            after_publications
            - before_publications
        )
        == 1,
        (
            "publication_delta="
            f"{after_publications - before_publications}"
        ),
    )

    return variant_id


async def new_tenant_session(
    company_id: int,
):
    db = p2_gate.SessionApp()
    await db.begin()
    await p2_gate.set_tenant(
        db,
        company_id,
    )
    return db


async def test_family_concurrency(
    *,
    company_id: int,
) -> None:
    create_name = (
        "P8 Family Race "
        + uuid4().hex[:10]
    )

    first_db = await new_tenant_session(
        company_id
    )
    first = await create_family(
        first_db,
        company_id=company_id,
        request_id=uuid4(),
        name=create_name,
    )

    contender_started = asyncio.Event()

    async def create_contender():
        db = await new_tenant_session(
            company_id
        )
        contender_started.set()
        try:
            await create_family(
                db,
                company_id=company_id,
                request_id=uuid4(),
                name=create_name,
            )
            await db.commit()
            return "unexpected-success"
        except SimpleProductError as exc:
            await db.rollback()
            return exc.code
        finally:
            await db.close()

    task = asyncio.create_task(
        create_contender()
    )
    await contender_started.wait()
    await asyncio.sleep(0.15)
    blocked_before_release = (
        not task.done()
    )
    await first_db.commit()
    await first_db.close()
    contender_result = await asyncio.wait_for(
        task,
        timeout=5,
    )

    record(
        "Family create concurrency serializes duplicate names",
        blocked_before_release
        and contender_result
        == "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",
        (
            f"blocked={blocked_before_release} "
            f"result={contender_result}"
        ),
    )

    seed_db = await new_tenant_session(
        company_id
    )
    family_a = await create_family(
        seed_db,
        company_id=company_id,
        request_id=uuid4(),
        name=(
            "P8 Family Rename A "
            + uuid4().hex[:8]
        ),
    )
    family_b = await create_family(
        seed_db,
        company_id=company_id,
        request_id=uuid4(),
        name=(
            "P8 Family Rename B "
            + uuid4().hex[:8]
        ),
    )
    family_a_id = int(family_a.id)
    family_b_id = int(family_b.id)
    await seed_db.commit()
    await seed_db.close()

    target_name = (
        "P8 Family Rename Target "
        + uuid4().hex[:8]
    )

    rename_db = await new_tenant_session(
        company_id
    )
    renamed = await rename_family(
        rename_db,
        company_id=company_id,
        family_id=family_a_id,
        expected_version=1,
        name=target_name,
    )
    renamed_version = int(renamed.version)

    rename_started = asyncio.Event()

    async def rename_contender():
        db = await new_tenant_session(
            company_id
        )
        rename_started.set()
        try:
            await rename_family(
                db,
                company_id=company_id,
                family_id=family_b_id,
                expected_version=1,
                name=target_name,
            )
            await db.commit()
            return "unexpected-success"
        except SimpleProductError as exc:
            await db.rollback()
            return exc.code
        finally:
            await db.close()

    rename_task = asyncio.create_task(
        rename_contender()
    )
    await rename_started.wait()
    await asyncio.sleep(0.15)
    rename_blocked = (
        not rename_task.done()
    )
    await rename_db.commit()
    await rename_db.close()
    rename_result = (
        await asyncio.wait_for(
            rename_task,
            timeout=5,
        )
    )

    record(
        "Family rename concurrency serializes duplicate target names",
        rename_blocked
        and rename_result
        == "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",
        (
            f"blocked={rename_blocked} "
            f"result={rename_result}"
        ),
    )

    stale_db = await new_tenant_session(
        company_id
    )
    stale_code = None
    try:
        await rename_family(
            stale_db,
            company_id=company_id,
            family_id=family_a_id,
            expected_version=1,
            name=(
                target_name
                + " stale"
            ),
        )
    except SimpleProductError as exc:
        stale_code = exc.code
        await stale_db.rollback()
    finally:
        await stale_db.close()

    record(
        "Family stale version fails closed",
        renamed_version == 2
        and stale_code
        == "SIMPLE_PRODUCT_FAMILY_VERSION_CONFLICT",
        (
            f"version={renamed_version} "
            f"code={stale_code}"
        ),
    )


async def seed_barcode_variants(
    *,
    company_id: int,
    actor_id: int,
    each_uom_id: int,
) -> tuple[int, int]:
    product_payload = catalog.ProductCreate(
        request_id=uuid4(),
        code=(
            "P8-CONC-"
            + uuid4().hex[:10]
        ),
        name=(
            "P8 Barcode Parent "
            + uuid4().hex[:8]
        ),
        description=None,
        brand=None,
        category=None,
    )
    parent = await call_with_fresh_session(
        company_id=company_id,
        actor_id=actor_id,
        fn=catalog.create_product,
        payload=product_payload,
    )
    product_id = int(
        parent["product"]["id"]
    )

    variants: list[int] = []
    for index in (1, 2):
        payload = catalog.VariantCreate(
            request_id=uuid4(),
            product_id=product_id,
            sku=(
                f"P8-RACE-{index}-"
                + uuid4().hex[:8]
            ),
            gtin=None,
            name=(
                f"P8 Barcode Variant {index}"
            ),
            base_uom_id=each_uom_id,
            quantity_scale=0,
            quantity_step=Decimal("1"),
            lot_control_mode="NONE",
            expiry_control_mode="NONE",
        )
        result = await call_with_fresh_session(
            company_id=company_id,
            actor_id=actor_id,
            fn=catalog.create_variant,
            payload=payload,
        )
        variants.append(
            int(result["variant"]["id"])
        )

    return variants[0], variants[1]


async def test_barcode_race_and_lifecycle(
    *,
    company_id: int,
    actor_id: int,
    each_uom_id: int,
) -> None:
    variant_a, variant_b = (
        await seed_barcode_variants(
            company_id=company_id,
            actor_id=actor_id,
            each_uom_id=each_uom_id,
        )
    )

    barcode = (
        "P8-RACE-BARCODE-"
        + uuid4().hex[:16]
    )

    async def create_barcode_for(
        variant_id: int,
    ):
        payload = catalog.BarcodeCreate(
            request_id=uuid4(),
            uom_id=each_uom_id,
            barcode=barcode,
            barcode_type="INTERNAL",
            is_primary=True,
            valid_from=None,
            valid_to=None,
        )
        try:
            result = await call_with_fresh_session(
                company_id=company_id,
                actor_id=actor_id,
                fn=catalog.create_barcode,
                variant_id=variant_id,
                payload=payload,
            )
            return (
                "success",
                result,
            )
        except HTTPException as exc:
            return (
                "error",
                (
                    exc.status_code,
                    http_code(exc),
                ),
            )

    race_results = await asyncio.gather(
        create_barcode_for(variant_a),
        create_barcode_for(variant_b),
    )
    successes = [
        item
        for item in race_results
        if item[0] == "success"
    ]
    conflicts = [
        item
        for item in race_results
        if item[0] == "error"
        and item[1][0] == 409
        and item[1][1]
        == "BARCODE_CONFLICT"
    ]

    async with p2_gate.SessionSU() as su:
        await su.begin()
        barcode_rows = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM product_barcodes "
                        "WHERE company_id = :company_id "
                        "AND barcode = :barcode "
                        "AND is_active IS TRUE"
                    ),
                    {
                        "company_id":
                            company_id,
                        "barcode": barcode,
                    },
                )
            ).scalar_one()
        )

    record(
        "Barcode uniqueness race allows one winner",
        len(successes) == 1
        and len(conflicts) == 1
        and barcode_rows == 1,
        (
            f"successes={len(successes)} "
            f"conflicts={len(conflicts)} "
            f"rows={barcode_rows}"
        ),
    )

    async with p2_gate.SessionSU() as su:
        await su.begin()
        before = (
            await su.execute(
                text(
                    "SELECT version, "
                    "lifecycle_revision "
                    "FROM product_variants "
                    "WHERE company_id = :company_id "
                    "AND id = :variant_id"
                ),
                {
                    "company_id":
                        company_id,
                    "variant_id":
                        variant_a,
                },
            )
        ).mappings().one()
    before_version = int(
        before["version"]
    )
    before_revision = int(
        before["lifecycle_revision"]
    )

    publish_payload = catalog.LifecycleCommand(
        request_id=uuid4(),
        expected_version=before_version,
        reason="P8 lifecycle concurrency proof",
    )
    first_publish = (
        await call_with_fresh_session(
            company_id=company_id,
            actor_id=actor_id,
            fn=catalog.publish_variant,
            variant_id=variant_a,
            payload=publish_payload,
        )
    )

    stale_payload = catalog.LifecycleCommand(
        request_id=uuid4(),
        expected_version=before_version,
        reason="P8 stale lifecycle proof",
    )
    stale_status = None
    stale_code = None
    try:
        await call_with_fresh_session(
            company_id=company_id,
            actor_id=actor_id,
            fn=catalog.publish_variant,
            variant_id=variant_a,
            payload=stale_payload,
        )
    except HTTPException as exc:
        stale_status = exc.status_code
        stale_code = http_code(exc)

    async with p2_gate.SessionSU() as su:
        await su.begin()
        after = (
            await su.execute(
                text(
                    "SELECT version, "
                    "lifecycle_revision, "
                    "lifecycle_status "
                    "FROM product_variants "
                    "WHERE company_id = :company_id "
                    "AND id = :variant_id"
                ),
                {
                    "company_id":
                        company_id,
                    "variant_id":
                        variant_a,
                },
            )
        ).mappings().one()

    record(
        "Lifecycle transition rejects stale revision/version",
        first_publish["variant"][
            "lifecycle_status"
        ]
        == "ACTIVE"
        and int(after["version"])
        == before_version + 1
        and int(
            after["lifecycle_revision"]
        )
        == before_revision + 1
        and stale_status == 409
        and stale_code
        == "VARIANT_VERSION_CONFLICT",
        (
            f"version={before_version}"
            f"->{after['version']} "
            f"revision={before_revision}"
            f"->{after['lifecycle_revision']} "
            f"stale={stale_status}/{stale_code}"
        ),
    )


async def cleanup_pricing_history(
    company_ids: list[int],
) -> None:
    if not company_ids:
        return

    async with p2_gate.SessionSU() as su:
        await su.begin()

        rows = (
            await su.execute(
                text(
                    "SELECT id, name, company_code "
                    "FROM companies "
                    "WHERE id = ANY(CAST(:company_ids AS integer[]))"
                ),
                {
                    "company_ids":
                        company_ids,
                },
            )
        ).mappings().all()
        if len(rows) != len(
            set(company_ids)
        ):
            raise RuntimeError(
                "P8 concurrency cleanup company set is incomplete."
            )

        for row in rows:
            if (
                str(row["name"])
                not in {
                    "P2 Read Contract Gate A",
                    "P2 Read Contract Gate B",
                }
                or not str(
                    row["company_code"]
                ).startswith("P2READ-")
            ):
                raise RuntimeError(
                    "Refusing pricing cleanup outside synthetic P8 companies."
                )

        triggers = (
            (
                "price_book_entries",
                "trg_published_price_entry_guard",
            ),
            (
                "price_publications",
                "trg_price_publication_history_guard",
            ),
            (
                "price_book_assignments",
                "trg_price_assignment_history_guard",
            ),
        )

        for table_name, trigger_name in triggers:
            await su.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    f"DISABLE TRIGGER {trigger_name}"
                )
            )

        try:
            await su.execute(
                text(
                    "DELETE FROM price_book_entries "
                    "WHERE company_id = ANY(CAST(:company_ids AS integer[]))"
                ),
                {
                    "company_ids":
                        company_ids,
                },
            )
            await su.execute(
                text(
                    "DELETE FROM price_publications "
                    "WHERE company_id = ANY(CAST(:company_ids AS integer[]))"
                ),
                {
                    "company_ids":
                        company_ids,
                },
            )
            await su.execute(
                text(
                    "DELETE FROM price_book_assignments "
                    "WHERE company_id = ANY(CAST(:company_ids AS integer[]))"
                ),
                {
                    "company_ids":
                        company_ids,
                },
            )
        finally:
            for (
                table_name,
                trigger_name,
            ) in reversed(triggers):
                await su.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ENABLE TRIGGER {trigger_name}"
                    )
                )

        await su.execute(
            text(
                "DELETE FROM product_barcodes "
                "WHERE company_id = ANY(CAST(:company_ids AS integer[]))"
            ),
            {
                "company_ids":
                    company_ids,
            },
        )
        await su.execute(
            text(
                "DELETE FROM product_uom_conversions "
                "WHERE company_id = ANY(CAST(:company_ids AS integer[]))"
            ),
            {
                "company_ids":
                    company_ids,
            },
        )
        await su.commit()


async def cleanup_all(
    ids: dict[str, int],
    actor_meta: dict[
        str,
        int | bool,
    ],
) -> tuple[bool, str]:
    try:
        company_ids = [
            int(value)
            for value in (
                ids.get("company_id"),
                ids.get(
                    "foreign_company_id"
                ),
            )
            if value is not None
        ]
        await cleanup_pricing_history(
            company_ids
        )

        async with p2_gate.SessionSU() as su:
            await su.begin()
            params = {
                "company_ids": company_ids,
            }
            for table_name in (
                "transactional_outbox",
                "domain_audit_events",
                "system_audit_logs",
                "operation_idempotency",
            ):
                await su.execute(
                    text(
                        f"DELETE FROM {table_name} "
                        "WHERE company_id = ANY("
                        "CAST(:company_ids AS integer[]))"
                    ),
                    params,
                )
            await su.commit()

        base_ok, base_detail = (
            await p2_gate.cleanup(ids)
        )
        if not base_ok:
            return False, base_detail

        created_pairs = (
            (
                "catalog_manage_permission_created",
                "catalog_manage_permission_id",
            ),
            (
                "catalog_publish_permission_created",
                "catalog_publish_permission_id",
            ),
            (
                "pricing_manage_permission_created",
                "pricing_manage_permission_id",
            ),
        )

        async with p2_gate.SessionSU() as su:
            await su.begin()
            for created_key, id_key in created_pairs:
                if not bool(
                    actor_meta.get(
                        created_key,
                        False,
                    )
                ):
                    continue
                await su.execute(
                    text(
                        "DELETE FROM permissions AS p "
                        "WHERE p.id = :permission_id "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM role_permissions rp "
                        "WHERE rp.permission_id = p.id"
                        ")"
                    ),
                    {
                        "permission_id": int(
                            actor_meta[
                                id_key
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
    actor_meta: dict[
        str,
        int | bool,
    ] = {}

    try:
        ids = await p2_gate.bootstrap()
        actor_meta = await seed_actor(ids)

        company_id = int(
            ids["company_id"]
        )
        actor_id = int(
            actor_meta["actor_id"]
        )

        await test_product_and_price_idempotency(
            company_id=company_id,
            actor_id=actor_id,
        )
        await test_family_concurrency(
            company_id=company_id,
        )
        await test_barcode_race_and_lifecycle(
            company_id=company_id,
            actor_id=actor_id,
            each_uom_id=int(
                ids["each_uom_id"]
            ),
        )

    except Exception as exc:
        record(
            "P8 concurrency/idempotency gate completed without unexpected exception",
            False,
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        cleanup_ok, cleanup_detail = (
            await cleanup_all(
                ids,
                actor_meta,
            )
            if ids
            else (True, "")
        )
        record(
            "P8 concurrency/idempotency gate removes test data",
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
            "PRODUCTS_P8_CONCURRENCY_IDEMPOTENCY_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        "PRODUCTS_P8_CONCURRENCY_IDEMPOTENCY_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
