from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        failures.append(label)


def static_checks() -> None:
    from domains.product_tracking import (
        INTERNAL_NO_LOT_PREFIX,
        ProductTrackingError,
        build_internal_no_lot_batch_number,
        normalize_tracking_mode,
    )

    check(
        normalize_tracking_mode(
            " required ",
            field_name="lot_control_mode",
        )
        == "REQUIRED",
        "Tracking mode normalization is canonical",
    )

    try:
        normalize_tracking_mode(
            "INVALID",
            field_name="lot_control_mode",
        )
        invalid_mode_rejected = False
    except ProductTrackingError:
        invalid_mode_rejected = True
    check(
        invalid_mode_rejected,
        "Invalid tracking modes fail closed",
    )

    no_lot = build_internal_no_lot_batch_number(
        production_date=None,
        expiry_date=None,
    )
    expiring = build_internal_no_lot_batch_number(
        production_date=None,
        expiry_date=date(2030, 1, 2),
    )
    check(
        no_lot.startswith(INTERNAL_NO_LOT_PREFIX)
        and no_lot != expiring
        and len(no_lot) <= 100
        and len(expiring) <= 100,
        "Internal non-lot identity is reserved, bounded and metadata-sensitive",
    )

    try:
        build_internal_no_lot_batch_number(
            production_date=datetime.now(),
            expiry_date=None,
        )
        datetime_rejected = False
    except ProductTrackingError:
        datetime_rejected = True
    check(
        datetime_rejected,
        "Internal batch identity rejects datetime in place of date",
    )

    tracking = (
        BACKEND / "domains/product_tracking.py"
    ).read_text(encoding="utf-8")
    simple_service = (
        BACKEND / "domains/simple_products/service.py"
    ).read_text(encoding="utf-8")
    simple_api = (
        BACKEND / "api/simple_products.py"
    ).read_text(encoding="utf-8")
    tracking_api = (
        BACKEND / "api/product_tracking.py"
    ).read_text(encoding="utf-8")
    main_py = (
        BACKEND / "main.py"
    ).read_text(encoding="utf-8")

    check(
        'lot_control_mode="REQUIRED"' not in simple_service
        and 'expiry_control_mode="REQUIRED"' not in simple_service
        and "resolve_product_tracking_modes(" in simple_service,
        "Simple creation no longer hardcodes REQUIRED tracking modes",
    )
    check(
        "lot_control_mode: str | None" in simple_api
        and "expiry_control_mode: str | None" in simple_api
        and "lot_control_mode=payload.lot_control_mode" in simple_api
        and "expiry_control_mode=payload.expiry_control_mode" in simple_api,
        "Simple create contract accepts explicit tracking modes",
    )
    check(
        '"version": int(variant.version)' in simple_api
        and '"lot_control_mode": str(' in simple_api
        and '"expiry_control_mode": str(' in simple_api,
        "Simple product reads expose versioned tracking state",
    )

    check(
        "SystemSetting.company_id == company_id" in tracking
        and "PRODUCT_DEFAULT_LOT_CONTROL_MODE_KEY" in tracking
        and "PRODUCT_DEFAULT_EXPIRY_CONTROL_MODE_KEY" in tracking,
        "Company defaults are tenant scoped",
    )
    check(
        "pg_advisory_xact_lock" in tracking
        and '"product-tracking-defaults"' in tracking,
        "Company default updates are serialized per tenant",
    )

    check(
        "acquire_product_lifecycle_guards(" in tracking
        and "exclusive=True" in tracking
        and "ProductVariant.company_id == company_id" in tracking
        and "ProductVariant.id == product_variant_id" in tracking
        and ".with_for_update()" in tracking,
        "Tracking mutation serializes against inbound and locks the tenant product row",
    )
    check(
        "ProductBatch.company_id == company_id" in tracking
        and "ProductBatch.product_variant_id" in tracking
        and '"PRODUCT_TRACKING_LOCKED"' in tracking,
        "Batch history blocks unsafe tracking edits",
    )
    check(
        '"PRODUCT_TRACKING_VERSION_CONFLICT"' in tracking
        and "int(variant.version) != expected_version" in tracking
        and "variant.version = int(variant.version) + 1" in tracking,
        "Tracking updates use optimistic version control",
    )
    check(
        '"DRAFT"' in tracking
        and '"ACTIVE"' in tracking
        and '"PRODUCT_TRACKING_LIFECYCLE_BLOCKED"' in tracking,
        "Retiring/archived products are blocked from normal tracking edits",
    )
    check(
        'event_type="PRODUCT_TRACKING_UPDATED"' in tracking
        and "record_domain_event(" in tracking,
        "Tracking changes emit structured domain audit evidence",
    )

    check(
        'prefix="/simple-products/tracking"' in tracking_api
        and '@router.get("/defaults")' in tracking_api
        and '@router.put("/defaults")' in tracking_api
        and '@router.patch("/variants/{variant_id}")'
        in tracking_api,
        "Product tracking API exposes defaults and variant mutation contracts",
    )
    check(
        '"catalog.read"' in tracking_api
        and tracking_api.count('"catalog.manage"') >= 2,
        "Product tracking API enforces catalog read/manage permissions",
    )
    check(
        "begin_idempotent_operation(" in tracking_api
        and "complete_idempotent_operation(" in tracking_api
        and '"PRODUCT_TRACKING_DEFAULTS_UPDATE_V1"' in tracking_api
        and '"PRODUCT_TRACKING_UPDATE_V1"' in tracking_api,
        "Tracking mutations are idempotent",
    )
    check(
        "SystemAuditLog(" in tracking_api
        and "before=dict(result.before_snapshot)" in tracking_api
        and "after=dict(result.after_snapshot)" in tracking_api,
        "Tracking configuration records exact before/after audit snapshots",
    )
    check(
        "product_tracking" in main_py
        and "app.include_router(product_tracking.router)" in main_py,
        "Product tracking router is registered",
    )


async def database_checks() -> None:
    from database import engine

    async with engine.connect() as conn:
        constraint_count = await conn.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'uq_company_setting_key'
                """
            )
        )
        check(
            int(constraint_count or 0) == 1,
            "SystemSetting keeps company+key uniqueness",
        )

        for table_name in (
            "system_settings",
            "product_variants",
            "product_batches",
        ):
            rls = (
                await conn.execute(
                    text(
                        """
                        SELECT relrowsecurity, relforcerowsecurity
                        FROM pg_class
                        WHERE relname = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            ).one_or_none()
            check(
                rls is not None
                and bool(rls.relrowsecurity)
                and bool(rls.relforcerowsecurity),
                f"{table_name} keeps ENABLE + FORCE RLS",
            )

            policies = (
                await conn.execute(
                    text(
                        """
                        SELECT qual, with_check
                        FROM pg_policies
                        WHERE schemaname = current_schema()
                          AND tablename = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            ).all()
            check(
                any(
                    "app.current_tenant" in str(row.qual or "")
                    and "company_id" in str(row.qual or "")
                    and "app.current_tenant"
                    in str(row.with_check or "")
                    and "company_id"
                    in str(row.with_check or "")
                    for row in policies
                ),
                f"{table_name} RLS enforces tenant USING + WITH CHECK",
            )

    await engine.dispose()


def main() -> int:
    try:
        static_checks()
        asyncio.run(database_checks())
    except Exception as exc:
        check(False, "Gate completed without unexpected exception")
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("PRODUCT_TRACKING_AUTHORITY_GATE=FAIL")
        return 1

    print("PRODUCT_TRACKING_AUTHORITY_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
