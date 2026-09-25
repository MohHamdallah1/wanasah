from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gate_products_read_contract_p2 as p2_gate
from api.catalog import VariantFamilyUpdate, reassign_variant_family
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


async def set_tenant(
    session: AsyncSession,
    company_id: int,
) -> None:
    await session.execute(
        text(
            "SELECT set_config("
            "'app.current_tenant', :tenant, true)"
        ),
        {"tenant": str(company_id)},
    )


async def scoped_session(
    conn,
    company_id: int,
) -> AsyncSession:
    session = AsyncSession(
        bind=conn,
        expire_on_commit=False,
        autobegin=False,
        join_transaction_mode="create_savepoint",
    )
    await session.begin()
    await set_tenant(session, company_id)
    return session


async def call_reassign(
    conn,
    *,
    company_id: int,
    actor_id: int,
    variant_id: int,
    payload: VariantFamilyUpdate,
):
    db = await scoped_session(conn, company_id)
    try:
        actor = await db.get(Driver, actor_id)
        if actor is None:
            raise RuntimeError(
                "P9 family-reassignment actor is not visible."
            )
        return await reassign_variant_family(
            variant_id=variant_id,
            payload=payload,
            db=db,
            actor=actor,
        )
    finally:
        await db.close()


async def seed(conn) -> dict[str, int]:
    for code in ("catalog.read", "catalog.manage"):
        await conn.execute(
            text(
                "INSERT INTO permissions (code) "
                "VALUES (:code) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code},
        )

    permission_rows = (
        await conn.execute(
            text(
                "SELECT code, id FROM permissions "
                "WHERE code IN ('catalog.read', 'catalog.manage')"
            )
        )
    ).all()
    permissions = {
        str(row.code): int(row.id)
        for row in permission_rows
    }
    if set(permissions) != {"catalog.read", "catalog.manage"}:
        raise RuntimeError(
            "Required catalog permissions are missing."
        )

    each_uom_id = (
        await conn.execute(
            text("SELECT id FROM uom WHERE code = 'EACH'")
        )
    ).scalar_one_or_none()
    if each_uom_id is None:
        raise RuntimeError("EACH UOM is missing.")

    async def company(label: str) -> int:
        return int(
            (
                await conn.execute(
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
                        "name": label,
                        "code": "P9FAM-" + uuid4().hex[:10],
                    },
                )
            ).scalar_one()
        )

    company_id = await company("P9 Family Reassignment Gate")
    foreign_company_id = await company(
        "P9 Family Reassignment Foreign"
    )

    async def actor(
        *,
        name: str,
        permission_codes: tuple[str, ...],
    ) -> int:
        actor_id = int(
            (
                await conn.execute(
                    text(
                        "INSERT INTO drivers "
                        "(company_id, username, password_hash, "
                        "full_name, is_active, is_admin, created_at) "
                        "VALUES "
                        "(:company_id, :username, 'x', :name, "
                        "true, false, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "username": "p9fam_" + uuid4().hex[:10],
                        "name": name,
                    },
                )
            ).scalar_one()
        )
        role_id = int(
            (
                await conn.execute(
                    text(
                        "INSERT INTO roles "
                        "(company_id, name, is_system_role) "
                        "VALUES (:company_id, :name, false) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "name": name + " " + uuid4().hex[:6],
                    },
                )
            ).scalar_one()
        )
        for code in permission_codes:
            await conn.execute(
                text(
                    "INSERT INTO role_permissions "
                    "(company_id, role_id, permission_id) "
                    "VALUES (:company_id, :role_id, :permission_id)"
                ),
                {
                    "company_id": company_id,
                    "role_id": role_id,
                    "permission_id": permissions[code],
                },
            )
        await conn.execute(
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
        return actor_id

    actor_id = await actor(
        name="P9 Family Manager",
        permission_codes=("catalog.read", "catalog.manage"),
    )
    read_only_actor_id = await actor(
        name="P9 Family Reader",
        permission_codes=("catalog.read",),
    )

    async def family(
        target_company_id: int,
        label: str,
    ) -> int:
        return int(
            (
                await conn.execute(
                    text(
                        "INSERT INTO products "
                        "(company_id, code, name, version, "
                        "created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :code, :name, 1, "
                        "TIMEZONE('UTC', CURRENT_TIMESTAMP), "
                        "TIMEZONE('UTC', CURRENT_TIMESTAMP)) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": target_company_id,
                        "code": "P9-FAM-" + uuid4().hex[:10],
                        "name": label,
                    },
                )
            ).scalar_one()
        )

    family_a_id = await family(
        company_id,
        "P9 Family Alpha",
    )
    family_b_id = await family(
        company_id,
        "P9 Family Beta",
    )
    family_c_id = await family(
        company_id,
        "P9 Family Gamma",
    )
    foreign_family_id = await family(
        foreign_company_id,
        "P9 Foreign Family",
    )

    async def variant(
        *,
        target_company_id: int,
        target_family_id: int,
        name: str,
        lifecycle: str,
        version: int,
        lifecycle_revision: int,
    ) -> int:
        published_sql = (
            "NULL" if lifecycle == "DRAFT" else
            "TIMEZONE('UTC', CURRENT_TIMESTAMP)"
        )
        retired_sql = (
            "TIMEZONE('UTC', CURRENT_TIMESTAMP)"
            if lifecycle in {"RETIRING", "ARCHIVED"}
            else "NULL"
        )
        archived_sql = (
            "TIMEZONE('UTC', CURRENT_TIMESTAMP)"
            if lifecycle == "ARCHIVED"
            else "NULL"
        )
        return int(
            (
                await conn.execute(
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
                        ":name, :sku, 0, 1, 'OPTIONAL', 'NONE', "
                        ":lifecycle, 'NONE', :lifecycle_revision, "
                        ":version, "
                        + published_sql
                        + ", "
                        + retired_sql
                        + ", "
                        + archived_sql
                        + ", 1, false, 0, "
                        "TIMEZONE('UTC', CURRENT_TIMESTAMP), "
                        "TIMEZONE('UTC', CURRENT_TIMESTAMP)) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": target_company_id,
                        "product_id": target_family_id,
                        "uom_id": int(each_uom_id),
                        "name": name,
                        "sku": "P9-FAM-SKU-" + uuid4().hex[:10],
                        "lifecycle": lifecycle,
                        "lifecycle_revision": lifecycle_revision,
                        "version": version,
                    },
                )
            ).scalar_one()
        )

    active_variant_id = await variant(
        target_company_id=company_id,
        target_family_id=family_a_id,
        name="P9 Family Active",
        lifecycle="ACTIVE",
        version=5,
        lifecycle_revision=7,
    )
    retiring_variant_id = await variant(
        target_company_id=company_id,
        target_family_id=family_a_id,
        name="P9 Family Retiring",
        lifecycle="RETIRING",
        version=3,
        lifecycle_revision=4,
    )
    history_variant_id = await variant(
        target_company_id=company_id,
        target_family_id=family_a_id,
        name="P9 Family With History",
        lifecycle="ACTIVE",
        version=6,
        lifecycle_revision=8,
    )
    target_guard_variant_id = await variant(
        target_company_id=company_id,
        target_family_id=family_a_id,
        name="P9 Family Target Guard",
        lifecycle="ACTIVE",
        version=2,
        lifecycle_revision=2,
    )
    draft_variant_id = await variant(
        target_company_id=company_id,
        target_family_id=family_a_id,
        name="P9 Family Draft",
        lifecycle="DRAFT",
        version=1,
        lifecycle_revision=1,
    )
    archived_variant_id = await variant(
        target_company_id=company_id,
        target_family_id=family_a_id,
        name="P9 Family Archived",
        lifecycle="ARCHIVED",
        version=2,
        lifecycle_revision=3,
    )
    foreign_variant_id = await variant(
        target_company_id=foreign_company_id,
        target_family_id=foreign_family_id,
        name="P9 Foreign Variant",
        lifecycle="ACTIVE",
        version=1,
        lifecycle_revision=1,
    )

    history_batch_id = int(
        (
            await conn.execute(
                text(
                    "INSERT INTO product_batches "
                    "(company_id, product_variant_id, batch_number, "
                    "disposition, disposition_revision, is_active, "
                    "created_at, updated_at) "
                    "VALUES "
                    "(:company_id, :variant_id, :batch_number, "
                    "'RELEASED', 1, true, "
                    "TIMEZONE('UTC', CURRENT_TIMESTAMP), "
                    "TIMEZONE('UTC', CURRENT_TIMESTAMP)) "
                    "RETURNING id"
                ),
                {
                    "company_id": company_id,
                    "variant_id": history_variant_id,
                    "batch_number": "P9-FAMILY-HISTORY-" + uuid4().hex[:8],
                },
            )
        ).scalar_one()
    )

    return {
        "company_id": company_id,
        "foreign_company_id": foreign_company_id,
        "actor_id": actor_id,
        "read_only_actor_id": read_only_actor_id,
        "family_a_id": family_a_id,
        "family_b_id": family_b_id,
        "family_c_id": family_c_id,
        "foreign_family_id": foreign_family_id,
        "active_variant_id": active_variant_id,
        "retiring_variant_id": retiring_variant_id,
        "history_variant_id": history_variant_id,
        "target_guard_variant_id": target_guard_variant_id,
        "draft_variant_id": draft_variant_id,
        "archived_variant_id": archived_variant_id,
        "foreign_variant_id": foreign_variant_id,
        "history_batch_id": history_batch_id,
    }


