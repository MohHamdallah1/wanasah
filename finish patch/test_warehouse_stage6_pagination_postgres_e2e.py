from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url


def locate_project() -> tuple[Path, Path]:
    cwd = Path.cwd().resolve()
    here = Path(__file__).resolve().parent

    for root in (cwd, here, cwd.parent, here.parent):
        backend = root / "wa_backend"
        if backend.is_dir() and (backend / "models.py").is_file():
            return root, backend
        if root.name == "wa_backend" and (root / "models.py").is_file():
            return root.parent, root

    raise SystemExit(
        "ERROR: لم أجد wa_backend/models.py. "
        "ضع السكربت في جذر المشروع وشغله من هناك."
    )


ROOT, BACKEND = locate_project()
sys.path.insert(0, str(BACKEND))

from config import Config  # noqa: E402
from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import (  # noqa: E402
    Base,
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryStockPolicy,
    Product,
    ProductBatch,
    ProductVariant,
    UOM,
)
from schemas import ProductVariantResolveRequest  # noqa: E402
from api.warehouse import (  # noqa: E402
    get_simple_product_variants,
    get_warehouse_inventory,
    resolve_simple_product_variants,
)


# ---------------------------------------------------------------------------
# Safety gate: هذا اختبار يكتب Fixtures مؤقتة وينظفها. لا يعمل على DB بعيدة
# إلا بطلب صريح، حتى لا يتم تشغيله بالخطأ على Production.
# ---------------------------------------------------------------------------
db_url = make_url(Config.SQLALCHEMY_DATABASE_URI)
host = (db_url.host or "").lower()
if host not in {"localhost", "127.0.0.1", "::1"}:
    if os.getenv("WANASAH_ALLOW_REMOTE_TEST_DB") != "YES":
        raise SystemExit(
            "REFUSED: DATABASE_URL ليست قاعدة محلية. "
            "هذا الاختبار يكتب بيانات اختبار مؤقتة. "
            "إذا كانت قاعدة اختبار بعيدة مقصودة، اضبط "
            "WANASAH_ALLOW_REMOTE_TEST_DB=YES صراحةً."
        )


@dataclass
class QueryCounter:
    active: bool = False
    count: int = 0


QUERY_COUNTER = QueryCounter()


def _before_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    if QUERY_COUNTER.active:
        QUERY_COUNTER.count += 1


event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)


async def counted(awaitable):
    QUERY_COUNTER.count = 0
    QUERY_COUNTER.active = True
    try:
        result = await awaitable
    finally:
        QUERY_COUNTER.active = False
    return result, QUERY_COUNTER.count


async def set_tenant(db, company_id: int | None) -> None:
    tenant_context.set(company_id)
    value = "" if company_id is None else str(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": value},
    )


async def current_runtime_role(db) -> tuple[str, bool, bool]:
    row = (
        await db.execute(
            text(
                """
                SELECT r.rolname, r.rolsuper, r.rolbypassrls
                FROM pg_roles AS r
                WHERE r.rolname = current_user
                """
            )
        )
    ).one()
    return str(row[0]), bool(row[1]), bool(row[2])


