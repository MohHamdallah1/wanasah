from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

import gate_products_read_contract_p2 as p2_gate
from api.catalog import VariantNameUpdate, rename_variant_name
from domains.live_stock_projection.service import refresh_live_stock_variants
from models import Driver


RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
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


async def ensure_permission(su, code: str) -> tuple[int, bool]:
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


async def seed(ids: dict[str, int]) -> dict[str, int | bool]:
    company_id = int(ids["company_id"])
    each_uom_id = int(ids["each_uom_id"])

    async with p2_gate.SessionSU() as su:
        await su.begin()
        manage_permission_id, manage_created = (
            await ensure_permission(su, "catalog.manage")
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
                        "'P9 Rename Actor', true, false, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "username": "p9_rename_" + uuid4().hex[:10],
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
                        "name": "P9 Rename " + uuid4().hex[:8],
                    },
                )
            ).scalar_one()
        )
        for permission_id in (
            int(ids["catalog_permission_id"]),
            manage_permission_id,
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
                    "permission_id": permission_id,
                },
            )
        await su.execute(
            text(
                "INSERT INTO user_roles "
                "(company_id, driver_id, role_id) "
                "VALUES (:company_id, :driver_id, :role_id)"
            ),
            {
                "company_id": company_id,
                "driver_id": actor_id,
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
                        "code": "P9-FAM-" + uuid4().hex[:10],
                        "name": "P9 Rename Family " + uuid4().hex[:8],
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
                        ":name, :sku, 0, 1, 'OPTIONAL', 'NONE', "
                        "'ACTIVE', 'NONE', 7, 5, NOW(), "
                        "1, false, 0, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "product_id": product_id,
                        "uom_id": each_uom_id,
                        "name": "P9 Rename Original",
                        "sku": "P9-RENAME-" + uuid4().hex[:10],
                    },
                )
            ).scalar_one()
        )

        archived_variant_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO product_variants "
                        "(company_id, product_id, base_uom_id, "
                        "name, sku, quantity_scale, quantity_step, "
                        "lot_control_mode, expiry_control_mode, "
                        "lifecycle_status, operational_hold, "
                        "lifecycle_revision, version, published_at, "
                        "archived_at, packs_per_carton, "
                        "package_uses_base_barcode, "
                        "default_max_samples_per_day, "
                        "created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :product_id, :uom_id, "
                        ":name, :sku, 0, 1, 'NONE', 'NONE', "
                        "'ARCHIVED', 'NONE', 3, 2, NOW(), NOW(), "
                        "1, false, 0, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "product_id": product_id,
                        "uom_id": each_uom_id,
                        "name": "P9 Archived Product",
                        "sku": "P9-ARCH-" + uuid4().hex[:10],
                    },
                )
            ).scalar_one()
        )

        warehouse_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO inventory_locations "
                        "(company_id, name, code, location_type, "
                        "is_system_managed, version, is_active, "
                        "created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :name, :code, 'WAREHOUSE', "
                        "false, 1, true, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "name": "P9 Rename Warehouse",
                        "code": "P9-WH-" + uuid4().hex[:8],
                    },
                )
            ).scalar_one()
        )
        await su.execute(
            text(
                "INSERT INTO inventory_stock_policies "
                "(company_id, location_id, product_variant_id, "
                "minimum_quantity, target_quantity, "
                "minimum_remaining_shelf_life_days, is_active, "
                "created_at, updated_at) "
                "VALUES "
                "(:company_id, :location_id, :variant_id, "
                "1, 10, 0, true, NOW(), NOW())"
            ),
            {
                "company_id": company_id,
                "location_id": warehouse_id,
                "variant_id": variant_id,
            },
        )
        await su.commit()

    return {
        "actor_id": actor_id,
        "product_id": product_id,
        "variant_id": variant_id,
        "archived_variant_id": archived_variant_id,
        "warehouse_id": warehouse_id,
        "manage_permission_id": manage_permission_id,
        "manage_permission_created": manage_created,
    }


async def app_actor(company_id: int, actor_id: int):
    db = p2_gate.SessionApp()
    await db.begin()
    await p2_gate.set_tenant(db, company_id)
    actor = await db.get(Driver, actor_id)
    if actor is None:
        await db.close()
        raise RuntimeError("P9 rename actor is not visible.")
    return db, actor


async def call_rename(
    *,
    company_id: int,
    actor_id: int,
    variant_id: int,
    payload: VariantNameUpdate,
):
    db, actor = await app_actor(company_id, actor_id)
    try:
        return await rename_variant_name(
            variant_id=variant_id,
            payload=payload,
            db=db,
            actor=actor,
        )
    finally:
        await db.close()