async def snapshot(
    conn,
    company_id: int,
    variant_id: int,
) -> dict:
    row = (
        await conn.execute(
            text(
                "SELECT "
                "product_id, sku, name, base_uom_id, quantity_scale, "
                "quantity_step::text AS quantity_step, "
                "lot_control_mode, expiry_control_mode, "
                "lifecycle_status, operational_hold, "
                "lifecycle_revision, packs_per_carton, "
                "package_uses_base_barcode, version, updated_at "
                "FROM product_variants "
                "WHERE company_id = :company_id AND id = :variant_id"
            ),
            {
                "company_id": company_id,
                "variant_id": variant_id,
            },
        )
    ).mappings().one()
    return dict(row)


async def event_counts(
    conn,
    company_id: int,
    variant_id: int,
) -> tuple[int, int]:
    audit_count = int(
        (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM domain_audit_events "
                    "WHERE company_id = :company_id "
                    "AND entity_type = 'ProductVariant' "
                    "AND entity_id = :entity_id "
                    "AND event_type = "
                    "'ProductVariantFamilyReassigned'"
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
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM transactional_outbox "
                    "WHERE company_id = :company_id "
                    "AND aggregate_type = 'ProductVariant' "
                    "AND aggregate_id = :entity_id "
                    "AND event_type = "
                    "'ProductVariantFamilyReassigned'"
                ),
                {
                    "company_id": company_id,
                    "entity_id": str(variant_id),
                },
            )
        ).scalar_one()
    )
    return audit_count, outbox_count