async def ensure_schema_and_rls_ready() -> str:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)

        role, is_superuser, bypass_rls = await current_runtime_role(db)
        if is_superuser or bypass_rls:
            raise AssertionError(
                "INVALID_RLS_TEST_ROLE: runtime DATABASE_URL يستخدم role "
                f"{role!r} مع superuser={is_superuser}, "
                f"bypassrls={bypass_rls}. "
                "لن نعتبر اختبار العزل صالحاً بهذه الصلاحيات."
            )

        tenant_tables = sorted(
            table_name
            for table_name, table in Base.metadata.tables.items()
            if "company_id" in table.columns
        )

        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        cls.relname AS table_name,
                        cls.relrowsecurity AS rls_enabled,
                        cls.relforcerowsecurity AS rls_forced
                    FROM pg_class AS cls
                    JOIN pg_namespace AS ns
                      ON ns.oid = cls.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND cls.relkind = 'r'
                    """
                )
            )
        ).all()
        flags = {
            str(name): (bool(enabled), bool(forced))
            for name, enabled, forced in rows
        }

        missing_or_weak = {
            table_name: flags.get(table_name)
            for table_name in tenant_tables
            if flags.get(table_name) != (True, True)
        }
        if missing_or_weak:
            raise AssertionError(
                f"RLS/FORCE missing on tenant tables: {missing_or_weak}"
            )

        policy_rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        tablename,
                        policyname,
                        cmd,
                        qual,
                        with_check
                    FROM pg_policies
                    WHERE schemaname = current_schema()
                    """
                )
            )
        ).all()

        policies = {}
        for table_name, policy_name, cmd, qual, with_check in policy_rows:
            if policy_name == "tenant_isolation_policy":
                policies[str(table_name)] = (
                    str(cmd),
                    str(qual or ""),
                    str(with_check or ""),
                )

        bad_policies = {}
        for table_name in tenant_tables:
            policy = policies.get(table_name)
            if policy is None:
                bad_policies[table_name] = "MISSING"
                continue

            cmd, qual, with_check = policy
            merged = f"{qual} {with_check}".lower()
            if (
                cmd.upper() != "ALL"
                or "company_id" not in merged
                or "app.current_tenant" not in merged
                or not with_check
            ):
                bad_policies[table_name] = policy

        if bad_policies:
            raise AssertionError(
                f"Tenant policies are incomplete: {bad_policies}"
            )

        idx = (
            await db.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'product_variants'
                      AND indexname = 'ix_product_variant_company_name_id'
                    """
                )
            )
        ).scalar_one_or_none()

        if idx is None:
            raise AssertionError(
                "ix_product_variant_company_name_id missing"
            )

        idx_upper = str(idx).upper()
        for token in ("COMPANY_ID", "VARIANT_NAME", "ID"):
            if token not in idx_upper:
                raise AssertionError(
                    f"Bad ProductVariant cursor index: {idx}"
                )

        return role


async def ensure_uom(db, suffix: str) -> int:
    await set_tenant(db, None)
    uom = UOM(
        name=f"Stage6 Pack {suffix}",
        code=f"S6{suffix[:8].upper()}",
    )
    db.add(uom)
    await db.flush()
    return int(uom.id)


async def create_variant(
    db,
    *,
    company_id: int,
    product_id: int,
    uom_id: int,
    name: str,
    sku: str,
    active: bool = True,
) -> ProductVariant:
    variant = ProductVariant(
        company_id=company_id,
        product_id=product_id,
        base_uom_id=uom_id,
        variant_name=name,
        sku=sku,
        packs_per_carton=50,
        price_per_carton=Decimal("10.000"),
        price_per_pack=Decimal("0.200"),
        is_active=active,
        default_max_samples_per_day=0,
    )
    db.add(variant)
    return variant


async def create_batch_balance(
    db,
    *,
    company_id: int,
    location_id: int,
    variant_id: int,
    batch_number: str,
    expiry_date: date,
    on_hand: int,
    reserved: int = 0,
    batch_active: bool = True,
) -> tuple[int, int]:
    batch = ProductBatch(
        company_id=company_id,
        product_variant_id=variant_id,
        batch_number=batch_number,
        production_date=date.today() - timedelta(days=30),
        expiry_date=expiry_date,
        is_active=batch_active,
    )
    db.add(batch)
    await db.flush()

    balance = InventoryBalance(
        company_id=company_id,
        location_id=location_id,
        product_variant_id=variant_id,
        batch_id=batch.id,
        stock_status="AVAILABLE",
        on_hand_quantity=on_hand,
        reserved_quantity=reserved,
    )
    db.add(balance)
    await db.flush()
    return int(batch.id), int(balance.id)


async def setup_fixture():
    suffix = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        # Global entities first.
        await set_tenant(db, None)
        c1 = Company(
            name=f"Stage6 Tenant A {suffix}",
            company_code=f"S6A{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        c2 = Company(
            name=f"Stage6 Tenant B {suffix}",
            company_code=f"S6B{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        db.add_all([c1, c2])
        await db.flush()

        uom_id = await ensure_uom(db, suffix)

        # ---------------- Tenant A ----------------
        await set_tenant(db, c1.id)

        admin_a = Driver(
            company_id=c1.id,
            username=f"s6_admin_a_{suffix}",
            password_hash="test-only",
            full_name="Stage6 Admin A",
            is_active=True,
            is_admin=True,
        )
        product_a = Product(
            company_id=c1.id,
            base_name=f"Stage6 Product A {suffix}",
            brand="Stage6",
            category="TEST",
        )
        warehouse_a = InventoryLocation(
            company_id=c1.id,
            name=f"Stage6 Warehouse A {suffix}",
            code=f"S6WA{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([admin_a, product_a, warehouse_a])
        await db.flush()

        active_variants_a: list[ProductVariant] = []
        all_variants_a: list[ProductVariant] = []

        # 125 active products; duplicate names intentionally test (name, id) tie-break.
        for i in range(125):
            variant = await create_variant(
                db,
                company_id=c1.id,
                product_id=product_a.id,
                uom_id=uom_id,
                name=f"Bulk Item {i // 2:03d}",
                sku=f"S6A-BULK-{suffix}-{i:03d}",
                active=True,
            )
            active_variants_a.append(variant)
            all_variants_a.append(variant)

        # Special semantics products.
        special_specs = [
            ("alert", "ZZ Alert", True),
            ("nonalert", "ZZ NonAlert", True),
            ("expired", "ZZ Expired", True),
            ("reserved", "ZZ Reserved", True),
            ("active_empty", "ZZ Active Empty", True),
            ("inactive_stock", "ZZ Inactive Stock", False),
            ("inactive_empty", "ZZ Inactive Empty", False),
        ]
        special = {}
        for key, name, active in special_specs:
            variant = await create_variant(
                db,
                company_id=c1.id,
                product_id=product_a.id,
                uom_id=uom_id,
                name=name,
                sku=f"S6A-{key.upper()}-{suffix}",
                active=active,
            )
            special[key] = variant
            all_variants_a.append(variant)
            if active:
                active_variants_a.append(variant)

        await db.flush()

        future = date.today() + timedelta(days=180)
        past = date.today() - timedelta(days=1)

        _, alert_balance = await create_batch_balance(
            db,
            company_id=c1.id,
            location_id=warehouse_a.id,
            variant_id=special["alert"].id,
            batch_number=f"A-ALERT-{suffix}",
            expiry_date=future,
            on_hand=4,
        )
        _, nonalert_balance = await create_batch_balance(
            db,
            company_id=c1.id,
            location_id=warehouse_a.id,
            variant_id=special["nonalert"].id,
            batch_number=f"A-NONALERT-{suffix}",
            expiry_date=future,
            on_hand=8,
        )
        _, expired_balance = await create_batch_balance(
            db,
            company_id=c1.id,
            location_id=warehouse_a.id,
            variant_id=special["expired"].id,
            batch_number=f"A-EXPIRED-{suffix}",
            expiry_date=past,
            on_hand=100,
        )
        _, reserved_balance = await create_batch_balance(
            db,
            company_id=c1.id,
            location_id=warehouse_a.id,
            variant_id=special["reserved"].id,
            batch_number=f"A-RESERVED-{suffix}",
            expiry_date=future,
            on_hand=10,
            reserved=6,
        )
        _, inactive_balance = await create_batch_balance(
            db,
            company_id=c1.id,
            location_id=warehouse_a.id,
            variant_id=special["inactive_stock"].id,
            batch_number=f"A-INACTIVE-{suffix}",
            expiry_date=future,
            on_hand=7,
        )

        for key in ("alert", "nonalert", "expired", "reserved"):
            db.add(
                InventoryStockPolicy(
                    company_id=c1.id,
                    location_id=warehouse_a.id,
                    product_variant_id=special[key].id,
                    minimum_quantity=5,
                    target_quantity=20,
                    is_active=True,
                )
            )

        await db.commit()

        # ---------------- Tenant B ----------------
        await set_tenant(db, c2.id)

        admin_b = Driver(
            company_id=c2.id,
            username=f"s6_admin_b_{suffix}",
            password_hash="test-only",
            full_name="Stage6 Admin B",
            is_active=True,
            is_admin=True,
        )
        product_b = Product(
            company_id=c2.id,
            base_name=f"Stage6 Product B {suffix}",
            brand="Stage6",
            category="TEST",
        )
        warehouse_b = InventoryLocation(
            company_id=c2.id,
            name=f"Stage6 Warehouse B {suffix}",
            code=f"S6WB{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([admin_b, product_b, warehouse_b])
        await db.flush()

        secret_b = await create_variant(
            db,
            company_id=c2.id,
            product_id=product_b.id,
            uom_id=uom_id,
            name=f"TENANT-B-SECRET-{suffix}",
            sku=f"S6B-SECRET-{suffix}",
            active=True,
        )
        extra_b = await create_variant(
            db,
            company_id=c2.id,
            product_id=product_b.id,
            uom_id=uom_id,
            name=f"TENANT-B-EXTRA-{suffix}",
            sku=f"S6B-EXTRA-{suffix}",
            active=True,
        )
        await db.flush()

        _, secret_balance_b = await create_batch_balance(
            db,
            company_id=c2.id,
            location_id=warehouse_b.id,
            variant_id=secret_b.id,
            batch_number=f"B-SECRET-{suffix}",
            expiry_date=future,
            on_hand=99,
        )

        db.add(
            InventoryStockPolicy(
                company_id=c2.id,
                location_id=warehouse_b.id,
                product_variant_id=secret_b.id,
                minimum_quantity=200,
                target_quantity=300,
                is_active=True,
            )
        )

        await db.commit()

        active_expected = sorted(
            [(str(v.variant_name), int(v.id)) for v in active_variants_a],
            key=lambda x: (x[0], x[1]),
        )
        inventory_expected = sorted(
            active_expected
            + [
                (
                    str(special["inactive_stock"].variant_name),
                    int(special["inactive_stock"].id),
                )
            ],
            key=lambda x: (x[0], x[1]),
        )

        return {
            "suffix": suffix,
            "uom_id": uom_id,
            "c1": int(c1.id),
            "c2": int(c2.id),
            "admin_a": int(admin_a.id),
            "admin_b": int(admin_b.id),
            "warehouse_a": int(warehouse_a.id),
            "warehouse_b": int(warehouse_b.id),
            "active_expected": active_expected,
            "inventory_expected": inventory_expected,
            "bulk_ids": {
                int(v.id)
                for v in active_variants_a
                if str(v.variant_name).startswith("Bulk Item ")
            },
            "special": {
                key: int(value.id)
                for key, value in special.items()
            },
            "secret_b": int(secret_b.id),
            "secret_b_name": str(secret_b.variant_name),
            "secret_balance_b": int(secret_balance_b),
            "inactive_balance_a": int(inactive_balance),
            "alert_balance_a": int(alert_balance),
            "nonalert_balance_a": int(nonalert_balance),
            "expired_balance_a": int(expired_balance),
            "reserved_balance_a": int(reserved_balance),
        }


async def load_admin(db, company_id: int, admin_id: int) -> Driver:
    await set_tenant(db, company_id)
    return (
        await db.execute(
            select(Driver).where(
                Driver.company_id == company_id,
                Driver.id == admin_id,
            )
        )
    ).scalar_one()


async def expect_http_status(awaitable, expected_status: int) -> None:
    try:
        await awaitable
    except HTTPException as exc:
        if exc.status_code != expected_status:
            raise AssertionError(
                f"Expected HTTP {expected_status}, got {exc.status_code}: {exc.detail}"
            )
        return
    raise AssertionError(
        f"Expected HTTP {expected_status}, but call unexpectedly succeeded."
    )


async def catalog_page(
    db,
    admin,
    *,
    cursor=None,
    limit=50,
    search=None,
):
    return await get_simple_product_variants(
        cursor=cursor,
        limit=limit,
        search=search,
        db=db,
        current_admin=admin,
    )


async def inventory_page(
    db,
    admin,
    *,
    location_id,
    cursor=None,
    limit=50,
    search=None,
    only_alerts=False,
):
    return await get_warehouse_inventory(
        location_id=location_id,
        cursor=cursor,
        limit=limit,
        search=search,
        only_alerts=only_alerts,
        db=db,
        current_admin=admin,
    )


async def test_catalog_pagination(fx) -> None:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx["c1"], fx["admin_a"])

        seen: list[int] = []
        cursor = None
        first = True

        while True:
            page = await catalog_page(
                db,
                admin,
                cursor=cursor,
                limit=17,
            )
            ids = [int(item["id"]) for item in page["items"]]

            if first:
                if page["total"] != len(fx["active_expected"]):
                    raise AssertionError(
                        f"Catalog total mismatch: {page['total']} "
                        f"!= {len(fx['active_expected'])}"
                    )
                first = False
            elif page["total"] is not None:
                raise AssertionError(
                    "Catalog total must only be returned on the first cursor page."
                )

            seen.extend(ids)

            if not page["has_more"]:
                if page["next_cursor"] is not None:
                    raise AssertionError(
                        "Catalog final page unexpectedly returned next_cursor."
                    )
                break

            cursor = page["next_cursor"]
            if not cursor:
                raise AssertionError(
                    "Catalog has_more=True without next_cursor."
                )

        expected_ids = [item_id for _, item_id in fx["active_expected"]]

        if len(seen) != len(set(seen)):
            raise AssertionError("Catalog cursor duplicated rows.")

        if seen != expected_ids:
            missing = sorted(set(expected_ids) - set(seen))
            extra = sorted(set(seen) - set(expected_ids))
            raise AssertionError(
                f"Catalog cursor skip/order mismatch. missing={missing}, extra={extra}"
            )

        if fx["special"]["inactive_stock"] in seen:
            raise AssertionError(
                "Inactive variant leaked into active inbound catalog."
            )

        if fx["special"]["inactive_empty"] in seen:
            raise AssertionError(
                "Inactive empty variant leaked into active inbound catalog."
            )


async def test_inventory_pagination(fx) -> None:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx["c1"], fx["admin_a"])

        seen: list[int] = []
        cursor = None
        first = True

        while True:
            page = await inventory_page(
                db,
                admin,
                location_id=fx["warehouse_a"],
                cursor=cursor,
                limit=19,
            )
            ids = [int(item["id"]) for item in page["items"]]

            if first:
                if page["total"] != len(fx["inventory_expected"]):
                    raise AssertionError(
                        f"Inventory total mismatch: {page['total']} "
                        f"!= {len(fx['inventory_expected'])}"
                    )
                first = False
            elif page["total"] is not None:
                raise AssertionError(
                    "Inventory total must only be returned on first page."
                )

            seen.extend(ids)

            if not page["has_more"]:
                if page["next_cursor"] is not None:
                    raise AssertionError(
                        "Inventory final page unexpectedly returned next_cursor."
                    )
                break

            cursor = page["next_cursor"]
            if not cursor:
                raise AssertionError(
                    "Inventory has_more=True without next_cursor."
                )

        expected_ids = [item_id for _, item_id in fx["inventory_expected"]]

        if len(seen) != len(set(seen)):
            raise AssertionError("Inventory cursor duplicated rows.")

        if seen != expected_ids:
            missing = sorted(set(expected_ids) - set(seen))
            extra = sorted(set(seen) - set(expected_ids))
            raise AssertionError(
                f"Inventory cursor skip/order mismatch. "
                f"missing={missing}, extra={extra}"
            )

        if fx["special"]["inactive_stock"] not in seen:
            raise AssertionError(
                "Inactive variant with physical stock disappeared from live inventory."
            )

        if fx["special"]["inactive_empty"] in seen:
            raise AssertionError(
                "Inactive zero-stock variant should not pollute live inventory."
            )


async def test_inventory_semantics_and_alerts(fx) -> None:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx["c1"], fx["admin_a"])

        first_page = await inventory_page(
            db,
            admin,
            location_id=fx["warehouse_a"],
            limit=25,
        )

        expected_alert_ids = {
            fx["special"]["alert"],
            fx["special"]["expired"],
            fx["special"]["reserved"],
        }

        if int(first_page["alert_count"] or 0) != len(expected_alert_ids):
            raise AssertionError(
                f"Alert count mismatch: {first_page['alert_count']} "
                f"!= {len(expected_alert_ids)}"
            )

        alert_page = await inventory_page(
            db,
            admin,
            location_id=fx["warehouse_a"],
            limit=50,
            only_alerts=True,
        )
        actual_alert_ids = {
            int(item["id"]) for item in alert_page["items"]
        }

        if actual_alert_ids != expected_alert_ids:
            raise AssertionError(
                f"Alert semantics mismatch: {actual_alert_ids} "
                f"!= {expected_alert_ids}"
            )

        expired_page = await inventory_page(
            db,
            admin,
            location_id=fx["warehouse_a"],
            limit=10,
            search="zz expired",
        )
        if len(expired_page["items"]) != 1:
            raise AssertionError(
                f"Expected one expired product, got {expired_page['items']}"
            )
        expired = expired_page["items"][0]
        if (
            int(expired["available_packs"]) != 0
            or int(expired["blocked_packs"]) != 100
            or int(expired["total_packs"]) != 100
        ):
            raise AssertionError(
                f"Expired stock semantics incorrect: {expired}"
            )

        inactive_page = await inventory_page(
            db,
            admin,
            location_id=fx["warehouse_a"],
            limit=10,
            search="zz inactive stock",
        )
        if len(inactive_page["items"]) != 1:
            raise AssertionError(
                f"Expected one inactive-stock product, got {inactive_page['items']}"
            )
        inactive = inactive_page["items"][0]
        if (
            int(inactive["available_packs"]) != 0
            or int(inactive["blocked_packs"]) != 7
            or int(inactive["total_packs"]) != 7
        ):
            raise AssertionError(
                f"Inactive physical stock semantics incorrect: {inactive}"
            )

        nonalert_page = await inventory_page(
            db,
            admin,
            location_id=fx["warehouse_a"],
            limit=10,
            search="zz nonalert",
        )
        if len(nonalert_page["items"]) != 1:
            raise AssertionError(
                f"Expected one non-alert product, got {nonalert_page['items']}"
            )
        nonalert = nonalert_page["items"][0]
        if int(nonalert["available_packs"]) != 8:
            raise AssertionError(
                f"Sellable available stock incorrect: {nonalert}"
            )

        reserved_page = await inventory_page(
            db,
            admin,
            location_id=fx["warehouse_a"],
            limit=10,
            search="zz reserved",
        )
        reserved = reserved_page["items"][0]
        if (
            int(reserved["available_packs"]) != 4
            or int(reserved["reserved_packs"]) != 6
            or int(reserved["blocked_packs"]) != 0
        ):
            raise AssertionError(
                f"Reserved/free stock semantics incorrect: {reserved}"
            )


async def test_tenant_api_isolation(fx) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        admin_a = await load_admin(db, fx["c1"], fx["admin_a"])

        # A cannot address B warehouse by ID.
        await expect_http_status(
            inventory_page(
                db,
                admin_a,
                location_id=fx["warehouse_b"],
                limit=10,
            ),
            404,
        )

        # A cannot discover B secret by search.
        catalog_secret = await catalog_page(
            db,
            admin_a,
            limit=10,
            search=fx["secret_b_name"].lower(),
        )
        if catalog_secret["items"] or catalog_secret["total"] != 0:
            raise AssertionError(
                f"Tenant B product leaked through catalog search: {catalog_secret}"
            )

        inventory_secret = await inventory_page(
            db,
            admin_a,
            location_id=fx["warehouse_a"],
            limit=10,
            search=fx["secret_b_name"].lower(),
        )
        if inventory_secret["items"] or inventory_secret["total"] != 0:
            raise AssertionError(
                f"Tenant B product leaked through inventory search: {inventory_secret}"
            )

        # Resolve endpoint must silently resolve only IDs owned by A.
        resolved = await resolve_simple_product_variants(
            payload=ProductVariantResolveRequest(
                ids=[fx["special"]["alert"], fx["secret_b"]]
            ),
            db=db,
            current_admin=admin_a,
        )
        resolved_ids = {int(item["id"]) for item in resolved}
        if resolved_ids != {fx["special"]["alert"]}:
            raise AssertionError(
                f"Cross-tenant ID leaked through resolve: {resolved_ids}"
            )

        # Create A cursors.
        a_catalog_first = await catalog_page(
            db,
            admin_a,
            limit=2,
            search="bulk",
        )
        a_catalog_cursor = a_catalog_first["next_cursor"]
        if not a_catalog_cursor:
            raise AssertionError("Expected catalog cursor for tenant A.")

        a_inventory_first = await inventory_page(
            db,
            admin_a,
            location_id=fx["warehouse_a"],
            limit=2,
            search="bulk",
        )
        a_inventory_cursor = a_inventory_first["next_cursor"]
        if not a_inventory_cursor:
            raise AssertionError("Expected inventory cursor for tenant A.")

        # Same tenant but changed search scope must reject cursor.
        await expect_http_status(
            catalog_page(
                db,
                admin_a,
                cursor=a_catalog_cursor,
                limit=2,
                search="zz",
            ),
            400,
        )
        await expect_http_status(
            inventory_page(
                db,
                admin_a,
                location_id=fx["warehouse_a"],
                cursor=a_inventory_cursor,
                limit=2,
                search="zz",
            ),
            400,
        )

        # Switch to tenant B and reuse A cursors: must reject.
        admin_b = await load_admin(db, fx["c2"], fx["admin_b"])

        await expect_http_status(
            catalog_page(
                db,
                admin_b,
                cursor=a_catalog_cursor,
                limit=2,
                search="bulk",
            ),
            400,
        )
        await expect_http_status(
            inventory_page(
                db,
                admin_b,
                location_id=fx["warehouse_b"],
                cursor=a_inventory_cursor,
                limit=2,
                search="bulk",
            ),
            400,
        )

        return a_catalog_cursor, a_inventory_cursor


async def test_rls_cross_tenant_read_write_block(fx) -> None:
    # The important part: these are raw SQL attempts through runtime DATABASE_URL.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["c1"])

        role, is_superuser, bypass_rls = await current_runtime_role(db)
        if is_superuser or bypass_rls:
            raise AssertionError(
                f"RLS test invalid: role={role}, "
                f"superuser={is_superuser}, bypassrls={bypass_rls}"
            )

        # Raw SELECT cannot see B even with a known malicious ID.
        leaked_variant = (
            await db.execute(
                text(
                    """
                    SELECT id, variant_name
                    FROM product_variants
                    WHERE id = :variant_id
                    """
                ),
                {"variant_id": fx["secret_b"]},
            )
        ).first()
        if leaked_variant is not None:
            raise AssertionError(
                f"RLS SELECT leak: tenant A saw tenant B row {leaked_variant}"
            )

        leaked_balance = (
            await db.execute(
                text(
                    """
                    SELECT id, on_hand_quantity
                    FROM inventory_balances
                    WHERE id = :balance_id
                    """
                ),
                {"balance_id": fx["secret_balance_b"]},
            )
        ).first()
        if leaked_balance is not None:
            raise AssertionError(
                f"RLS SELECT leak: tenant A saw tenant B inventory {leaked_balance}"
            )

        # Raw UPDATE must affect zero B rows.
        update_result = await db.execute(
            text(
                """
                UPDATE product_variants
                SET variant_name = 'HACKED-BY-TENANT-A'
                WHERE id = :variant_id
                """
            ),
            {"variant_id": fx["secret_b"]},
        )
        if update_result.rowcount != 0:
            raise AssertionError(
                f"RLS UPDATE crossed tenant boundary: rowcount={update_result.rowcount}"
            )

        # Raw DELETE must affect zero B rows.
        delete_result = await db.execute(
            text(
                """
                DELETE FROM inventory_balances
                WHERE id = :balance_id
                """
            ),
            {"balance_id": fx["secret_balance_b"]},
        )
        if delete_result.rowcount != 0:
            raise AssertionError(
                f"RLS DELETE crossed tenant boundary: rowcount={delete_result.rowcount}"
            )

        await db.commit()

    # WITH CHECK must reject malicious INSERT stamped as company B.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["c1"])
        blocked = False
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO products (
                        company_id,
                        base_name,
                        brand,
                        category,
                        created_at
                    )
                    VALUES (
                        :company_id,
                        :base_name,
                        'MALICIOUS',
                        'MALICIOUS',
                        NOW()
                    )
                    """
                ),
                {
                    "company_id": fx["c2"],
                    "base_name": f"MALICIOUS-{uuid.uuid4().hex[:8]}",
                },
            )
            await db.commit()
        except Exception:
            blocked = True
            await db.rollback()

        if not blocked:
            raise AssertionError(
                "RLS WITH CHECK failed: tenant A inserted tenant B data."
            )

    # Verify B data is still intact from B's own tenant context.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["c2"])

        variant = (
            await db.execute(
                select(ProductVariant).where(
                    ProductVariant.company_id == fx["c2"],
                    ProductVariant.id == fx["secret_b"],
                )
            )
        ).scalar_one_or_none()

        if variant is None:
            raise AssertionError(
                "Tenant B product disappeared after malicious cross-tenant attempts."
            )
        if variant.variant_name != fx["secret_b_name"]:
            raise AssertionError(
                f"Tenant B product was modified cross-tenant: {variant.variant_name!r}"
            )

        balance = (
            await db.execute(
                select(InventoryBalance).where(
                    InventoryBalance.company_id == fx["c2"],
                    InventoryBalance.id == fx["secret_balance_b"],
                )
            )
        ).scalar_one_or_none()

        if balance is None or int(balance.on_hand_quantity) != 99:
            raise AssertionError(
                "Tenant B inventory was deleted/changed by tenant A."
            )


