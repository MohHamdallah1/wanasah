from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=False)

from domains.product_tracking import (
    ProductTrackingError,
    load_company_product_tracking_defaults_state,
    resolve_product_tracking_modes,
    save_company_product_tracking_defaults_serialized,
    update_product_tracking_modes,
)
from product_lifecycle import (
    acquire_product_lifecycle_guards,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


MIGRATION_URL = os.environ["DATABASE_URL_MIGRATION"]
APP_URL = os.environ["DATABASE_URL"]

engine_su = create_async_engine(
    MIGRATION_URL,
    pool_size=5,
    max_overflow=5,
)
engine_app = create_async_engine(
    APP_URL,
    pool_size=10,
    max_overflow=10,
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


async def cleanup_company(
    company_id: int | None,
) -> tuple[bool, str]:
    if not company_id:
        return True, ""

    immutable_audit_tables = {
        "domain_audit_events",
        "system_audit_logs",
    }

    try:
        async with SessionSU() as su:
            await su.begin()
            await set_tenant(
                su,
                int(company_id),
            )

            # Append-only audit evidence is a production invariant. The gate
            # must never disable or bypass those guards just to clean itself.
            # Any immutable evidence for this disposable tenant means a test
            # transaction leaked a commit and the gate must fail explicitly.
            audit_leaks: dict[str, int] = {}
            for table_name in sorted(
                immutable_audit_tables
            ):
                quoted = (
                    '"'
                    + table_name.replace(
                        '"',
                        '""',
                    )
                    + '"'
                )
                count = int(
                    (
                        await su.execute(
                            text(
                                f"SELECT count(*) FROM {quoted} "
                                "WHERE company_id = :company_id"
                            ),
                            {
                                "company_id": int(
                                    company_id
                                )
                            },
                        )
                    ).scalar_one()
                )
                if count:
                    audit_leaks[
                        table_name
                    ] = count

            if audit_leaks:
                await su.rollback()
                return (
                    False,
                    (
                        "runtime gate leaked immutable audit evidence: "
                        + ", ".join(
                            f"{name}={count}"
                            for name, count in sorted(
                                audit_leaks.items()
                            )
                        )
                    ),
                )

            table_rows = (
                await su.execute(
                    text(
                        """
                        SELECT c.relname
                        FROM pg_class AS c
                        JOIN pg_namespace AS n
                          ON n.oid = c.relnamespace
                        JOIN pg_attribute AS a
                          ON a.attrelid = c.oid
                        WHERE n.nspname = current_schema()
                          AND c.relkind IN ('r', 'p')
                          AND a.attname = 'company_id'
                          AND NOT a.attisdropped
                          AND c.relname <> 'companies'
                        ORDER BY c.relname
                        """
                    )
                )
            ).scalars().all()

            pending = {
                str(table_name)
                for table_name in table_rows
                if str(table_name)
                not in immutable_audit_tables
            }
            last_errors: dict[str, str] = {}

            # FK RESTRICT edges are not guaranteed to follow model/file order.
            # Delete only mutable rows owned by this disposable tenant in
            # repeated savepoint-protected passes. Immutable audit tables are
            # intentionally excluded above and are required to be empty.
            for _ in range(
                len(pending) + 1
            ):
                if not pending:
                    break

                progressed = False
                for table_name in sorted(
                    tuple(pending)
                ):
                    quoted = (
                        '"'
                        + table_name.replace(
                            '"',
                            '""',
                        )
                        + '"'
                    )
                    try:
                        async with su.begin_nested():
                            await su.execute(
                                text(
                                    f"DELETE FROM {quoted} "
                                    "WHERE company_id = :company_id"
                                ),
                                {
                                    "company_id": int(
                                        company_id
                                    )
                                },
                            )
                        pending.remove(
                            table_name
                        )
                        last_errors.pop(
                            table_name,
                            None,
                        )
                        progressed = True
                    except Exception as exc:
                        last_errors[
                            table_name
                        ] = (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )

                if not progressed:
                    break

            if pending:
                await su.rollback()
                blocked = "; ".join(
                    (
                        f"{table_name} => "
                        f"{last_errors.get(table_name, 'blocked')}"
                    )
                    for table_name in sorted(
                        pending
                    )
                )
                return (
                    False,
                    (
                        "company-scoped cleanup blocked: "
                        + blocked
                    ),
                )

            result = await su.execute(
                text(
                    "DELETE FROM companies "
                    "WHERE id = :company_id"
                ),
                {
                    "company_id": int(
                        company_id
                    )
                },
            )
            if result.rowcount != 1:
                await su.rollback()
                return (
                    False,
                    (
                        "expected to delete exactly one "
                        f"test company, deleted={result.rowcount}"
                    ),
                )

            await su.commit()

        async with SessionSU() as su:
            await su.begin()
            remaining = int(
                (
                    await su.execute(
                        text(
                            "SELECT count(*) "
                            "FROM companies "
                            "WHERE id = :company_id"
                        ),
                        {
                            "company_id": int(
                                company_id
                            )
                        },
                    )
                ).scalar_one()
            )
            await su.rollback()

        if remaining != 0:
            return (
                False,
                (
                    "test company still exists after cleanup: "
                    f"company_id={company_id}"
                ),
            )

        return True, ""
    except Exception as exc:
        return (
            False,
            f"{type(exc).__name__}: {exc}",
        )


async def seed() -> dict[str, object]:
    shared_import_request = uuid4()

    async with SessionSU() as su:
        await su.begin()

        uom_id = (
            await su.execute(
                text(
                    "SELECT id FROM uom "
                    "ORDER BY id LIMIT 1"
                )
            )
        ).scalar_one_or_none()
        if uom_id is None:
            raise RuntimeError(
                "No UOM row exists; product tracking runtime gate "
                "cannot seed variants."
            )

        async def company(name: str) -> int:
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
                                "PTRK-"
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
                            "full_name, phone_number, is_active, "
                            "is_admin, created_at) "
                            "VALUES "
                            "(:company_id, :username, "
                            "'$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', "
                            ":name, :phone, true, true, NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "username": (
                                "ptrk_"
                                + uuid4().hex[:10]
                            ),
                            "name": name,
                            "phone": (
                                "+9627"
                                + uuid4().hex[:7]
                            ),
                        },
                    )
                ).scalar_one()
            )

        async def product(
            company_id: int,
            name: str,
        ) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            "INSERT INTO products "
                            "(company_id, code, name, "
                            "created_at, updated_at) "
                            "VALUES "
                            "(:company_id, :code, :name, "
                            "NOW(), NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "code": (
                                "PTRK-P-"
                                + uuid4().hex[:8]
                            ),
                            "name": name,
                        },
                    )
                ).scalar_one()
            )

        async def variant(
            company_id: int,
            product_id: int,
            name: str,
        ) -> int:
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
                            "created_at, updated_at) "
                            "VALUES "
                            "(:company_id, :product_id, :uom_id, "
                            ":name, :sku, 0, '1', "
                            "'REQUIRED', 'REQUIRED', "
                            "'ACTIVE', 'NONE', 1, 1, NOW(), "
                            "NOW(), NOW()) "
                            "RETURNING id"
                        ),
                        {
                            "company_id": company_id,
                            "product_id": product_id,
                            "uom_id": int(uom_id),
                            "name": name,
                            "sku": (
                                "PTRK-SKU-"
                                + uuid4().hex[:10]
                            ),
                        },
                    )
                ).scalar_one()
            )

        a = await company(
            "Product Tracking Runtime A"
        )
        b = await company(
            "Product Tracking Runtime B"
        )
        a_driver = await driver(
            a,
            "Tracking Admin A",
        )
        b_driver = await driver(
            b,
            "Tracking Admin B",
        )
        a_product = await product(
            a,
            "Tracking Product A",
        )
        b_product = await product(
            b,
            "Tracking Product B",
        )

        a_mutable = await variant(
            a,
            a_product,
            "A Mutable Legacy",
        )
        a_history = await variant(
            a,
            a_product,
            "A Historical Legacy",
        )
        a_concurrent = await variant(
            a,
            a_product,
            "A Concurrent",
        )
        b_foreign = await variant(
            b,
            b_product,
            "B Foreign",
        )

        await su.execute(
            text(
                "INSERT INTO product_batches "
                "(company_id, product_variant_id, "
                "batch_number, disposition, "
                "disposition_revision, is_active, "
                "created_at, updated_at) "
                "VALUES "
                "(:company_id, :variant_id, :batch, "
                "'RELEASED', 1, true, NOW(), NOW())"
            ),
            {
                "company_id": a,
                "variant_id": a_history,
                "batch": (
                    "PTRK-A-"
                    + uuid4().hex[:8]
                ),
            },
        )
        await su.execute(
            text(
                "INSERT INTO product_batches "
                "(company_id, product_variant_id, "
                "batch_number, disposition, "
                "disposition_revision, is_active, "
                "created_at, updated_at) "
                "VALUES "
                "(:company_id, :variant_id, :batch, "
                "'RELEASED', 1, true, NOW(), NOW())"
            ),
            {
                "company_id": b,
                "variant_id": b_foreign,
                "batch": (
                    "PTRK-B-"
                    + uuid4().hex[:8]
                ),
            },
        )

        await su.execute(
            text(
                "INSERT INTO system_settings "
                "(company_id, setting_key, "
                "setting_value, description) "
                "VALUES "
                "(:company_id, "
                "'product.default_lot_control_mode', "
                "'OPTIONAL', 'runtime gate'), "
                "(:company_id, "
                "'product.default_expiry_control_mode', "
                "'NONE', 'runtime gate')"
            ),
            {"company_id": b},
        )

        async def import_job(
            company_id: int,
            actor_id: int,
            lot_mode: str,
            expiry_mode: str,
        ) -> UUID:
            job_id = uuid4()
            await su.execute(
                text(
                    "INSERT INTO product_import_jobs "
                    "(id, company_id, request_id, created_by, "
                    "file_name, content_type, source_payload, "
                    "source_sha256, file_size, status, "
                    "detected_headers, suggested_mapping, "
                    "column_mapping, default_lot_control_mode, "
                    "default_expiry_control_mode, error_summary, "
                    "total_rows, processed_rows, valid_rows, "
                    "failed_rows, version, created_at, updated_at) "
                    "VALUES "
                    "(:id, :company_id, :request_id, :created_by, "
                    "'tracking.csv', 'text/csv', :payload, "
                    ":source_sha256, 1, 'QUEUED', "
                    "'[]'::jsonb, '{}'::jsonb, '{}'::jsonb, "
                    ":lot_mode, :expiry_mode, '{}'::jsonb, "
                    "0, 0, 0, 0, 1, NOW(), NOW())"
                ),
                {
                    "id": job_id,
                    "company_id": company_id,
                    "request_id": (
                        shared_import_request
                    ),
                    "created_by": actor_id,
                    "payload": b"x",
                    "source_sha256": (
                        hashlib.sha256(
                            b"x"
                        ).hexdigest()
                    ),
                    "lot_mode": lot_mode,
                    "expiry_mode": expiry_mode,
                },
            )
            return job_id

        a_import = await import_job(
            a,
            a_driver,
            "REQUIRED",
            "REQUIRED",
        )
        b_import = await import_job(
            b,
            b_driver,
            "OPTIONAL",
            "NONE",
        )

        await su.commit()

    return {
        "a": a,
        "b": b,
        "a_driver": a_driver,
        "b_driver": b_driver,
        "a_mutable": a_mutable,
        "a_history": a_history,
        "a_concurrent": a_concurrent,
        "b_foreign": b_foreign,
        "a_import": a_import,
        "b_import": b_import,
        "shared_import_request": (
            shared_import_request
        ),
    }


