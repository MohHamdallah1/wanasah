from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# ============================================================================
# Strict parent launcher
# ============================================================================
def _run_strict_parent() -> None:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child"]
    proc = subprocess.run(
        cmd,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )

    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)

    if proc.returncode != 0:
        raise SystemExit(
            f"WAREHOUSE_LOCATION_E2E_CHILD_FAILED: exit_code={proc.returncode}"
        )

    if proc.stderr.strip():
        raise SystemExit(
            "WAREHOUSE_LOCATION_E2E_STRICT_STDERR_FAILED: child emitted stderr."
        )

    if "WAREHOUSE_LOCATION_MANAGEMENT_POSTGRES_E2E_OK" not in proc.stdout:
        raise SystemExit("WAREHOUSE_LOCATION_E2E_SUCCESS_MARKER_MISSING")

    print("STRICT_STDERR=EMPTY")
    print("WAREHOUSE_LOCATION_MANAGEMENT_POSTGRES_E2E_STRICT_OK")


if "--child" not in sys.argv:
    _run_strict_parent()
    raise SystemExit(0)


# ============================================================================
# Child process imports
# ============================================================================
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url


def _locate_project() -> tuple[Path, Path]:
    cwd = Path.cwd().resolve()
    here = Path(__file__).resolve().parent

    for root in (cwd, here, cwd.parent, here.parent):
        backend = root / "wa_backend"
        if backend.is_dir() and (backend / "models.py").is_file():
            return root, backend
        if root.name == "wa_backend" and (root / "models.py").is_file():
            return root.parent, root

    raise SystemExit(
        "ERROR: لم أجد wa_backend/models.py. شغّل الاختبار من جذر المشروع."
    )


ROOT, BACKEND = _locate_project()
sys.path.insert(0, str(BACKEND))

from config import Config  # noqa: E402
from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import (  # noqa: E402
    Branch,
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryMovement,
    InventoryMovementImpact,
    InventoryTransferHeader,
    OperationIdempotency,
    Product,
    ProductBatch,
    ProductVariant,
    StocktakeSession,
    UOM,
    Vehicle,
    Zone,
)
from services import (  # noqa: E402
    InventoryMutationError,
    apply_inventory_movements_batch,
)
from schemas import (  # noqa: E402
    UnifiedDispatchRequest,
    UnifiedTransferDecisionRequest,
    WarehouseLocationCreateRequest,
    WarehouseLocationStateRequest,
    WarehouseLocationUpdateRequest,
)
from api.warehouse import (  # noqa: E402
    create_warehouse_location,
    update_warehouse_location,
    activate_warehouse_location,
    deactivate_warehouse_location,
    manage_warehouse_locations,
    unified_transfer_dispatch,
    unified_transfer_cancel,
)


# ============================================================================
# Safety
# ============================================================================
db_url = make_url(Config.SQLALCHEMY_DATABASE_URI)
host = (db_url.host or "").lower()
if host not in {"localhost", "127.0.0.1", "::1"}:
    if os.getenv("WANASAH_ALLOW_REMOTE_TEST_DB") != "YES":
        raise SystemExit(
            "REFUSED: DATABASE_URL ليست قاعدة محلية. "
            "الاختبار يكتب Fixtures مؤقتة. "
            "إذا كانت قاعدة اختبار بعيدة مقصودة اضبط "
            "WANASAH_ALLOW_REMOTE_TEST_DB=YES."
        )


# ============================================================================
# Query counter
# ============================================================================
@dataclass
class QueryCounter:
    active: bool = False
    count: int = 0


_QC = QueryCounter()


def _before_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    if _QC.active:
        _QC.count += 1


event.listen(
    engine.sync_engine,
    "before_cursor_execute",
    _before_cursor_execute,
)


async def counted(awaitable):
    _QC.count = 0
    _QC.active = True
    try:
        result = await awaitable
    finally:
        _QC.active = False
    return result, _QC.count


# ============================================================================
# Helpers
# ============================================================================
async def set_tenant(db, company_id: int | None) -> None:
    tenant_context.set(company_id)
    value = "" if company_id is None else str(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": value},
    )


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


async def expect_http(awaitable, status_code: int) -> HTTPException:
    try:
        await awaitable
    except HTTPException as exc:
        if exc.status_code != status_code:
            raise AssertionError(
                f"Expected HTTP {status_code}, got {exc.status_code}: {exc.detail}"
            )
        return exc
    raise AssertionError(
        f"Expected HTTP {status_code}, request unexpectedly succeeded."
    )