async def test_fixed_query_count(fx) -> tuple[int, int, int, int]:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx["c1"], fx["admin_a"])

        # Warm the connection outside the counter.
        await db.execute(text("SELECT 1"))

        _, inv_q1 = await counted(
            inventory_page(
                db,
                admin,
                location_id=fx["warehouse_a"],
                limit=1,
                search="bulk",
            )
        )

        _, inv_q100 = await counted(
            inventory_page(
                db,
                admin,
                location_id=fx["warehouse_a"],
                limit=100,
                search="bulk",
            )
        )

        if inv_q1 != inv_q100:
            raise AssertionError(
                f"Inventory query count scales with page size: "
                f"limit1={inv_q1}, limit100={inv_q100}"
            )

        _, cat_q1 = await counted(
            catalog_page(
                db,
                admin,
                limit=1,
                search="bulk",
            )
        )

        _, cat_q100 = await counted(
            catalog_page(
                db,
                admin,
                limit=100,
                search="bulk",
            )
        )

        if cat_q1 != cat_q100:
            raise AssertionError(
                f"Catalog query count scales with page size: "
                f"limit1={cat_q1}, limit100={cat_q100}"
            )

        return inv_q1, inv_q100, cat_q1, cat_q100


async def cleanup_company(company_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)

        # Explicit cleanup preserves the test's intent and avoids hiding FK mistakes.
        for table in (
            "inventory_stock_policies",
            "inventory_balances",
            "product_batches",
            "product_variants",
            "products",
            "inventory_locations",
            "drivers",
        ):
            await db.execute(
                text(
                    f"DELETE FROM {table} "
                    "WHERE company_id = :company_id"
                ),
                {"company_id": company_id},
            )

        await db.commit()

    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)
        await db.execute(
            text("DELETE FROM companies WHERE id = :company_id"),
            {"company_id": company_id},
        )
        await db.commit()