async def main() -> None:
    ids: dict[str, object] = {}

    try:
        ids = await seed()
        a = int(ids["a"])
        b = int(ids["b"])
        a_driver = int(ids["a_driver"])
        b_driver = int(ids["b_driver"])

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            own_variants = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM product_variants "
                            "WHERE company_id = :company_id"
                        ),
                        {"company_id": a},
                    )
                ).scalar_one()
            )
            foreign_variants = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM product_variants "
                            "WHERE company_id = :company_id"
                        ),
                        {"company_id": b},
                    )
                ).scalar_one()
            )
            foreign_settings = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM system_settings "
                            "WHERE company_id = :company_id"
                        ),
                        {"company_id": b},
                    )
                ).scalar_one()
            )
            foreign_batches = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM product_batches "
                            "WHERE company_id = :company_id"
                        ),
                        {"company_id": b},
                    )
                ).scalar_one()
            )
            foreign_imports = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM product_import_jobs "
                            "WHERE company_id = :company_id"
                        ),
                        {"company_id": b},
                    )
                ).scalar_one()
            )
            await app.rollback()

        record(
            "tracking RLS hides all foreign-company rows",
            own_variants == 3
            and foreign_variants == 0
            and foreign_settings == 0
            and foreign_batches == 0
            and foreign_imports == 0,
            (
                f"own={own_variants} "
                f"foreign_variants={foreign_variants} "
                f"foreign_settings={foreign_settings} "
                f"foreign_batches={foreign_batches} "
                f"foreign_imports={foreign_imports}"
            ),
        )

        cross_default_write_blocked = False
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await (
                    save_company_product_tracking_defaults_serialized(
                        app,
                        company_id=b,
                        lot_control_mode="NONE",
                        expiry_control_mode="NONE",
                    )
                )
                await app.flush()
            except Exception:
                cross_default_write_blocked = True
            finally:
                await app.rollback()
        record(
            "cross-company tracking default write is blocked",
            cross_default_write_blocked,
        )

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            before_defaults = (
                await load_company_product_tracking_defaults_state(
                    app,
                    company_id=a,
                )
            )
            await app.rollback()
        record(
            "tenant without saved defaults keeps fail-closed fallback",
            before_defaults.lot_control_mode
            == "REQUIRED"
            and before_defaults.expiry_control_mode
            == "REQUIRED"
            and before_defaults.lot_control_source
            == "PLATFORM_FALLBACK"
            and before_defaults.expiry_control_source
            == "PLATFORM_FALLBACK",
        )

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            saved_defaults = (
                await save_company_product_tracking_defaults_serialized(
                    app,
                    company_id=a,
                    lot_control_mode="NONE",
                    expiry_control_mode="OPTIONAL",
                )
            )
            inherited = await resolve_product_tracking_modes(
                app,
                company_id=a,
                lot_control_mode=None,
                expiry_control_mode=None,
            )
            partial_override = (
                await resolve_product_tracking_modes(
                    app,
                    company_id=a,
                    lot_control_mode="REQUIRED",
                    expiry_control_mode=None,
                )
            )
            legacy_row = (
                await app.execute(
                    text(
                        "SELECT lot_control_mode, "
                        "expiry_control_mode, version "
                        "FROM product_variants "
                        "WHERE company_id = :company_id "
                        "AND id = :variant_id"
                    ),
                    {
                        "company_id": a,
                        "variant_id": int(
                            ids["a_mutable"]
                        ),
                    },
                )
            ).one()
            import_snapshot = (
                await app.execute(
                    text(
                        "SELECT default_lot_control_mode, "
                        "default_expiry_control_mode "
                        "FROM product_import_jobs "
                        "WHERE company_id = :company_id "
                        "AND id = :job_id"
                    ),
                    {
                        "company_id": a,
                        "job_id": ids["a_import"],
                    },
                )
            ).one()
            await app.rollback()

        record(
            "tenant tracking defaults save explicitly",
            saved_defaults.lot_control_mode
            == "NONE"
            and saved_defaults.expiry_control_mode
            == "OPTIONAL"
            and saved_defaults.lot_control_source
            == "COMPANY"
            and saved_defaults.expiry_control_source
            == "COMPANY",
        )
        record(
            "manual/import tracking resolution shares one authority",
            inherited.lot_control_mode == "NONE"
            and inherited.expiry_control_mode
            == "OPTIONAL"
            and partial_override.lot_control_mode
            == "REQUIRED"
            and partial_override.expiry_control_mode
            == "OPTIONAL",
        )
        record(
            "company default changes never rewrite existing products",
            str(legacy_row.lot_control_mode)
            == "REQUIRED"
            and str(
                legacy_row.expiry_control_mode
            )
            == "REQUIRED"
            and int(legacy_row.version) == 1,
        )
        record(
            "company default changes never rewrite import snapshots",
            str(
                import_snapshot.default_lot_control_mode
            )
            == "REQUIRED"
            and str(
                import_snapshot.default_expiry_control_mode
            )
            == "REQUIRED",
        )

        async with SessionSU() as su:
            await su.begin()
            import_request_count = int(
                (
                    await su.execute(
                        text(
                            "SELECT count(*) "
                            "FROM product_import_jobs "
                            "WHERE request_id = :request_id"
                        ),
                        {
                            "request_id": ids[
                                "shared_import_request"
                            ]
                        },
                    )
                ).scalar_one()
            )
            await su.rollback()

        record(
            "import request identity remains tenant scoped",
            import_request_count == 2,
            f"same_request_rows={import_request_count}",
        )

        correction_request = uuid4()
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            correction = (
                await update_product_tracking_modes(
                    app,
                    company_id=a,
                    actor_id=a_driver,
                    request_id=correction_request,
                    product_variant_id=int(
                        ids["a_mutable"]
                    ),
                    expected_version=1,
                    lot_control_mode="NONE",
                    expiry_control_mode="OPTIONAL",
                )
            )
            await app.flush()
            audit_count = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM domain_audit_events "
                            "WHERE company_id = :company_id "
                            "AND request_id = :request_id "
                            "AND event_type = "
                            "'PRODUCT_TRACKING_UPDATED'"
                        ),
                        {
                            "company_id": a,
                            "request_id": (
                                correction_request
                            ),
                        },
                    )
                ).scalar_one()
            )
            outbox_count = int(
                (
                    await app.execute(
                        text(
                            "SELECT count(*) "
                            "FROM transactional_outbox "
                            "WHERE company_id = :company_id "
                            "AND event_type = "
                            "'PRODUCT_TRACKING_UPDATED' "
                            "AND payload ->> 'request_id' "
                            "= :request_id"
                        ),
                        {
                            "company_id": a,
                            "request_id": str(
                                correction_request
                            ),
                        },
                    )
                ).scalar_one()
            )
            await app.rollback()

        record(
            "history-free legacy product can be corrected explicitly",
            correction.changed
            and correction.version == 2
            and correction.lot_control_mode
            == "NONE"
            and correction.expiry_control_mode
            == "OPTIONAL",
        )
        record(
            "tracking correction emits transactional audit and outbox evidence",
            audit_count == 1
            and outbox_count == 1,
            (
                f"audit={audit_count} "
                f"outbox={outbox_count}"
            ),
        )

        history_blocked = False
        history_code = ""
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await update_product_tracking_modes(
                    app,
                    company_id=a,
                    actor_id=a_driver,
                    request_id=uuid4(),
                    product_variant_id=int(
                        ids["a_history"]
                    ),
                    expected_version=1,
                    lot_control_mode="NONE",
                    expiry_control_mode="NONE",
                )
            except ProductTrackingError as exc:
                history_blocked = True
                history_code = exc.code
            finally:
                await app.rollback()

        async with SessionSU() as su:
            await su.begin()
            history_row = (
                await su.execute(
                    text(
                        "SELECT lot_control_mode, "
                        "expiry_control_mode, version "
                        "FROM product_variants "
                        "WHERE id = :variant_id"
                    ),
                    {
                        "variant_id": int(
                            ids["a_history"]
                        )
                    },
                )
            ).one()
            await su.rollback()

        record(
            "batch history blocks normal tracking migration",
            history_blocked
            and history_code
            == "PRODUCT_TRACKING_LOCKED"
            and str(history_row.lot_control_mode)
            == "REQUIRED"
            and str(
                history_row.expiry_control_mode
            )
            == "REQUIRED"
            and int(history_row.version) == 1,
            f"code={history_code}",
        )

        cross_variant_blocked = False
        cross_variant_code = ""
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await update_product_tracking_modes(
                    app,
                    company_id=a,
                    actor_id=a_driver,
                    request_id=uuid4(),
                    product_variant_id=int(
                        ids["b_foreign"]
                    ),
                    expected_version=1,
                    lot_control_mode="NONE",
                    expiry_control_mode="NONE",
                )
            except ProductTrackingError as exc:
                cross_variant_blocked = True
                cross_variant_code = exc.code
            finally:
                await app.rollback()

        record(
            "cross-company product mutation fails closed",
            cross_variant_blocked
            and cross_variant_code
            == "PRODUCT_TRACKING_VARIANT_NOT_FOUND",
            f"code={cross_variant_code}",
        )

        # Runtime proof for the concurrency contract without committing
        # disposable audit evidence: the shared lifecycle guard must block a
        # competing exclusive edit, and stale optimistic versions must fail.
        guard_blocked_as_expected = False
        guard_detail = (
            "second exclusive guard unexpectedly acquired"
        )
        async with SessionApp() as first:
            await first.begin()
            await set_tenant(first, a)
            await acquire_product_lifecycle_guards(
                first,
                a,
                [int(ids["a_concurrent"])],
                exclusive=True,
            )

            async with SessionApp() as second:
                await second.begin()
                await set_tenant(second, a)
                await second.execute(
                    text(
                        "SET LOCAL lock_timeout = '250ms'"
                    )
                )
                try:
                    await acquire_product_lifecycle_guards(
                        second,
                        a,
                        [int(ids["a_concurrent"])],
                        exclusive=True,
                    )
                except DBAPIError as exc:
                    original = exc.orig
                    sqlstate = getattr(
                        original,
                        "sqlstate",
                        None,
                    )
                    if sqlstate is None:
                        cause = getattr(
                            original,
                            "__cause__",
                            None,
                        )
                        sqlstate = getattr(
                            cause,
                            "sqlstate",
                            None,
                        )

                    if sqlstate == "55P03":
                        guard_blocked_as_expected = True
                        guard_detail = (
                            "expected lock contention rejected "
                            "with SQLSTATE 55P03"
                        )
                    else:
                        guard_detail = (
                            "unexpected database error while "
                            "testing lifecycle serialization: "
                            f"sqlstate={sqlstate!r}, "
                            f"type={type(original).__name__}"
                        )
                except Exception as exc:
                    guard_detail = (
                        "unexpected non-database exception while "
                        "testing lifecycle serialization: "
                        f"{type(exc).__name__}: {exc}"
                    )
                finally:
                    await second.rollback()

            await first.rollback()

        record(
            "product lifecycle guard serializes concurrent tracking edits",
            guard_blocked_as_expected,
            guard_detail,
        )

        version_conflict = False
        version_conflict_code = ""
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            first_edit = (
                await update_product_tracking_modes(
                    app,
                    company_id=a,
                    actor_id=a_driver,
                    request_id=uuid4(),
                    product_variant_id=int(
                        ids["a_concurrent"]
                    ),
                    expected_version=1,
                    lot_control_mode="NONE",
                    expiry_control_mode="REQUIRED",
                )
            )
            try:
                await update_product_tracking_modes(
                    app,
                    company_id=a,
                    actor_id=a_driver,
                    request_id=uuid4(),
                    product_variant_id=int(
                        ids["a_concurrent"]
                    ),
                    expected_version=1,
                    lot_control_mode="OPTIONAL",
                    expiry_control_mode="NONE",
                )
            except ProductTrackingError as exc:
                version_conflict = True
                version_conflict_code = exc.code
            finally:
                await app.rollback()

        record(
            "stale tracking edit fails through optimistic version control",
            first_edit.changed
            and first_edit.version == 2
            and version_conflict
            and version_conflict_code
            == "PRODUCT_TRACKING_VERSION_CONFLICT",
            f"code={version_conflict_code}",
        )

        idem_request = uuid4()
        hash_a = hashlib.sha256(
            b"product-tracking-runtime-a"
        ).hexdigest()
        hash_b = hashlib.sha256(
            b"product-tracking-runtime-b"
        ).hexdigest()
        response = {
            "product_variant_id": int(
                ids["a_mutable"]
            ),
            "version": 2,
            "changed": True,
        }

        async with SessionSU() as su:
            await su.begin()
            idem_a, replay_a = (
                await begin_idempotent_operation(
                    su,
                    company_id=a,
                    actor_id=a_driver,
                    operation=(
                        "PRODUCT_TRACKING_UPDATE_V1"
                    ),
                    request_id=str(idem_request),
                    request_hash=hash_a,
                )
            )
            first_is_new = replay_a is None
            complete_idempotent_operation(
                idem_a,
                response,
            )
            await su.flush()

            _, replay = (
                await begin_idempotent_operation(
                    su,
                    company_id=a,
                    actor_id=a_driver,
                    operation=(
                        "PRODUCT_TRACKING_UPDATE_V1"
                    ),
                    request_id=str(idem_request),
                    request_hash=hash_a,
                )
            )

            changed_payload_blocked = False
            try:
                await begin_idempotent_operation(
                    su,
                    company_id=a,
                    actor_id=a_driver,
                    operation=(
                        "PRODUCT_TRACKING_UPDATE_V1"
                    ),
                    request_id=str(idem_request),
                    request_hash=hash_b,
                )
            except InventoryMutationError:
                changed_payload_blocked = True

            idem_b, replay_b = (
                await begin_idempotent_operation(
                    su,
                    company_id=b,
                    actor_id=b_driver,
                    operation=(
                        "PRODUCT_TRACKING_UPDATE_V1"
                    ),
                    request_id=str(idem_request),
                    request_hash=hash_a,
                )
            )
            b_is_new = replay_b is None
            complete_idempotent_operation(
                idem_b,
                {"tenant": "B"},
            )
            await su.flush()

            idem_count = int(
                (
                    await su.execute(
                        text(
                            "SELECT count(*) "
                            "FROM operation_idempotency "
                            "WHERE operation = "
                            "'PRODUCT_TRACKING_UPDATE_V1' "
                            "AND request_id = :request_id"
                        ),
                        {
                            "request_id": str(
                                idem_request
                            )
                        },
                    )
                ).scalar_one()
            )
            await su.rollback()

        record(
            "tracking mutation idempotency replays exact requests only",
            first_is_new
            and replay == response
            and changed_payload_blocked,
        )
        record(
            "idempotency identity is tenant scoped",
            b_is_new and idem_count == 2,
            f"same_request_rows={idem_count}",
        )

        variant_constraint_blocked = False
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await app.execute(
                    text(
                        "UPDATE product_variants "
                        "SET lot_control_mode = 'BROKEN' "
                        "WHERE company_id = :company_id "
                        "AND id = :variant_id"
                    ),
                    {
                        "company_id": a,
                        "variant_id": int(
                            ids["a_history"]
                        ),
                    },
                )
                await app.flush()
            except Exception:
                variant_constraint_blocked = True
            finally:
                await app.rollback()

        import_constraint_blocked = False
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            try:
                await app.execute(
                    text(
                        "UPDATE product_import_jobs "
                        "SET default_expiry_control_mode "
                        "= 'BROKEN' "
                        "WHERE company_id = :company_id "
                        "AND id = :job_id"
                    ),
                    {
                        "company_id": a,
                        "job_id": ids["a_import"],
                    },
                )
                await app.flush()
            except Exception:
                import_constraint_blocked = True
            finally:
                await app.rollback()

        record(
            "database rejects invalid tracking state at both boundaries",
            variant_constraint_blocked
            and import_constraint_blocked,
        )

    except Exception as exc:
        record(
            "runtime gate completed without unexpected exception",
            False,
            repr(exc),
        )
    finally:
        cleanup_results: list[
            tuple[bool, str]
        ] = []
        for key in ("a", "b"):
            value = ids.get(key)
            cleanup_results.append(
                await cleanup_company(
                    int(value)
                    if value is not None
                    else None
                )
            )
        cleanup_ok = all(
            ok for ok, _ in cleanup_results
        )
        cleanup_detail = "; ".join(
            detail
            for ok, detail in cleanup_results
            if not ok
        )
        record(
            "runtime gate removes all seeded tenant data",
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
            "PRODUCT_TRACKING_RUNTIME_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        "PRODUCT_TRACKING_RUNTIME_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