async def event_family_ids(
    conn,
    company_id: int,
    variant_id: int,
) -> tuple[int | None, int | None]:
    row = (
        await conn.execute(
            text(
                "SELECT "
                "(before_snapshot->>'product_id')::int AS before_family_id, "
                "(after_snapshot->>'product_id')::int AS after_family_id "
                "FROM domain_audit_events "
                "WHERE company_id = :company_id "
                "AND entity_type = 'ProductVariant' "
                "AND entity_id = :entity_id "
                "AND event_type = "
                "'ProductVariantFamilyReassigned' "
                "ORDER BY id DESC LIMIT 1"
            ),
            {
                "company_id": company_id,
                "entity_id": str(variant_id),
            },
        )
    ).one_or_none()
    if row is None:
        return None, None
    return int(row.before_family_id), int(row.after_family_id)


async def main() -> None:
    outer = None
    try:
        async with p2_gate.engine_su.connect() as conn:
            outer = await conn.begin()
            ids = await seed(conn)

            company_id = ids["company_id"]
            actor_id = ids["actor_id"]
            active_variant_id = ids["active_variant_id"]

            permission_codes = {
                str(row.code)
                for row in (
                    await conn.execute(
                        text(
                            "SELECT p.code "
                            "FROM permissions AS p "
                            "JOIN role_permissions AS rp "
                            "ON rp.permission_id = p.id "
                            "JOIN user_roles AS ur "
                            "ON ur.role_id = rp.role_id "
                            "AND ur.company_id = rp.company_id "
                            "WHERE ur.company_id = :company_id "
                            "AND ur.driver_id = :driver_id"
                        ),
                        {
                            "company_id": company_id,
                            "driver_id": actor_id,
                        },
                    )
                ).all()
            }
            record(
                "family reassignment actor has only catalog read/manage",
                permission_codes == {"catalog.read", "catalog.manage"},
                str(sorted(permission_codes)),
            )

            before = await snapshot(
                conn,
                company_id,
                active_variant_id,
            )
            request_id = uuid4()
            payload = VariantFamilyUpdate(
                request_id=request_id,
                expected_version=int(before["version"]),
                family_id=ids["family_b_id"],
            )
            first = await call_reassign(
                conn,
                company_id=company_id,
                actor_id=actor_id,
                variant_id=active_variant_id,
                payload=payload,
            )
            after = await snapshot(
                conn,
                company_id,
                active_variant_id,
            )

            record(
                "ACTIVE history-free Product family reassignment succeeds",
                first
                == {
                    "product_variant_id": active_variant_id,
                    "family_id": ids["family_b_id"],
                    "family_name": "P9 Family Beta",
                    "version": int(before["version"]) + 1,
                    "changed": True,
                },
                str(first),
            )

            immutable_fields = (
                "sku",
                "name",
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
            changed_immutable = [
                field
                for field in immutable_fields
                if before[field] != after[field]
            ]
            record(
                "family reassignment changes only family/version/update timestamp",
                not changed_immutable
                and int(after["product_id"]) == ids["family_b_id"]
                and int(after["version"]) == int(before["version"]) + 1
                and after["updated_at"] >= before["updated_at"],
                (
                    f"changed_immutable={changed_immutable} "
                    f"family={before['product_id']}->{after['product_id']} "
                    f"version={before['version']}->{after['version']}"
                ),
            )
            record(
                "family reassignment preserves lifecycle revision",
                after["lifecycle_revision"]
                == before["lifecycle_revision"],
                (
                    f"before={before['lifecycle_revision']} "
                    f"after={after['lifecycle_revision']}"
                ),
            )

            audit_count, outbox_count = await event_counts(
                conn,
                company_id,
                active_variant_id,
            )
            event_before_family, event_after_family = (
                await event_family_ids(
                    conn,
                    company_id,
                    active_variant_id,
                )
            )
            record(
                "family reassignment emits exact audit/outbox evidence",
                audit_count == 1
                and outbox_count == 1
                and event_before_family == ids["family_a_id"]
                and event_after_family == ids["family_b_id"],
                (
                    f"audit={audit_count} outbox={outbox_count} "
                    f"event={event_before_family}->{event_after_family}"
                ),
            )

            replay = await call_reassign(
                conn,
                company_id=company_id,
                actor_id=actor_id,
                variant_id=active_variant_id,
                payload=payload,
            )
            replay_events = await event_counts(
                conn,
                company_id,
                active_variant_id,
            )
            record(
                "exact family reassignment replay is idempotent",
                replay == first
                and replay_events == (1, 1),
                (
                    f"response={replay} "
                    f"events={replay_events}"
                ),
            )

            changed_payload_code = None
            try:
                await call_reassign(
                    conn,
                    company_id=company_id,
                    actor_id=actor_id,
                    variant_id=active_variant_id,
                    payload=payload.model_copy(
                        update={
                            "family_id": ids["family_c_id"],
                        }
                    ),
                )
            except HTTPException as exc:
                changed_payload_code = http_code(exc)
            record(
                "same request ID with different family fails closed",
                changed_payload_code == "IDEMPOTENCY_CONFLICT",
                str(changed_payload_code),
            )

            stale_code = None
            try:
                await call_reassign(
                    conn,
                    company_id=company_id,
                    actor_id=actor_id,
                    variant_id=active_variant_id,
                    payload=VariantFamilyUpdate(
                        request_id=uuid4(),
                        expected_version=int(before["version"]),
                        family_id=ids["family_c_id"],
                    ),
                )
            except HTTPException as exc:
                stale_code = http_code(exc)
            record(
                "stale family reassignment version fails closed",
                stale_code == "VARIANT_VERSION_CONFLICT",
                str(stale_code),
            )

            history_before = await snapshot(
                conn,
                company_id,
                ids["history_variant_id"],
            )
            history_events_before = await event_counts(
                conn,
                company_id,
                ids["history_variant_id"],
            )
            noop = await call_reassign(
                conn,
                company_id=company_id,
                actor_id=actor_id,
                variant_id=ids["history_variant_id"],
                payload=VariantFamilyUpdate(
                    request_id=uuid4(),
                    expected_version=int(history_before["version"]),
                    family_id=ids["family_a_id"],
                ),
            )
            history_after_noop = await snapshot(
                conn,
                company_id,
                ids["history_variant_id"],
            )
            history_events_after_noop = await event_counts(
                conn,
                company_id,
                ids["history_variant_id"],
            )
            record(
                "same-family request is a true no-op even with history",
                noop["changed"] is False
                and int(noop["version"]) == int(history_before["version"])
                and history_after_noop == history_before
                and history_events_after_noop == history_events_before,
                str(noop),
            )

            history_code = None
            try:
                await call_reassign(
                    conn,
                    company_id=company_id,
                    actor_id=actor_id,
                    variant_id=ids["history_variant_id"],
                    payload=VariantFamilyUpdate(
                        request_id=uuid4(),
                        expected_version=int(history_before["version"]),
                        family_id=ids["family_b_id"],
                    ),
                )
            except HTTPException as exc:
                history_code = http_code(exc)
            history_after_block = await snapshot(
                conn,
                company_id,
                ids["history_variant_id"],
            )
            history_events_after_block = await event_counts(
                conn,
                company_id,
                ids["history_variant_id"],
            )
            record(
                "batch history blocks a real family reassignment",
                history_code
                == "PRODUCT_FAMILY_REASSIGN_HISTORY_LOCKED"
                and history_after_block == history_before
                and history_events_after_block
                == history_events_before,
                (
                    f"code={history_code} "
                    f"batch_id={ids['history_batch_id']}"
                ),
            )

            retiring_before = await snapshot(
                conn,
                company_id,
                ids["retiring_variant_id"],
            )
            retiring = await call_reassign(
                conn,
                company_id=company_id,
                actor_id=actor_id,
                variant_id=ids["retiring_variant_id"],
                payload=VariantFamilyUpdate(
                    request_id=uuid4(),
                    expected_version=int(retiring_before["version"]),
                    family_id=ids["family_b_id"],
                ),
            )
            retiring_after = await snapshot(
                conn,
                company_id,
                ids["retiring_variant_id"],
            )
            record(
                "RETIRING history-free Product can change family safely",
                retiring["changed"] is True
                and int(retiring["family_id"]) == ids["family_b_id"]
                and retiring_after["lifecycle_status"] == "RETIRING"
                and retiring_after["lifecycle_revision"]
                == retiring_before["lifecycle_revision"],
                str(retiring),
            )

            for label, variant_key, expected_version in (
                ("DRAFT", "draft_variant_id", 1),
                ("ARCHIVED", "archived_variant_id", 2),
            ):
                lifecycle_code = None
                try:
                    await call_reassign(
                        conn,
                        company_id=company_id,
                        actor_id=actor_id,
                        variant_id=ids[variant_key],
                        payload=VariantFamilyUpdate(
                            request_id=uuid4(),
                            expected_version=expected_version,
                            family_id=ids["family_b_id"],
                        ),
                    )
                except HTTPException as exc:
                    lifecycle_code = http_code(exc)
                record(
                    f"{label} is blocked from published family reassignment",
                    lifecycle_code
                    == "PRODUCT_FAMILY_REASSIGN_LIFECYCLE_BLOCKED",
                    str(lifecycle_code),
                )

            foreign_variant_code = None
            try:
                await call_reassign(
                    conn,
                    company_id=company_id,
                    actor_id=actor_id,
                    variant_id=ids["foreign_variant_id"],
                    payload=VariantFamilyUpdate(
                        request_id=uuid4(),
                        expected_version=1,
                        family_id=ids["family_b_id"],
                    ),
                )
            except HTTPException as exc:
                foreign_variant_code = http_code(exc)
            record(
                "family reassignment cannot cross variant tenant boundary",
                foreign_variant_code == "VARIANT_NOT_FOUND",
                str(foreign_variant_code),
            )

            target_before = await snapshot(
                conn,
                company_id,
                ids["target_guard_variant_id"],
            )
            foreign_family_code = None
            try:
                await call_reassign(
                    conn,
                    company_id=company_id,
                    actor_id=actor_id,
                    variant_id=ids["target_guard_variant_id"],
                    payload=VariantFamilyUpdate(
                        request_id=uuid4(),
                        expected_version=int(target_before["version"]),
                        family_id=ids["foreign_family_id"],
                    ),
                )
            except HTTPException as exc:
                foreign_family_code = http_code(exc)
            target_after = await snapshot(
                conn,
                company_id,
                ids["target_guard_variant_id"],
            )
            record(
                "target family must belong to the same company",
                foreign_family_code
                == "PRODUCT_FAMILY_REASSIGN_TARGET_NOT_FOUND"
                and target_after == target_before,
                str(foreign_family_code),
            )

            permission_status = None
            try:
                await call_reassign(
                    conn,
                    company_id=company_id,
                    actor_id=ids["read_only_actor_id"],
                    variant_id=ids["target_guard_variant_id"],
                    payload=VariantFamilyUpdate(
                        request_id=uuid4(),
                        expected_version=int(target_before["version"]),
                        family_id=ids["family_b_id"],
                    ),
                )
            except HTTPException as exc:
                permission_status = exc.status_code
            record(
                "catalog reader without manage permission cannot change family",
                permission_status == 403,
                str(permission_status),
            )

            idem_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM operation_idempotency "
                            "WHERE company_id = :company_id "
                            "AND operation = "
                            "'CATALOG_VARIANT_FAMILY_REASSIGN_V1' "
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
                "exact family replay persists one idempotency record",
                idem_count == 1,
                f"records={idem_count}",
            )

            await outer.rollback()
            outer = None

            persisted = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM companies "
                            "WHERE id IN (:company_id, :foreign_company_id)"
                        ),
                        {
                            "company_id": company_id,
                            "foreign_company_id": ids[
                                "foreign_company_id"
                            ],
                        },
                    )
                ).scalar_one()
            )
            record(
                "family reassignment gate leaves no committed tenant data",
                persisted == 0,
                f"companies={persisted}",
            )

    except Exception as exc:
        record(
            (
                "P9 family reassignment runtime gate completed "
                "without unexpected exception"
            ),
            False,
            repr(exc),
        )
    finally:
        if outer is not None and outer.is_active:
            await outer.rollback()

    failures = [
        name
        for name, ok, _detail in RESULTS
        if not ok
    ]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")
    if failures:
        print("PRODUCTS_P9_FAMILY_REASSIGNMENT_GATE=FAIL")
        raise SystemExit(1)
    print("PRODUCTS_P9_FAMILY_REASSIGNMENT_GATE=PASS")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