async def cleanup_uom(uom_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)
        await db.execute(
            text("DELETE FROM uom WHERE id = :uom_id"),
            {"uom_id": uom_id},
        )
        await db.commit()


async def main() -> None:
    role = await ensure_schema_and_rls_ready()
    fx = await setup_fixture()

    try:
        await test_catalog_pagination(fx)
        print("CATALOG_CURSOR_NO_DUPLICATES_NO_SKIPS=OK")

        await test_inventory_pagination(fx)
        print("INVENTORY_CURSOR_NO_DUPLICATES_NO_SKIPS=OK")

        await test_inventory_semantics_and_alerts(fx)
        print("INVENTORY_SELLABLE_BLOCKED_SEMANTICS=OK")
        print("ALERT_SEMANTICS=OK")
        print("INACTIVE_PHYSICAL_STOCK_VISIBLE=OK")

        await test_tenant_api_isolation(fx)
        print("TENANT_API_ISOLATION=OK")
        print("CURSOR_SCOPE_GUARD=OK")
        print("CATALOG_ACTIVE_ONLY=OK")
        print("CROSS_TENANT_RESOLVE=BLOCKED")

        await test_rls_cross_tenant_read_write_block(fx)
        print("RLS_CROSS_TENANT_SELECT=BLOCKED")
        print("RLS_CROSS_TENANT_UPDATE=BLOCKED")
        print("RLS_CROSS_TENANT_DELETE=BLOCKED")
        print("RLS_CROSS_TENANT_INSERT=BLOCKED")
        print("TENANT_B_DATA_INTACT_AFTER_ATTACK=OK")

        inv_q1, inv_q100, cat_q1, cat_q100 = await test_fixed_query_count(fx)
        print(f"INVENTORY_QUERY_COUNT_LIMIT_1={inv_q1}")
        print(f"INVENTORY_QUERY_COUNT_LIMIT_100={inv_q100}")
        print(f"CATALOG_QUERY_COUNT_LIMIT_1={cat_q1}")
        print(f"CATALOG_QUERY_COUNT_LIMIT_100={cat_q100}")
        print("FIXED_QUERY_COUNT=OK")

        print(f"RUNTIME_ROLE={role}")
        print("RUNTIME_ROLE_SUPERUSER=NO")
        print("RUNTIME_ROLE_BYPASSRLS=NO")
        print("ALL_TENANT_TABLES_RLS_FORCE_POLICY=OK")
        print("WAREHOUSE_STAGE6_PAGINATION_POSTGRES_E2E_OK")

    finally:
        # Clean both tenants independently under their own RLS context.
        cleanup_errors = []
        for company_id in (fx["c1"], fx["c2"]):
            try:
                await cleanup_company(company_id)
            except Exception as exc:
                cleanup_errors.append(
                    f"company {company_id}: {exc}"
                )

        try:
            await cleanup_uom(fx["uom_id"])
        except Exception as exc:
            cleanup_errors.append(f"uom {fx['uom_id']}: {exc}")

        if cleanup_errors:
            raise RuntimeError(
                "TEST_CLEANUP_FAILED: " + " | ".join(cleanup_errors)
            )


async def runner() -> None:
    try:
        await main()
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            _before_cursor_execute,
        )
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(runner())