async def snapshot(company_id: int, variant_id: int) -> dict:
    async with p2_gate.SessionSU() as su:
        await su.begin()
        row = (
            await su.execute(
                text(
                    "SELECT "
                    "product_id, sku, base_uom_id, quantity_scale, "
                    "quantity_step::text AS quantity_step, "
                    "lot_control_mode, expiry_control_mode, "
                    "lifecycle_status, operational_hold, "
                    "lifecycle_revision, packs_per_carton, "
                    "package_uses_base_barcode, name, version, updated_at "
                    "FROM product_variants "
                    "WHERE company_id = :company_id AND id = :variant_id"
                ),
                {
                    "company_id": company_id,
                    "variant_id": variant_id,
                },
            )
        ).mappings().one()
        projection_name = (
            await su.execute(
                text(
                    "SELECT variant_name "
                    "FROM inventory_live_stock_projection "
                    "WHERE company_id = :company_id "
                    "AND product_variant_id = :variant_id"
                ),
                {
                    "company_id": company_id,
                    "variant_id": variant_id,
                },
            )
        ).scalar_one_or_none()
        return {
            **dict(row),
            "projection_name": projection_name,
        }


async def event_counts(
    company_id: int,
    variant_id: int,
) -> tuple[int, int]:
    async with p2_gate.SessionSU() as su:
        await su.begin()
        audit_count = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) FROM domain_audit_events "
                        "WHERE company_id = :company_id "
                        "AND entity_type = 'ProductVariant' "
                        "AND entity_id = :entity_id "
                        "AND event_type = 'ProductVariantRenamed'"
                    ),
                    {
                        "company_id": company_id,
                        "entity_id": str(variant_id),
                    },
                )
            ).scalar_one()
        )
        outbox_count = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) FROM transactional_outbox "
                        "WHERE company_id = :company_id "
                        "AND aggregate_type = 'ProductVariant' "
                        "AND aggregate_id = :entity_id "
                        "AND event_type = 'ProductVariantRenamed'"
                    ),
                    {
                        "company_id": company_id,
                        "entity_id": str(variant_id),
                    },
                )
            ).scalar_one()
        )
        return audit_count, outbox_count