async def call_create(company_id: int, admin_id: int, payload):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await create_warehouse_location(
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_update(company_id: int, admin_id: int, location_id: int, payload):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await update_warehouse_location(
            location_id=location_id,
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_activate(company_id: int, admin_id: int, location_id: int, payload):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await activate_warehouse_location(
            location_id=location_id,
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_deactivate(company_id: int, admin_id: int, location_id: int, payload):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await deactivate_warehouse_location(
            location_id=location_id,
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_list(
    company_id: int,
    admin_id: int,
    *,
    search: str | None = None,
    include_inactive: bool = True,
    cursor: str | None = None,
    limit: int = 50,
):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await manage_warehouse_locations(
            search=search,
            include_inactive=include_inactive,
            cursor=cursor,
            limit=limit,
            db=db,
            current_admin=admin,
        )


async def call_dispatch(company_id: int, admin_id: int, payload):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await unified_transfer_dispatch(
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_cancel(
    company_id: int,
    admin_id: int,
    header_id: int,
    payload,
):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        return await unified_transfer_cancel(
            header_id=header_id,
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def get_location(db, company_id: int, location_id: int) -> InventoryLocation:
    await set_tenant(db, company_id)
    return (
        await db.execute(
            select(InventoryLocation).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
            )
        )
    ).scalar_one()


async def balance_qty(
    db,
    *,
    company_id: int,
    location_id: int,
    variant_id: int,
    batch_id: int,
) -> tuple[int, int]:
    await set_tenant(db, company_id)
    row = (
        await db.execute(
            select(
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
            ).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
    ).one_or_none()
    if row is None:
        return (0, 0)
    return int(row[0] or 0), int(row[1] or 0)


async def move_stock(
    *,
    company_id: int,
    admin_id: int,
    variant_id: int,
    batch_id: int,
    quantity: int,
    source_location_id: int,
    destination_location_id: int,
    key: str,
):
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        try:
            result = await apply_inventory_movements_batch(
                db,
                company_id=company_id,
                performed_by=admin_id,
                movements=[{
                    "product_variant_id": variant_id,
                    "batch_id": batch_id,
                    "quantity": quantity,
                    "movement_kind": "PHYSICAL",
                    "reference_type": "LOCATION_E2E",
                    "reference_id": key,
                    "idempotency_key": key,
                    "source_location_id": source_location_id,
                    "destination_location_id": destination_location_id,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "notes": "warehouse location management e2e",
                }],
            )
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise


async def operation_count(
    db,
    *,
    company_id: int,
    operation: str,
    request_id: uuid.UUID,
) -> int:
    await set_tenant(db, company_id)
    return int(
        (
            await db.execute(
                select(func.count(OperationIdempotency.id)).where(
                    OperationIdempotency.company_id == company_id,
                    OperationIdempotency.operation == operation,
                    OperationIdempotency.request_id == str(request_id),
                )
            )
        ).scalar_one()
    )


# ============================================================================
# Preflight
# ============================================================================
async def preflight() -> str:
    if engine.dialect.name != "postgresql":
        raise AssertionError("POSTGRESQL_REQUIRED")

    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)

        role_row = (
            await db.execute(
                text(
                    """
                    SELECT rolname, rolsuper, rolbypassrls
                    FROM pg_roles
                    WHERE rolname = current_user
                    """
                )
            )
        ).one()
        role, is_superuser, bypass = (
            str(role_row[0]),
            bool(role_row[1]),
            bool(role_row[2]),
        )
        if is_superuser or bypass:
            raise AssertionError(
                f"Invalid runtime role for RLS test: {role}, "
                f"superuser={is_superuser}, bypassrls={bypass}"
            )

        index_def = (
            await db.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'inventory_locations'
                      AND indexname = 'ix_inventory_location_company_type_active_id'
                    """
                )
            )
        ).scalar_one_or_none()
        if index_def is None:
            raise AssertionError(
                "ix_inventory_location_company_type_active_id missing"
            )

        constraint_names = set(
            (
                await db.execute(
                    text(
                        """
                        SELECT con.conname
                        FROM pg_constraint con
                        JOIN pg_class rel ON rel.oid = con.conrelid
                        JOIN pg_namespace ns ON ns.oid = rel.relnamespace
                        WHERE ns.nspname = current_schema()
                          AND rel.relname = 'inventory_locations'
                          AND con.contype = 'c'
                        """
                    )
                )
            ).scalars().all()
        )
        expected_name_check = "ck_inventory_locations_chk_inv_loc_name_not_blank"
        if expected_name_check not in constraint_names:
            raise AssertionError(
                "InventoryLocation nonblank name CHECK missing: "
                f"{sorted(constraint_names)}"
            )

        for table_name in (
            "inventory_locations",
            "inventory_balances",
            "inventory_transfer_headers",
            "inventory_locks",
            "dispatch_routes",
            "operation_idempotency",
        ):
            row = (
                await db.execute(
                    text(
                        """
                        SELECT c.relrowsecurity, c.relforcerowsecurity,
                               EXISTS (
                                   SELECT 1
                                   FROM pg_policies p
                                   WHERE p.schemaname = current_schema()
                                     AND p.tablename = :table_name
                                     AND p.policyname = 'tenant_isolation_policy'
                               )
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema()
                          AND c.relname = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            ).one()
            if not all(bool(value) for value in row):
                raise AssertionError(
                    f"RLS/FORCE/policy incomplete for {table_name}: {row}"
                )

        return role


# ============================================================================
# Fixtures
# ============================================================================
async def setup_fixture() -> dict:
    suffix = uuid.uuid4().hex[:10]
    today = date.today()

    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)

        company_a = Company(
            name=f"Warehouse Locations A {suffix}",
            company_code=f"WLA{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        company_b = Company(
            name=f"Warehouse Locations B {suffix}",
            company_code=f"WLB{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        uom = UOM(
            name=f"Warehouse Location Unit {suffix}",
            code=f"WLU{suffix[:7]}",
        )
        db.add_all([company_a, company_b, uom])
        await db.flush()

        await set_tenant(db, company_a.id)
        admin_a = Driver(
            company_id=company_a.id,
            username=f"wl_admin_a_{suffix}",
            password_hash="test-only",
            full_name="Warehouse Location Admin A",
            is_active=True,
            is_admin=True,
        )
        receiver_a = Driver(
            company_id=company_a.id,
            username=f"wl_receiver_a_{suffix}",
            password_hash="test-only",
            full_name="Warehouse Location Receiver A",
            is_active=True,
            is_admin=True,
        )
        branch_a = Branch(
            company_id=company_a.id,
            name=f"Branch A {suffix}",
            branch_code=f"BRA-{suffix}",
            is_active=True,
        )
        product = Product(
            company_id=company_a.id,
            base_name=f"Warehouse Location Product {suffix}",
        )
        db.add_all([admin_a, receiver_a, branch_a, product])
        await db.flush()

        variant = ProductVariant(
            company_id=company_a.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Warehouse Location Variant {suffix}",
            sku=f"WL-{suffix}",
            packs_per_carton=10,
            price_per_carton=Decimal("10.000"),
            price_per_pack=Decimal("1.000"),
            is_active=True,
            default_max_samples_per_day=0,
        )
        db.add(variant)
        await db.flush()

        batch = ProductBatch(
            company_id=company_a.id,
            product_variant_id=variant.id,
            batch_number=f"WL-BATCH-{suffix}",
            production_date=today - timedelta(days=30),
            expiry_date=today + timedelta(days=365),
            is_active=True,
        )
        db.add(batch)
        await db.flush()

        # Tenant B
        await set_tenant(db, company_b.id)
        admin_b = Driver(
            company_id=company_b.id,
            username=f"wl_admin_b_{suffix}",
            password_hash="test-only",
            full_name="Warehouse Location Admin B",
            is_active=True,
            is_admin=True,
        )
        branch_b = Branch(
            company_id=company_b.id,
            name=f"Branch B {suffix}",
            branch_code=f"BRB-{suffix}",
            is_active=True,
        )
        db.add_all([admin_b, branch_b])
        await db.commit()

        return {
            "suffix": suffix,
            "company_a": int(company_a.id),
            "company_b": int(company_b.id),
            "admin_a": int(admin_a.id),
            "receiver_a": int(receiver_a.id),
            "admin_b": int(admin_b.id),
            "branch_a": int(branch_a.id),
            "branch_b": int(branch_b.id),
            "product": int(product.id),
            "variant": int(variant.id),
            "batch": int(batch.id),
            "uom": int(uom.id),
        }


async def cleanup_company(company_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)

        # Child tables before parents.
        for table_name in (
            "system_audit_logs",
            "inventory_movement_impacts",
            "inventory_movements",
            "inventory_transfer_lines",
            "inventory_transfer_headers",
            "operation_idempotency",
            "inventory_locks",
            "stocktake_count_attempt_lines",
            "stocktake_count_attempts",
            "stocktake_lines",
            "stocktake_sessions",
            "inventory_balances",
            "inventory_stock_policies",
            "dispatch_load_plan_lines",
            "dispatch_routes",
            "inventory_locations",
            "product_batches",
            "product_variants",
            "products",
            "vehicles",
            "zones",
            "branches",
            "drivers",
        ):
            await db.execute(
                text(
                    f"DELETE FROM {table_name} "
                    "WHERE company_id = :company_id"
                ),
                {"company_id": company_id},
            )

        await db.commit()


async def cleanup_fixture(fx: dict) -> None:
    errors: list[str] = []
    for company_id in (fx["company_a"], fx["company_b"]):
        try:
            await cleanup_company(company_id)
        except Exception as exc:
            errors.append(f"company {company_id}: {exc}")

    try:
        async with AsyncSessionLocal() as db:
            await set_tenant(db, None)
            await db.execute(
                text(
                    "DELETE FROM companies WHERE id IN (:a, :b)"
                ),
                {"a": fx["company_a"], "b": fx["company_b"]},
            )
            await db.execute(
                text("DELETE FROM uom WHERE id = :uom"),
                {"uom": fx["uom"]},
            )
            await db.commit()
    except Exception as exc:
        errors.append(f"global cleanup: {exc}")

    if errors:
        raise RuntimeError(
            "WAREHOUSE_LOCATION_TEST_CLEANUP_FAILED: "
            + " | ".join(errors)
        )


# ============================================================================
# Tests
# ============================================================================
async def test_create_edit_idempotency(fx: dict) -> dict:
    create_id = uuid.uuid4()
    create_payload = WarehouseLocationCreateRequest(
        request_id=create_id,
        name="مستودع عمّان",
        code=f"AMMAN-{fx['suffix']}",
        branch_id=fx["branch_a"],
    )

    first = await call_create(
        fx["company_a"], fx["admin_a"], create_payload
    )
    replay = await call_create(
        fx["company_a"], fx["admin_a"], create_payload
    )
    if first != replay:
        raise AssertionError("Create idempotency replay mismatch.")

    source_id = int(first["location"]["id"])
    if (
        first["location"]["name"] != "مستودع عمّان"
        or first["location"]["code"] != f"AMMAN-{fx['suffix']}".upper()
        or int(first["location"]["branch_id"]) != fx["branch_a"]
        or first["location"]["is_active"] is not True
    ):
        raise AssertionError(f"Unexpected create response: {first}")

    changed = create_payload.model_copy(
        update={"name": "اسم مختلف لنفس request_id"}
    )
    await expect_http(
        call_create(
            fx["company_a"],
            fx["admin_a"],
            changed,
        ),
        409,
    )

    await expect_http(
        call_create(
            fx["company_a"],
            fx["admin_a"],
            WarehouseLocationCreateRequest(
                request_id=uuid.uuid4(),
                name="Reserved transit code attack",
                code="TRANSIT-SYS",
                branch_id=fx["branch_a"],
            ),
        ),
        409,
    )

    # Seed source stock through the actual inventory engine.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        db.add(
            InventoryBalance(
                company_id=fx["company_a"],
                location_id=source_id,
                product_variant_id=fx["variant"],
                batch_id=fx["batch"],
                stock_status="AVAILABLE",
                on_hand_quantity=1000,
                reserved_quantity=0,
            )
        )
        await db.commit()

    update_id = uuid.uuid4()
    update_payload = WarehouseLocationUpdateRequest(
        request_id=update_id,
        name="مستودع عمّان المركزي",
        code=f"AMMAN-CENTRAL-{fx['suffix']}",
        branch_id=fx["branch_a"],
    )
    updated = await call_update(
        fx["company_a"],
        fx["admin_a"],
        source_id,
        update_payload,
    )
    updated_replay = await call_update(
        fx["company_a"],
        fx["admin_a"],
        source_id,
        update_payload,
    )
    if updated != updated_replay:
        raise AssertionError("Update idempotency replay mismatch.")

    changed_update = update_payload.model_copy(
        update={"name": "Payload conflict"}
    )
    await expect_http(
        call_update(
            fx["company_a"],
            fx["admin_a"],
            source_id,
            changed_update,
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        if await operation_count(
            db,
            company_id=fx["company_a"],
            operation="WAREHOUSE_LOCATION_CREATE",
            request_id=create_id,
        ) != 1:
            raise AssertionError("Create idempotency record count != 1.")
        if await operation_count(
            db,
            company_id=fx["company_a"],
            operation="WAREHOUSE_LOCATION_UPDATE",
            request_id=update_id,
        ) != 1:
            raise AssertionError("Update idempotency record count != 1.")

    return {
        "source_id": source_id,
        "create_id": create_id,
        "update_id": update_id,
    }


async def create_empty_location(
    fx: dict,
    *,
    label: str,
) -> int:
    response = await call_create(
        fx["company_a"],
        fx["admin_a"],
        WarehouseLocationCreateRequest(
            request_id=uuid.uuid4(),
            name=f"{label} {fx['suffix']}",
            code=f"{label}-{fx['suffix']}",
            branch_id=fx["branch_a"],
        ),
    )
    return int(response["location"]["id"])


async def test_activate_deactivate_idempotency(fx: dict) -> int:
    location_id = await create_empty_location(fx, label="EMPTY")

    deactivate_id = uuid.uuid4()
    payload = WarehouseLocationStateRequest(
        request_id=deactivate_id,
        reason="إيقاف تشغيلي للاختبار",
    )
    first = await call_deactivate(
        fx["company_a"], fx["admin_a"], location_id, payload
    )
    replay = await call_deactivate(
        fx["company_a"], fx["admin_a"], location_id, payload
    )
    if first != replay:
        raise AssertionError("Deactivate idempotency replay mismatch.")
    if first["location"]["is_active"] is not False:
        raise AssertionError("Location did not deactivate.")

    changed = payload.model_copy(
        update={"reason": "سبب مختلف لنفس request_id"}
    )
    await expect_http(
        call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            location_id,
            changed,
        ),
        409,
    )

    activate_id = uuid.uuid4()
    activate_payload = WarehouseLocationStateRequest(
        request_id=activate_id,
        reason="إعادة تفعيل",
    )
    activated = await call_activate(
        fx["company_a"],
        fx["admin_a"],
        location_id,
        activate_payload,
    )
    activated_replay = await call_activate(
        fx["company_a"],
        fx["admin_a"],
        location_id,
        activate_payload,
    )
    if activated != activated_replay:
        raise AssertionError("Activate idempotency replay mismatch.")
    if activated["location"]["is_active"] is not True:
        raise AssertionError("Location did not reactivate.")

    async with AsyncSessionLocal() as db:
        if await operation_count(
            db,
            company_id=fx["company_a"],
            operation="WAREHOUSE_LOCATION_DEACTIVATE",
            request_id=deactivate_id,
        ) != 1:
            raise AssertionError("Deactivate idempotency record count != 1.")
        if await operation_count(
            db,
            company_id=fx["company_a"],
            operation="WAREHOUSE_LOCATION_ACTIVATE",
            request_id=activate_id,
        ) != 1:
            raise AssertionError("Activate idempotency record count != 1.")

    return location_id


async def test_stock_guard(fx: dict, source_id: int) -> None:
    target_id = await create_empty_location(fx, label="STOCK")
    await move_stock(
        company_id=fx["company_a"],
        admin_id=fx["admin_a"],
        variant_id=fx["variant"],
        batch_id=fx["batch"],
        quantity=25,
        source_location_id=source_id,
        destination_location_id=target_id,
        key=f"WL-STOCK-IN-{fx['suffix']}",
    )

    await expect_http(
        call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            target_id,
            WarehouseLocationStateRequest(
                request_id=uuid.uuid4(),
                reason="must be blocked by physical stock",
            ),
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        location = await get_location(db, fx["company_a"], target_id)
        if not location.is_active:
            raise AssertionError("Stock-bearing warehouse was deactivated.")
        on_hand, _ = await balance_qty(
            db,
            company_id=fx["company_a"],
            location_id=target_id,
            variant_id=fx["variant"],
            batch_id=fx["batch"],
        )
        if on_hand != 25:
            raise AssertionError(f"Stock guard changed quantity: {on_hand}")

    # Remove stock through the engine, then it must be deactivatable.
    await move_stock(
        company_id=fx["company_a"],
        admin_id=fx["admin_a"],
        variant_id=fx["variant"],
        batch_id=fx["batch"],
        quantity=25,
        source_location_id=target_id,
        destination_location_id=source_id,
        key=f"WL-STOCK-OUT-{fx['suffix']}",
    )
    result = await call_deactivate(
        fx["company_a"],
        fx["admin_a"],
        target_id,
        WarehouseLocationStateRequest(
            request_id=uuid.uuid4(),
            reason="stock removed",
        ),
    )
    if result["location"]["is_active"] is not False:
        raise AssertionError("Empty warehouse failed to deactivate after stock removal.")


async def test_in_transit_guard(fx: dict, source_id: int) -> None:
    destination_id = await create_empty_location(fx, label="TRANSITDST")

    dispatched = await call_dispatch(
        fx["company_a"],
        fx["admin_a"],
        UnifiedDispatchRequest(
            request_id=uuid.uuid4(),
            source_location_id=source_id,
            destination_location_id=destination_id,
            items=[{
                "product_variant_id": fx["variant"],
                "quantity": 15,
            }],
            notes="location deactivate IN_TRANSIT guard",
        ),
    )
    header_id = int(dispatched["header_id"])

    await expect_http(
        call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            destination_id,
            WarehouseLocationStateRequest(
                request_id=uuid.uuid4(),
                reason="must fail while transfer is in transit",
            ),
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        header = (
            await db.execute(
                select(InventoryTransferHeader).where(
                    InventoryTransferHeader.company_id == fx["company_a"],
                    InventoryTransferHeader.id == header_id,
                )
            )
        ).scalar_one()
        if header.status != "IN_TRANSIT":
            raise AssertionError("IN_TRANSIT guard altered transfer state.")

        destination = await get_location(
            db, fx["company_a"], destination_id
        )
        if not destination.is_active:
            raise AssertionError("IN_TRANSIT destination was deactivated.")

    await call_cancel(
        fx["company_a"],
        fx["admin_a"],
        header_id,
        UnifiedTransferDecisionRequest(
            request_id=uuid.uuid4(),
            decision_reason="cleanup after IN_TRANSIT guard test",
        ),
    )

    result = await call_deactivate(
        fx["company_a"],
        fx["admin_a"],
        destination_id,
        WarehouseLocationStateRequest(
            request_id=uuid.uuid4(),
            reason="transfer closed",
        ),
    )
    if result["location"]["is_active"] is not False:
        raise AssertionError("Warehouse stayed active after transfer closed.")


async def test_stocktake_lock_guard(fx: dict) -> None:
    location_id = await create_empty_location(fx, label="STOCKTAKE")

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        session = StocktakeSession(
            company_id=fx["company_a"],
            location_id=location_id,
            reference_number=f"WL-ST-{fx['suffix']}",
            stocktake_type="FULL_COUNT",
            status="DRAFT",
            started_by=fx["admin_a"],
            notes="location guard e2e",
        )
        db.add(session)
        await db.flush()

        lock = InventoryLock(
            company_id=fx["company_a"],
            stocktake_session_id=session.id,
            location_id=location_id,
            product_variant_id=None,
            batch_id=None,
            created_by=fx["admin_a"],
        )
        db.add(lock)
        await db.commit()

        lock_id = int(lock.id)

    await expect_http(
        call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            location_id,
            WarehouseLocationStateRequest(
                request_id=uuid.uuid4(),
                reason="must fail during stocktake",
            ),
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        now = (
            await db.execute(
                text("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'")
            )
        ).scalar_one()
        await db.execute(
            text(
                """
                UPDATE inventory_locks
                SET released_by = :admin_id,
                    released_at = :now,
                    release_reason = 'location e2e cleanup'
                WHERE company_id = :company_id
                  AND id = :lock_id
                """
            ),
            {
                "admin_id": fx["admin_a"],
                "now": now,
                "company_id": fx["company_a"],
                "lock_id": lock_id,
            },
        )
        await db.commit()


async def test_dispatch_route_guard(fx: dict) -> None:
    location_id = await create_empty_location(fx, label="ROUTE")

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        zone = Zone(
            company_id=fx["company_a"],
            name=f"WL Zone {fx['suffix']}",
            sequence_number=1,
            is_active=True,
        )
        vehicle = Vehicle(
            company_id=fx["company_a"],
            plate_number=f"WL-{fx['suffix'][:6]}",
            current_mileage=0,
            maintenance_status="Active",
            is_active=True,
        )
        route_driver = Driver(
            company_id=fx["company_a"],
            username=f"wl_route_driver_{fx['suffix']}",
            password_hash="test-only",
            full_name="Warehouse Location Route Driver",
            is_active=True,
            is_admin=False,
        )
        db.add_all([zone, vehicle, route_driver])
        await db.flush()

        route = DispatchRoute(
            company_id=fx["company_a"],
            zone_id=zone.id,
            driver_id=route_driver.id,
            vehicle_id=vehicle.id,
            work_session_id=None,
            source_location_id=location_id,
            dispatch_date=date.today(),
            status="waiting",
        )
        db.add(route)
        await db.commit()
        route_id = int(route.id)

    await expect_http(
        call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            location_id,
            WarehouseLocationStateRequest(
                request_id=uuid.uuid4(),
                reason="must fail with active dispatch route",
            ),
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        await db.execute(
            text(
                """
                UPDATE dispatch_routes
                SET status = 'closed'
                WHERE company_id = :company_id
                  AND id = :route_id
                """
            ),
            {
                "company_id": fx["company_a"],
                "route_id": route_id,
            },
        )
        await db.commit()

    result = await call_deactivate(
        fx["company_a"],
        fx["admin_a"],
        location_id,
        WarehouseLocationStateRequest(
            request_id=uuid.uuid4(),
            reason="route closed",
        ),
    )
    if result["location"]["is_active"] is not False:
        raise AssertionError("Warehouse did not deactivate after route closed.")


async def test_cross_tenant_and_cursor(fx: dict) -> None:
    b_create = await call_create(
        fx["company_b"],
        fx["admin_b"],
        WarehouseLocationCreateRequest(
            request_id=uuid.uuid4(),
            name="Tenant B Secret Warehouse",
            code=f"B-SECRET-{fx['suffix']}",
            branch_id=fx["branch_b"],
        ),
    )
    b_location_id = int(b_create["location"]["id"])

    # API: A cannot update/deactivate B.
    await expect_http(
        call_update(
            fx["company_a"],
            fx["admin_a"],
            b_location_id,
            WarehouseLocationUpdateRequest(
                request_id=uuid.uuid4(),
                name="HACKED",
            ),
        ),
        404,
    )
    await expect_http(
        call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            b_location_id,
            WarehouseLocationStateRequest(
                request_id=uuid.uuid4(),
                reason="malicious cross tenant deactivation",
            ),
        ),
        404,
    )

    a_search = await call_list(
        fx["company_a"],
        fx["admin_a"],
        search="secret",
        limit=10,
    )
    if any(
        int(item["id"]) == b_location_id
        for item in a_search["items"]
    ):
        raise AssertionError("Tenant A saw Tenant B warehouse through list API.")

    # Need a cursor from A; enough A warehouses exist at this point.
    page = await call_list(
        fx["company_a"],
        fx["admin_a"],
        limit=1,
    )
    cursor = page["next_cursor"]
    if not cursor:
        raise AssertionError("Expected location management cursor.")

    await expect_http(
        call_list(
            fx["company_a"],
            fx["admin_a"],
            include_inactive=False,
            cursor=cursor,
            limit=1,
        ),
        400,
    )
    await expect_http(
        call_list(
            fx["company_b"],
            fx["admin_b"],
            cursor=cursor,
            limit=1,
        ),
        400,
    )

    # Raw RLS attacks from A against B location.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])

        leaked = (
            await db.execute(
                text(
                    """
                    SELECT id
                    FROM inventory_locations
                    WHERE id = :location_id
                    """
                ),
                {"location_id": b_location_id},
            )
        ).first()
        if leaked is not None:
            raise AssertionError(f"RLS SELECT leaked B location: {leaked}")

        upd = await db.execute(
            text(
                """
                UPDATE inventory_locations
                SET name = 'HACKED_RAW'
                WHERE id = :location_id
                """
            ),
            {"location_id": b_location_id},
        )
        if upd.rowcount != 0:
            raise AssertionError(
                f"RLS UPDATE crossed tenant boundary: {upd.rowcount}"
            )

        dele = await db.execute(
            text(
                """
                DELETE FROM inventory_locations
                WHERE id = :location_id
                """
            ),
            {"location_id": b_location_id},
        )
        if dele.rowcount != 0:
            raise AssertionError(
                f"RLS DELETE crossed tenant boundary: {dele.rowcount}"
            )

        await db.commit()

    # WITH CHECK / composite FK: A cannot create an A warehouse using B branch.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        blocked = False
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO inventory_locations (
                        company_id, branch_id, name, code,
                        location_type, is_active, created_at, updated_at
                    ) VALUES (
                        :company_a, :branch_b, 'MALICIOUS',
                        :code, 'WAREHOUSE', TRUE, NOW(), NOW()
                    )
                    """
                ),
                {
                    "company_a": fx["company_a"],
                    "branch_b": fx["branch_b"],
                    "code": f"MAL-{fx['suffix']}",
                },
            )
            await db.flush()
        except Exception:
            blocked = True
        finally:
            await db.rollback()

        if not blocked:
            raise AssertionError(
                "Composite tenant branch FK allowed A warehouse -> B branch."
            )

    # Ensure B warehouse intact.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_b"])
        row = (
            await db.execute(
                select(
                    InventoryLocation.name,
                    InventoryLocation.is_active,
                ).where(
                    InventoryLocation.company_id == fx["company_b"],
                    InventoryLocation.id == b_location_id,
                )
            )
        ).one()
        if row[0] != "Tenant B Secret Warehouse" or not bool(row[1]):
            raise AssertionError(
                f"Tenant B location changed after attacks: {row}"
            )


async def _capture(label: str, coro):
    try:
        return label, await coro
    except (HTTPException, InventoryMutationError) as exc:
        return label, exc


async def test_concurrent_deactivate_vs_movement(fx: dict, source_id: int) -> str:
    target_id = await create_empty_location(fx, label="RACE")
    movement_key = f"WL-RACE-{uuid.uuid4().hex}"
    deactivate_request_id = uuid.uuid4()

    results = await asyncio.gather(
        _capture(
            "deactivate",
            call_deactivate(
                fx["company_a"],
                fx["admin_a"],
                target_id,
                WarehouseLocationStateRequest(
                    request_id=deactivate_request_id,
                    reason="concurrent deactivate vs movement",
                ),
            ),
        ),
        _capture(
            "movement",
            move_stock(
                company_id=fx["company_a"],
                admin_id=fx["admin_a"],
                variant_id=fx["variant"],
                batch_id=fx["batch"],
                quantity=17,
                source_location_id=source_id,
                destination_location_id=target_id,
                key=movement_key,
            ),
        ),
    )

    successes = [
        (label, value)
        for label, value in results
        if not isinstance(value, (HTTPException, InventoryMutationError))
    ]
    failures = [
        (label, value)
        for label, value in results
        if isinstance(value, (HTTPException, InventoryMutationError))
    ]

    if len(successes) != 1 or len(failures) != 1:
        raise AssertionError(
            f"Race must have exactly one winner: {results}"
        )

    winner = successes[0][0]
    loser_label, loser_exc = failures[0]

    async with AsyncSessionLocal() as db:
        location = await get_location(
            db, fx["company_a"], target_id
        )
        target_on_hand, _ = await balance_qty(
            db,
            company_id=fx["company_a"],
            location_id=target_id,
            variant_id=fx["variant"],
            batch_id=fx["batch"],
        )

        if winner == "deactivate":
            if location.is_active:
                raise AssertionError(
                    "Deactivate won but location is still active."
                )
            if target_on_hand != 0:
                raise AssertionError(
                    f"Deactivate won but stock arrived: {target_on_hand}"
                )
            if loser_label != "movement":
                raise AssertionError(f"Unexpected loser: {failures}")
            if not isinstance(loser_exc, InventoryMutationError):
                raise AssertionError(
                    f"Movement loser should be InventoryMutationError: {loser_exc}"
                )
        elif winner == "movement":
            if not location.is_active:
                raise AssertionError(
                    "Movement won but location was deactivated."
                )
            if target_on_hand != 17:
                raise AssertionError(
                    f"Movement won but target quantity is {target_on_hand}"
                )
            if loser_label != "deactivate":
                raise AssertionError(f"Unexpected loser: {failures}")
            if (
                not isinstance(loser_exc, HTTPException)
                or loser_exc.status_code != 409
            ):
                raise AssertionError(
                    f"Deactivate loser should be HTTP 409: {loser_exc}"
                )
        else:
            raise AssertionError(f"Unknown race winner: {winner}")

        # Verify no partial idempotency record from the losing deactivation.
        op_count = await operation_count(
            db,
            company_id=fx["company_a"],
            operation="WAREHOUSE_LOCATION_DEACTIVATE",
            request_id=deactivate_request_id,
        )
        if winner == "deactivate" and op_count != 1:
            raise AssertionError(
                "Winning deactivation did not commit exactly one idempotency row."
            )
        if winner == "movement" and op_count != 0:
            raise AssertionError(
                "Losing deactivation committed an idempotency row."
            )

    # If movement won, restore stock and close target cleanly.
    if winner == "movement":
        await move_stock(
            company_id=fx["company_a"],
            admin_id=fx["admin_a"],
            variant_id=fx["variant"],
            batch_id=fx["batch"],
            quantity=17,
            source_location_id=target_id,
            destination_location_id=source_id,
            key=f"{movement_key}-RETURN",
        )
        closed = await call_deactivate(
            fx["company_a"],
            fx["admin_a"],
            target_id,
            WarehouseLocationStateRequest(
                request_id=uuid.uuid4(),
                reason="race cleanup after stock return",
            ),
        )
        if closed["location"]["is_active"] is not False:
            raise AssertionError("Race cleanup failed to deactivate target.")

    return winner


async def test_list_fixed_query_count(fx: dict) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(
            db, fx["company_a"], fx["admin_a"]
        )
        await db.execute(text("SELECT 1"))

        _, q1 = await counted(
            manage_warehouse_locations(
                search=None,
                include_inactive=True,
                cursor=None,
                limit=1,
                db=db,
                current_admin=admin,
            )
        )
        _, q100 = await counted(
            manage_warehouse_locations(
                search=None,
                include_inactive=True,
                cursor=None,
                limit=100,
                db=db,
                current_admin=admin,
            )
        )

        if q1 != q100:
            raise AssertionError(
                f"Warehouse location list query count scales: {q1} != {q100}"
            )
        return q1, q100


# ============================================================================
# Main
# ============================================================================
async def child_main() -> None:
    started = time.perf_counter()
    role = await preflight()
    fx = await setup_fixture()

    try:
        base = await test_create_edit_idempotency(fx)
        source_id = base["source_id"]
        print("LOCATION_CREATE=OK")
        print("LOCATION_CREATE_IDEMPOTENCY=OK")
        print("LOCATION_EDIT=OK")
        print("LOCATION_EDIT_IDEMPOTENCY=OK")
        print("TRANSIT_SYS_CODE_RESERVED=OK")

        await test_activate_deactivate_idempotency(fx)
        print("LOCATION_DEACTIVATE_EMPTY=OK")
        print("LOCATION_DEACTIVATE_IDEMPOTENCY=OK")
        print("LOCATION_ACTIVATE=OK")
        print("LOCATION_ACTIVATE_IDEMPOTENCY=OK")

        await test_stock_guard(fx, source_id)
        print("DEACTIVATE_WITH_STOCK=BLOCKED")
        print("DEACTIVATE_AFTER_STOCK_REMOVAL=OK")

        await test_in_transit_guard(fx, source_id)
        print("DEACTIVATE_WITH_IN_TRANSIT=BLOCKED")
        print("DEACTIVATE_AFTER_TRANSFER_CLOSED=OK")

        await test_stocktake_lock_guard(fx)
        print("DEACTIVATE_WITH_ACTIVE_STOCKTAKE_LOCK=BLOCKED")

        await test_dispatch_route_guard(fx)
        print("DEACTIVATE_WITH_ACTIVE_DISPATCH_ROUTE=BLOCKED")
        print("DEACTIVATE_AFTER_ROUTE_CLOSED=OK")

        await test_cross_tenant_and_cursor(fx)
        print("LOCATION_API_CROSS_TENANT=BLOCKED")
        print("LOCATION_RLS_SELECT=BLOCKED")
        print("LOCATION_RLS_UPDATE=BLOCKED")
        print("LOCATION_RLS_DELETE=BLOCKED")
        print("LOCATION_COMPOSITE_BRANCH_FK=ENFORCED")
        print("LOCATION_CURSOR_FILTER_SCOPE=BLOCKED")
        print("LOCATION_CURSOR_CROSS_TENANT=BLOCKED")
        print("TENANT_B_LOCATION_INTACT_AFTER_ATTACK=OK")

        race_winner = await test_concurrent_deactivate_vs_movement(
            fx,
            source_id,
        )
        print(f"DEACTIVATE_VS_MOVEMENT_WINNER={race_winner.upper()}")
        print("DEACTIVATE_VS_MOVEMENT=ONE_WINNER")
        print("DEACTIVATION_EXCLUSIVE_GUARD=VERIFIED")
        print("NO_PARTIAL_LOCATION_STATE=VERIFIED")

        q1, q100 = await test_list_fixed_query_count(fx)
        print(f"LOCATION_LIST_QUERY_COUNT_LIMIT_1={q1}")
        print(f"LOCATION_LIST_QUERY_COUNT_LIMIT_100={q100}")
        print("LOCATION_LIST_FIXED_QUERY_COUNT=OK")

        print(f"RUNTIME_ROLE={role}")
        print("RUNTIME_ROLE_SUPERUSER=NO")
        print("RUNTIME_ROLE_BYPASSRLS=NO")

    finally:
        await cleanup_fixture(fx)
        await engine.dispose()

    elapsed = time.perf_counter() - started
    print("TEST_CLEANUP=OK")
    print("ENGINE_DISPOSE_SAME_EVENT_LOOP=OK")
    print(f"TOTAL_EXECUTION_TIME={elapsed:.3f}s")
    print("WAREHOUSE_LOCATION_MANAGEMENT_POSTGRES_E2E_OK")


if __name__ == "__main__":
    try:
        asyncio.run(child_main())
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            _before_cursor_execute,
        )