async def cleanup(ids: dict[str, int | bool]) -> tuple[bool, str]:
    base_ok, base_detail = await p2_gate.cleanup(
        {k: int(v) for k, v in ids.items() if isinstance(v, int)}
    )
    if not base_ok:
        return base_ok, base_detail
    try:
        if bool(ids.get("manage_permission_created")):
            async with p2_gate.SessionSU() as su:
                await su.begin()
                await su.execute(
                    text(
                        "DELETE FROM permissions "
                        "WHERE id = :permission_id "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM role_permissions "
                        "WHERE permission_id = :permission_id)"
                    ),
                    {
                        "permission_id": int(
                            ids["manage_permission_id"]
                        ),
                    },
                )
                await su.commit()
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def main() -> None:
    ids: dict[str, int | bool] = {}
    try:
        base_ids = await p2_gate.bootstrap()
        ids.update(base_ids)
        seeded = await seed(base_ids)
        ids.update(seeded)

        company_id = int(ids["company_id"])
        actor_id = int(ids["actor_id"])
        variant_id = int(ids["variant_id"])

        db, _actor = await app_actor(company_id, actor_id)
        try:
            await refresh_live_stock_variants(
                db,
                company_id=company_id,
                variant_ids=[variant_id],
            )
            await db.commit()
        finally:
            await db.close()

        before = await snapshot(company_id, variant_id)
        record(
            "rename gate seeds the Live Stock projection with the old name",
            before["projection_name"] == before["name"],
            (
                f"variant={before['name']} "
                f"projection={before['projection_name']}"
            ),
        )

        request_id = uuid4()
        payload = VariantNameUpdate(
            request_id=request_id,
            expected_version=int(before["version"]),
            name="P9 Rename Published",
        )
        first = await call_rename(
            company_id=company_id,
            actor_id=actor_id,
            variant_id=variant_id,
            payload=payload,
        )
        after = await snapshot(company_id, variant_id)

        record(
            "ACTIVE published Product rename succeeds",
            first
            == {
                "product_variant_id": variant_id,
                "name": "P9 Rename Published",
                "version": int(before["version"]) + 1,
                "changed": True,
            },
            str(first),
        )

        immutable_fields = (
            "product_id",
            "sku",
            "base_uom_id",
            "quantity_scale",
            "quantity_step",
            "lot_control_mode",
            "expiry_control_mode",
            "lifecycle_status",
            "operational_hold",
            "lifecycle_revision",
            "packs_per_carton",
            "package_uses_base_barcode",
        )
        record(
            "rename changes only name/version/update timestamp",
            all(before[field] == after[field] for field in immutable_fields)
            and after["name"] == "P9 Rename Published"
            and int(after["version"]) == int(before["version"]) + 1
            and after["updated_at"] >= before["updated_at"],
        )
        record(
            "rename preserves lifecycle revision",
            after["lifecycle_revision"] == before["lifecycle_revision"],
            (
                f"before={before['lifecycle_revision']} "
                f"after={after['lifecycle_revision']}"
            ),
        )
        record(
            "rename refreshes Live Stock variant name transactionally",
            after["projection_name"] == "P9 Rename Published",
            str(after["projection_name"]),
        )

        audit_count, outbox_count = await event_counts(
            company_id,
            variant_id,
        )
        record(
            "real rename emits one audit event and one outbox event",
            audit_count == 1 and outbox_count == 1,
            f"audit={audit_count} outbox={outbox_count}",
        )

        replay = await call_rename(
            company_id=company_id,
            actor_id=actor_id,
            variant_id=variant_id,
            payload=payload,
        )
        replay_audit, replay_outbox = await event_counts(
            company_id,
            variant_id,
        )
        record(
            "rename replay is idempotent and emits no duplicate event",
            replay == first
            and replay_audit == 1
            and replay_outbox == 1,
            f"audit={replay_audit} outbox={replay_outbox}",
        )

        changed_payload_code = None
        try:
            await call_rename(
                company_id=company_id,
                actor_id=actor_id,
                variant_id=variant_id,
                payload=payload.model_copy(
                    update={"name": "P9 Reused Request Different Name"}
                ),
            )
        except HTTPException as exc:
            changed_payload_code = http_code(exc)
        record(
            "reusing rename request ID with a different payload fails closed",
            changed_payload_code == "IDEMPOTENCY_CONFLICT",
            str(changed_payload_code),
        )

        stale_code = None
        try:
            await call_rename(
                company_id=company_id,
                actor_id=actor_id,
                variant_id=variant_id,
                payload=VariantNameUpdate(
                    request_id=uuid4(),
                    expected_version=int(before["version"]),
                    name="P9 Stale Rename",
                ),
            )
        except HTTPException as exc:
            stale_code = http_code(exc)
        record(
            "stale rename version fails closed",
            stale_code == "VARIANT_VERSION_CONFLICT",
            str(stale_code),
        )

        before_noop_events = await event_counts(
            company_id,
            variant_id,
        )
        noop = await call_rename(
            company_id=company_id,
            actor_id=actor_id,
            variant_id=variant_id,
            payload=VariantNameUpdate(
                request_id=uuid4(),
                expected_version=int(after["version"]),
                name="  P9 Rename Published  ",
            ),
        )
        after_noop = await snapshot(company_id, variant_id)
        after_noop_events = await event_counts(
            company_id,
            variant_id,
        )
        record(
            "same-name rename is a true no-op",
            noop["changed"] is False
            and int(noop["version"]) == int(after["version"])
            and int(after_noop["version"]) == int(after["version"])
            and after_noop_events == before_noop_events,
        )

        archived_code = None
        try:
            await call_rename(
                company_id=company_id,
                actor_id=actor_id,
                variant_id=int(ids["archived_variant_id"]),
                payload=VariantNameUpdate(
                    request_id=uuid4(),
                    expected_version=2,
                    name="P9 Archived Rename",
                ),
            )
        except HTTPException as exc:
            archived_code = http_code(exc)
        record(
            "ARCHIVED Product rename is blocked",
            archived_code == "PRODUCT_NAME_EDIT_LIFECYCLE_BLOCKED",
            str(archived_code),
        )

        foreign_code = None
        try:
            await call_rename(
                company_id=company_id,
                actor_id=actor_id,
                variant_id=int(ids["foreign_variant_id"]),
                payload=VariantNameUpdate(
                    request_id=uuid4(),
                    expected_version=1,
                    name="P9 Cross Tenant Rename",
                ),
            )
        except HTTPException as exc:
            foreign_code = http_code(exc)
        record(
            "rename cannot cross the tenant boundary",
            foreign_code == "VARIANT_NOT_FOUND",
            str(foreign_code),
        )

        async with p2_gate.SessionSU() as su:
            await su.begin()
            idem_count = int(
                (
                    await su.execute(
                        text(
                            "SELECT COUNT(*) FROM operation_idempotency "
                            "WHERE company_id = :company_id "
                            "AND operation = 'CATALOG_VARIANT_NAME_UPDATE_V1' "
                            "AND request_id = :request_id"
                        ),
                        {
                            "company_id": company_id,
                            "request_id": str(request_id),
                        },
                    )
                ).scalar_one()
            )
        record(
            "rename replay persists one idempotency record",
            idem_count == 1,
            f"records={idem_count}",
        )

    except Exception as exc:
        record(
            "P9 rename runtime gate completed without unexpected exception",
            False,
            repr(exc),
        )
    finally:
        cleanup_ok, cleanup_detail = await cleanup(ids)
        record(
            "P9 rename gate cleanup completed",
            cleanup_ok,
            cleanup_detail,
        )

    failures = [name for name, ok, _detail in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")
    if failures:
        print("PRODUCTS_P9_RENAME_GATE=FAIL")
        raise SystemExit(1)
    print("PRODUCTS_P9_RENAME_GATE=PASS")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
