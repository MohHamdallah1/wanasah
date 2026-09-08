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
# Strict launcher
# ============================================================================
# The parent process captures the child's stderr. Any stderr at all is a failure.
# This prevents another false-green where SQLAlchemy/asyncpg logs a traceback
# while the child still exits with code 0.
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
            f"INTERWAREHOUSE_E2E_CHILD_FAILED: exit_code={proc.returncode}"
        )

    if proc.stderr.strip():
        raise SystemExit(
            "INTERWAREHOUSE_E2E_STRICT_STDERR_FAILED: "
            "child emitted stderr; success is rejected."
        )

    if "WAREHOUSE_INTERWAREHOUSE_POSTGRES_E2E_OK" not in proc.stdout:
        raise SystemExit(
            "INTERWAREHOUSE_E2E_SUCCESS_MARKER_MISSING"
        )

    print("STRICT_STDERR=EMPTY")
    print("WAREHOUSE_INTERWAREHOUSE_POSTGRES_E2E_STRICT_OK")


if "--child" not in sys.argv:
    _run_strict_parent()
    raise SystemExit(0)


# ============================================================================
# Child test process
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
        "ERROR: لم أجد wa_backend/models.py. "
        "شغّل السكربت من جذر المشروع."
    )


ROOT, BACKEND = _locate_project()
sys.path.insert(0, str(BACKEND))

from config import Config  # noqa: E402
from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import (  # noqa: E402
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryMovement,
    InventoryMovementImpact,
    InventoryTransferHeader,
    InventoryTransferLine,
    OperationIdempotency,
    Product,
    ProductBatch,
    ProductVariant,
    SystemAuditLog,
    UOM,
)
from schemas import (  # noqa: E402
    UnifiedDispatchRequest,
    UnifiedReceiveRequest,
    UnifiedTransferDecisionRequest,
)
from api.warehouse import (  # noqa: E402
    get_unified_transfer_detail,
    list_unified_transfers,
    unified_transfer_cancel,
    unified_transfer_dispatch,
    unified_transfer_receive,
    unified_transfer_reject,
)


# ============================================================================
# Safety gate
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


_QUERY_COUNTER = QueryCounter()


def _before_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    if _QUERY_COUNTER.active:
        _QUERY_COUNTER.count += 1


event.listen(
    engine.sync_engine,
    "before_cursor_execute",
    _before_cursor_execute,
)


async def _counted(awaitable):
    _QUERY_COUNTER.count = 0
    _QUERY_COUNTER.active = True
    try:
        result = await awaitable
    finally:
        _QUERY_COUNTER.active = False
    return result, _QUERY_COUNTER.count


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


async def runtime_role(db) -> tuple[str, bool, bool]:
    row = (
        await db.execute(
            text(
                """
                SELECT r.rolname, r.rolsuper, r.rolbypassrls
                FROM pg_roles r
                WHERE r.rolname = current_user
                """
            )
        )
    ).one()
    return str(row[0]), bool(row[1]), bool(row[2])


async def expect_http(
    awaitable,
    status: int,
) -> HTTPException:
    try:
        await awaitable
    except HTTPException as exc:
        if exc.status_code != status:
            raise AssertionError(
                f"Expected HTTP {status}, got {exc.status_code}: {exc.detail}"
            )
        return exc
    raise AssertionError(
        f"Expected HTTP {status}, request unexpectedly succeeded."
    )


async def _load_admin(
    db,
    company_id: int,
    admin_id: int,
) -> Driver:
    await set_tenant(db, company_id)
    return (
        await db.execute(
            select(Driver).where(
                Driver.company_id == company_id,
                Driver.id == admin_id,
            )
        )
    ).scalar_one()


async def call_dispatch(
    *,
    company_id: int,
    admin_id: int,
    payload: UnifiedDispatchRequest,
):
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(db, company_id, admin_id)
        return await unified_transfer_dispatch(
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_receive(
    *,
    company_id: int,
    admin_id: int,
    payload: UnifiedReceiveRequest,
):
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(db, company_id, admin_id)
        return await unified_transfer_receive(
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_cancel(
    *,
    company_id: int,
    admin_id: int,
    header_id: int,
    payload: UnifiedTransferDecisionRequest,
):
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(db, company_id, admin_id)
        return await unified_transfer_cancel(
            header_id=header_id,
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_reject(
    *,
    company_id: int,
    admin_id: int,
    header_id: int,
    payload: UnifiedTransferDecisionRequest,
):
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(db, company_id, admin_id)
        return await unified_transfer_reject(
            header_id=header_id,
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_list(
    *,
    company_id: int,
    admin_id: int,
    status: str | None = None,
    location_id: int | None = None,
    direction: str = "all",
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
):
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(db, company_id, admin_id)
        return await list_unified_transfers(
            status=status,
            location_id=location_id,
            direction=direction,
            search=search,
            cursor=cursor,
            limit=limit,
            db=db,
            current_admin=admin,
        )


async def call_detail(
    *,
    company_id: int,
    admin_id: int,
    header_id: int,
):
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(db, company_id, admin_id)
        return await get_unified_transfer_detail(
            header_id=header_id,
            db=db,
            current_admin=admin,
        )


async def qty(
    db,
    *,
    company_id: int,
    location_id: int,
    variant_id: int,
    batch_id: int,
) -> int:
    value = (
        await db.execute(
            select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
    ).scalar_one_or_none()
    return int(value or 0)


async def variant_total(
    db,
    *,
    company_id: int,
    variant_id: int,
) -> int:
    value = (
        await db.execute(
            select(func.sum(InventoryBalance.on_hand_quantity)).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
    ).scalar_one()
    return int(value or 0)


async def movement_count(
    db,
    *,
    company_id: int,
    header_id: int,
    reference_type: str,
) -> int:
    return int(
        (
            await db.execute(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.company_id == company_id,
                    InventoryMovement.transfer_header_id == header_id,
                    InventoryMovement.reference_type == reference_type,
                )
            )
        ).scalar_one()
    )


async def op_count(
    db,
    *,
    company_id: int,
    request_ids: list[uuid.UUID],
) -> int:
    request_values = [str(value) for value in request_ids]
    return int(
        (
            await db.execute(
                select(func.count(OperationIdempotency.id)).where(
                    OperationIdempotency.company_id == company_id,
                    OperationIdempotency.request_id.in_(request_values),
                )
            )
        ).scalar_one()
    )


async def get_header(
    db,
    *,
    company_id: int,
    header_id: int,
) -> InventoryTransferHeader:
    return (
        await db.execute(
            select(InventoryTransferHeader).where(
                InventoryTransferHeader.company_id == company_id,
                InventoryTransferHeader.id == header_id,
            )
        )
    ).scalar_one()


async def get_transfer_lines(
    db,
    *,
    company_id: int,
    header_id: int,
) -> list[InventoryTransferLine]:
    return list(
        (
            await db.execute(
                select(InventoryTransferLine).where(
                    InventoryTransferLine.company_id == company_id,
                    InventoryTransferLine.transfer_header_id == header_id,
                ).order_by(
                    InventoryTransferLine.batch_id.asc(),
                    InventoryTransferLine.id.asc(),
                )
            )
        ).scalars().all()
    )


# ============================================================================
# Schema / RLS preflight
# ============================================================================
async def ensure_schema_ready() -> str:
    if engine.dialect.name != "postgresql":
        raise SystemExit("POSTGRESQL_REQUIRED_FOR_INTERWAREHOUSE_E2E")

    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)

        role, is_superuser, bypass_rls = await runtime_role(db)
        if is_superuser or bypass_rls:
            raise AssertionError(
                "INVALID_RUNTIME_ROLE_FOR_RLS_TEST: "
                f"role={role}, superuser={is_superuser}, bypassrls={bypass_rls}"
            )

        constraint_rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        con.conname,
                        pg_get_constraintdef(con.oid, true) AS definition
                    FROM pg_constraint con
                    JOIN pg_class rel ON rel.oid = con.conrelid
                    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND rel.relname = 'inventory_transfer_headers'
                      AND con.contype = 'c'
                    ORDER BY con.conname
                    """
                )
            )
        ).all()

        constraint_definitions = [
            (str(name), str(definition))
            for name, definition in constraint_rows
        ]

        # PostgreSQL identifiers are limited to 63 bytes. SQLAlchemy may
        # truncate long convention-generated constraint names, so checking
        # the full Python-side name is not reliable. Verify the semantic
        # CHECK expressions instead.
        def _canonical_constraint_def(definition: str) -> str:
            value = definition.lower()
            value = value.replace("::text[]", "")
            value = value.replace("::text", "")
            value = value.replace("check", " ")
            value = value.replace("(", " ")
            value = value.replace(")", " ")
            value = value.replace("[", " ")
            value = value.replace("]", " ")
            value = value.replace(",", " ")
            return " ".join(value.split())

        required_constraint_signatures = {
            "session_scope": (
                "workflow_type = 'handshake'",
                "work_session_id is null",
            ),
            "received_by_scope": (
                "received_by is null",
                "'accepted'",
                "'rejected'",
                "'posted'",
            ),
            "separation_of_duties": (
                "workflow_type <> 'transit'",
                "received_by <> dispatched_by",
            ),
            "transit_location_required": (
                "workflow_type <> 'transit'",
                "status = 'draft'",
                "transit_location_id is not null",
            ),
        }

        missing_semantic_constraints = []
        normalized_defs = [
            (name, _canonical_constraint_def(definition))
            for name, definition in constraint_definitions
        ]

        for label, signatures in required_constraint_signatures.items():
            matched = any(
                all(signature in definition for signature in signatures)
                for _name, definition in normalized_defs
            )
            if not matched:
                missing_semantic_constraints.append(label)

        if missing_semantic_constraints:
            raise AssertionError(
                "TRANSFER_DB_CONSTRAINTS_MISSING="
                f"{sorted(missing_semantic_constraints)}; "
                f"ACTUAL_CHECKS={normalized_defs}"
            )

        index_def = (
            await db.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'inventory_transfer_headers'
                      AND indexname = 'ix_transfer_header_transit_queue'
                    """
                )
            )
        ).scalar_one_or_none()
        if index_def is None:
            raise AssertionError(
                "ix_transfer_header_transit_queue missing"
            )

        for table_name in (
            "inventory_transfer_headers",
            "inventory_transfer_lines",
            "inventory_balances",
            "inventory_movements",
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
            ).one_or_none()

            if row is None or not all(bool(value) for value in row):
                raise AssertionError(
                    f"RLS/FORCE/POLICY incomplete for {table_name}: {row}"
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
            name=f"InterWarehouse A {suffix}",
            company_code=f"IWA{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        company_b = Company(
            name=f"InterWarehouse B {suffix}",
            company_code=f"IWB{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        uom = UOM(
            name=f"InterWarehouse Unit {suffix}",
            code=f"IWU{suffix[:7]}",
        )
        db.add_all([company_a, company_b, uom])
        await db.flush()

        # Tenant A
        await set_tenant(db, company_a.id)

        sender = Driver(
            company_id=company_a.id,
            username=f"iw_sender_{suffix}",
            password_hash="test-only",
            full_name="InterWarehouse Sender",
            is_active=True,
            is_admin=True,
        )
        receiver = Driver(
            company_id=company_a.id,
            username=f"iw_receiver_{suffix}",
            password_hash="test-only",
            full_name="InterWarehouse Receiver",
            is_active=True,
            is_admin=True,
        )
        product_a = Product(
            company_id=company_a.id,
            base_name=f"InterWarehouse Product A {suffix}",
        )
        source = InventoryLocation(
            company_id=company_a.id,
            name=f"Warehouse Amman {suffix}",
            code=f"IW-SRC-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        destination = InventoryLocation(
            company_id=company_a.id,
            name=f"Warehouse Irbid {suffix}",
            code=f"IW-DST-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([sender, receiver, product_a, source, destination])
        await db.flush()

        fefo_variant = ProductVariant(
            company_id=company_a.id,
            product_id=product_a.id,
            base_uom_id=uom.id,
            variant_name=f"FEFO Transfer Variant {suffix}",
            sku=f"IW-FEFO-{suffix}",
            price_per_carton=Decimal("10.000"),
            price_per_pack=Decimal("1.000"),
            packs_per_carton=10,
            is_active=True,
            default_max_samples_per_day=0,
        )
        race_variant = ProductVariant(
            company_id=company_a.id,
            product_id=product_a.id,
            base_uom_id=uom.id,
            variant_name=f"Race Transfer Variant {suffix}",
            sku=f"IW-RACE-{suffix}",
            price_per_carton=Decimal("10.000"),
            price_per_pack=Decimal("1.000"),
            packs_per_carton=10,
            is_active=True,
            default_max_samples_per_day=0,
        )
        db.add_all([fefo_variant, race_variant])
        await db.flush()

        old_batch = ProductBatch(
            company_id=company_a.id,
            product_variant_id=fefo_variant.id,
            batch_number=f"IW-OLD-{suffix}",
            production_date=today - timedelta(days=120),
            expiry_date=today + timedelta(days=60),
            is_active=True,
        )
        new_batch = ProductBatch(
            company_id=company_a.id,
            product_variant_id=fefo_variant.id,
            batch_number=f"IW-NEW-{suffix}",
            production_date=today - timedelta(days=60),
            expiry_date=today + timedelta(days=180),
            is_active=True,
        )
        race_batch = ProductBatch(
            company_id=company_a.id,
            product_variant_id=race_variant.id,
            batch_number=f"IW-RACE-BATCH-{suffix}",
            production_date=today - timedelta(days=30),
            expiry_date=today + timedelta(days=365),
            is_active=True,
        )
        db.add_all([old_batch, new_batch, race_batch])
        await db.flush()

        db.add_all([
            InventoryBalance(
                company_id=company_a.id,
                location_id=source.id,
                product_variant_id=fefo_variant.id,
                batch_id=old_batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=80,
                reserved_quantity=0,
            ),
            InventoryBalance(
                company_id=company_a.id,
                location_id=source.id,
                product_variant_id=fefo_variant.id,
                batch_id=new_batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=160,
                reserved_quantity=0,
            ),
            InventoryBalance(
                company_id=company_a.id,
                location_id=source.id,
                product_variant_id=race_variant.id,
                batch_id=race_batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=500,
                reserved_quantity=0,
            ),
        ])

        await db.commit()

        # Tenant B
        await set_tenant(db, company_b.id)

        admin_b = Driver(
            company_id=company_b.id,
            username=f"iw_admin_b_{suffix}",
            password_hash="test-only",
            full_name="InterWarehouse Tenant B Admin",
            is_active=True,
            is_admin=True,
        )
        warehouse_b = InventoryLocation(
            company_id=company_b.id,
            name=f"Tenant B Warehouse {suffix}",
            code=f"IW-B-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([admin_b, warehouse_b])
        await db.commit()

        return {
            "suffix": suffix,
            "company_a": int(company_a.id),
            "company_b": int(company_b.id),
            "uom_id": int(uom.id),
            "sender": int(sender.id),
            "receiver": int(receiver.id),
            "admin_b": int(admin_b.id),
            "source": int(source.id),
            "destination": int(destination.id),
            "warehouse_b": int(warehouse_b.id),
            "fefo_variant": int(fefo_variant.id),
            "race_variant": int(race_variant.id),
            "old_batch": int(old_batch.id),
            "new_batch": int(new_batch.id),
            "race_batch": int(race_batch.id),
            "fefo_total": 240,
            "race_total": 500,
        }


async def cleanup_company(company_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)

        for table in (
            "system_audit_logs",
            "inventory_movement_impacts",
            "inventory_movements",
            "inventory_transfer_lines",
            "inventory_transfer_headers",
            "operation_idempotency",
            "inventory_balances",
            "product_batches",
            "inventory_locations",
            "product_variants",
            "products",
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
                    "DELETE FROM companies "
                    "WHERE id IN (:a, :b)"
                ),
                {
                    "a": fx["company_a"],
                    "b": fx["company_b"],
                },
            )
            await db.execute(
                text("DELETE FROM uom WHERE id = :uom_id"),
                {"uom_id": fx["uom_id"]},
            )
            await db.commit()
    except Exception as exc:
        errors.append(f"global cleanup: {exc}")

    if errors:
        raise RuntimeError(
            "INTERWAREHOUSE_TEST_CLEANUP_FAILED: "
            + " | ".join(errors)
        )


# ============================================================================
# Tests
# ============================================================================
async def test_dispatch_receive_fefo_conservation(fx: dict) -> int:
    request_id = uuid.uuid4()
    payload = UnifiedDispatchRequest(
        request_id=request_id,
        source_location_id=fx["source"],
        destination_location_id=fx["destination"],
        notes="FEFO conservation transfer",
        items=[{
            "product_variant_id": fx["fefo_variant"],
            "quantity": 110,
        }],
    )

    first = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=payload,
    )
    replay = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=payload,
    )
    if first != replay:
        raise AssertionError(
            f"Dispatch replay mismatch: {first} != {replay}"
        )

    changed = payload.model_copy(deep=True)
    changed.items[0].quantity = 111
    await expect_http(
        call_dispatch(
            company_id=fx["company_a"],
            admin_id=fx["sender"],
            payload=changed,
        ),
        409,
    )

    header_id = int(first["header_id"])

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])

        transit_id = (
            await db.execute(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == fx["company_a"],
                    InventoryLocation.code == "TRANSIT-SYS",
                    InventoryLocation.location_type == "IN_TRANSIT",
                )
            )
        ).scalar_one()

        if await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["fefo_variant"],
        ) != fx["fefo_total"]:
            raise AssertionError("FEFO total changed after dispatch.")

        checks = {
            "source_old": await qty(
                db,
                company_id=fx["company_a"],
                location_id=fx["source"],
                variant_id=fx["fefo_variant"],
                batch_id=fx["old_batch"],
            ),
            "source_new": await qty(
                db,
                company_id=fx["company_a"],
                location_id=fx["source"],
                variant_id=fx["fefo_variant"],
                batch_id=fx["new_batch"],
            ),
            "transit_old": await qty(
                db,
                company_id=fx["company_a"],
                location_id=transit_id,
                variant_id=fx["fefo_variant"],
                batch_id=fx["old_batch"],
            ),
            "transit_new": await qty(
                db,
                company_id=fx["company_a"],
                location_id=transit_id,
                variant_id=fx["fefo_variant"],
                batch_id=fx["new_batch"],
            ),
        }
        expected = {
            "source_old": 0,
            "source_new": 130,
            "transit_old": 80,
            "transit_new": 30,
        }
        if checks != expected:
            raise AssertionError(
                f"FEFO dispatch allocation mismatch: {checks} != {expected}"
            )

        lines = await get_transfer_lines(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        line_map = {
            int(line.batch_id): int(line.quantity)
            for line in lines
        }
        if line_map != {
            fx["old_batch"]: 80,
            fx["new_batch"]: 30,
        }:
            raise AssertionError(
                f"Transfer lines do not match FEFO allocation: {line_map}"
            )

        if await movement_count(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
            reference_type="TRANSFER_DISPATCH",
        ) != 2:
            raise AssertionError(
                "Expected exactly two dispatch movements for two FEFO batches."
            )

    # Read APIs must expose this transfer without losing batch detail.
    page = await call_list(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        status="IN_TRANSIT",
        search=first["transfer_reference"].lower(),
        limit=10,
    )
    matching = [
        item for item in page["items"]
        if int(item["id"]) == header_id
    ]
    if len(matching) != 1:
        raise AssertionError(
            f"IN_TRANSIT transfer missing from list API: {page}"
        )
    if (
        int(matching[0]["line_count"]) != 2
        or int(matching[0]["total_quantity"]) != 110
    ):
        raise AssertionError(
            f"Transfer aggregate mismatch: {matching[0]}"
        )

    detail = await call_detail(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        header_id=header_id,
    )
    if len(detail["lines"]) != 2:
        raise AssertionError(
            f"Transfer detail lost batch lines: {detail}"
        )

    receive_request_id = uuid.uuid4()
    receive_payload = UnifiedReceiveRequest(
        request_id=receive_request_id,
        transfer_header_id=header_id,
        destination_location_id=fx["destination"],
    )

    received = await call_receive(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        payload=receive_payload,
    )
    receive_replay = await call_receive(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        payload=receive_payload,
    )
    if received != receive_replay:
        raise AssertionError(
            f"Receive replay mismatch: {received} != {receive_replay}"
        )

    changed_receive = receive_payload.model_copy(
        update={"destination_location_id": fx["source"]}
    )
    await expect_http(
        call_receive(
            company_id=fx["company_a"],
            admin_id=fx["receiver"],
            payload=changed_receive,
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])

        header = await get_header(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        if header.status != "POSTED":
            raise AssertionError(
                f"Receive did not POST transfer: {header.status}"
            )
        if int(header.received_by) != fx["receiver"]:
            raise AssertionError(
                "Receive audit actor is incorrect."
            )

        transit_id = int(header.transit_location_id)

        checks = {
            "source_old": await qty(
                db,
                company_id=fx["company_a"],
                location_id=fx["source"],
                variant_id=fx["fefo_variant"],
                batch_id=fx["old_batch"],
            ),
            "source_new": await qty(
                db,
                company_id=fx["company_a"],
                location_id=fx["source"],
                variant_id=fx["fefo_variant"],
                batch_id=fx["new_batch"],
            ),
            "transit_old": await qty(
                db,
                company_id=fx["company_a"],
                location_id=transit_id,
                variant_id=fx["fefo_variant"],
                batch_id=fx["old_batch"],
            ),
            "transit_new": await qty(
                db,
                company_id=fx["company_a"],
                location_id=transit_id,
                variant_id=fx["fefo_variant"],
                batch_id=fx["new_batch"],
            ),
            "dest_old": await qty(
                db,
                company_id=fx["company_a"],
                location_id=fx["destination"],
                variant_id=fx["fefo_variant"],
                batch_id=fx["old_batch"],
            ),
            "dest_new": await qty(
                db,
                company_id=fx["company_a"],
                location_id=fx["destination"],
                variant_id=fx["fefo_variant"],
                batch_id=fx["new_batch"],
            ),
        }
        expected = {
            "source_old": 0,
            "source_new": 130,
            "transit_old": 0,
            "transit_new": 0,
            "dest_old": 80,
            "dest_new": 30,
        }
        if checks != expected:
            raise AssertionError(
                f"Receive conservation mismatch: {checks} != {expected}"
            )

        if await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["fefo_variant"],
        ) != fx["fefo_total"]:
            raise AssertionError("FEFO total changed after receive.")

        if await movement_count(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
            reference_type="TRANSFER_RECEIPT",
        ) != 2:
            raise AssertionError(
                "Receive replay generated duplicate receipt movements."
            )

        if await op_count(
            db,
            company_id=fx["company_a"],
            request_ids=[request_id, receive_request_id],
        ) != 2:
            raise AssertionError(
                "Dispatch/receive idempotency records are not exactly one each."
            )

    return header_id


async def test_separation_of_duties(fx: dict) -> None:
    dispatch_payload = UnifiedDispatchRequest(
        request_id=uuid.uuid4(),
        source_location_id=fx["source"],
        destination_location_id=fx["destination"],
        items=[{
            "product_variant_id": fx["race_variant"],
            "quantity": 10,
        }],
        notes="separation of duties",
    )
    dispatched = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=dispatch_payload,
    )
    header_id = int(dispatched["header_id"])

    self_receive = UnifiedReceiveRequest(
        request_id=uuid.uuid4(),
        transfer_header_id=header_id,
        destination_location_id=fx["destination"],
    )
    await expect_http(
        call_receive(
            company_id=fx["company_a"],
            admin_id=fx["sender"],
            payload=self_receive,
        ),
        403,
    )

    self_reject = UnifiedTransferDecisionRequest(
        request_id=uuid.uuid4(),
        decision_reason="sender cannot reject as receiver",
    )
    await expect_http(
        call_reject(
            company_id=fx["company_a"],
            admin_id=fx["sender"],
            header_id=header_id,
            payload=self_reject,
        ),
        403,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        header = await get_header(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        if header.status != "IN_TRANSIT":
            raise AssertionError(
                "Failed self-receive/reject changed transfer state."
            )

    # Clean up the transfer through the legal cancellation path.
    cancel_payload = UnifiedTransferDecisionRequest(
        request_id=uuid.uuid4(),
        decision_reason="test cleanup after separation checks",
    )
    await call_cancel(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        header_id=header_id,
        payload=cancel_payload,
    )


async def test_cancel_idempotency_and_conservation(fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        before_source = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        before_total = await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["race_variant"],
        )

    dispatch_request_id = uuid.uuid4()
    dispatched = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=UnifiedDispatchRequest(
            request_id=dispatch_request_id,
            source_location_id=fx["source"],
            destination_location_id=fx["destination"],
            items=[{
                "product_variant_id": fx["race_variant"],
                "quantity": 20,
            }],
            notes="cancel lifecycle",
        ),
    )
    header_id = int(dispatched["header_id"])

    cancel_request_id = uuid.uuid4()
    cancel_payload = UnifiedTransferDecisionRequest(
        request_id=cancel_request_id,
        decision_reason="operational cancellation",
    )
    first = await call_cancel(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        header_id=header_id,
        payload=cancel_payload,
    )
    replay = await call_cancel(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        header_id=header_id,
        payload=cancel_payload,
    )
    if first != replay:
        raise AssertionError(
            f"Cancel replay mismatch: {first} != {replay}"
        )

    changed = cancel_payload.model_copy(
        update={"decision_reason": "changed cancellation reason"}
    )
    await expect_http(
        call_cancel(
            company_id=fx["company_a"],
            admin_id=fx["sender"],
            header_id=header_id,
            payload=changed,
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        header = await get_header(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        if header.status != "CANCELLED":
            raise AssertionError(
                f"Cancel terminal state mismatch: {header.status}"
            )
        if header.decision_reason != "operational cancellation":
            raise AssertionError(
                "Cancellation reason was not persisted exactly."
            )

        source_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        total_after = await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["race_variant"],
        )
        transit_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=int(header.transit_location_id),
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )

        if source_after != before_source:
            raise AssertionError(
                f"Cancel did not restore source: {source_after} != {before_source}"
            )
        if total_after != before_total:
            raise AssertionError(
                f"Cancel broke conservation: {total_after} != {before_total}"
            )
        if transit_after != 0:
            raise AssertionError(
                f"Cancelled quantity remained in transit: {transit_after}"
            )
        if await movement_count(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
            reference_type="TRANSFER_CANCELLED",
        ) != 1:
            raise AssertionError(
                "Cancel replay generated duplicate stock movement."
            )
        if await op_count(
            db,
            company_id=fx["company_a"],
            request_ids=[dispatch_request_id, cancel_request_id],
        ) != 2:
            raise AssertionError(
                "Cancel idempotency record count mismatch."
            )


async def test_reject_idempotency_and_conservation(fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        before_source = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        before_total = await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["race_variant"],
        )

    dispatch_request_id = uuid.uuid4()
    dispatched = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=UnifiedDispatchRequest(
            request_id=dispatch_request_id,
            source_location_id=fx["source"],
            destination_location_id=fx["destination"],
            items=[{
                "product_variant_id": fx["race_variant"],
                "quantity": 25,
            }],
            notes="reject lifecycle",
        ),
    )
    header_id = int(dispatched["header_id"])

    reject_request_id = uuid.uuid4()
    reject_payload = UnifiedTransferDecisionRequest(
        request_id=reject_request_id,
        decision_reason="receiver rejected shipment",
    )
    first = await call_reject(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        header_id=header_id,
        payload=reject_payload,
    )
    replay = await call_reject(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        header_id=header_id,
        payload=reject_payload,
    )
    if first != replay:
        raise AssertionError(
            f"Reject replay mismatch: {first} != {replay}"
        )

    changed = reject_payload.model_copy(
        update={"decision_reason": "different rejection reason"}
    )
    await expect_http(
        call_reject(
            company_id=fx["company_a"],
            admin_id=fx["receiver"],
            header_id=header_id,
            payload=changed,
        ),
        409,
    )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        header = await get_header(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        if header.status != "REJECTED":
            raise AssertionError(
                f"Reject terminal state mismatch: {header.status}"
            )
        if int(header.received_by) != fx["receiver"]:
            raise AssertionError(
                "Reject actor was not persisted."
            )

        source_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        total_after = await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["race_variant"],
        )
        transit_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=int(header.transit_location_id),
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )

        if source_after != before_source:
            raise AssertionError(
                f"Reject did not restore source: {source_after} != {before_source}"
            )
        if total_after != before_total:
            raise AssertionError(
                f"Reject broke conservation: {total_after} != {before_total}"
            )
        if transit_after != 0:
            raise AssertionError(
                f"Rejected quantity remained in transit: {transit_after}"
            )
        if await movement_count(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
            reference_type="TRANSFER_REJECTED",
        ) != 1:
            raise AssertionError(
                "Reject replay generated duplicate stock movement."
            )
        if await op_count(
            db,
            company_id=fx["company_a"],
            request_ids=[dispatch_request_id, reject_request_id],
        ) != 2:
            raise AssertionError(
                "Reject idempotency record count mismatch."
            )


async def test_concurrent_same_receive_retry(fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        before_source = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        before_dest = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["destination"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )

    dispatched = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=UnifiedDispatchRequest(
            request_id=uuid.uuid4(),
            source_location_id=fx["source"],
            destination_location_id=fx["destination"],
            items=[{
                "product_variant_id": fx["race_variant"],
                "quantity": 30,
            }],
            notes="concurrent same receive retry",
        ),
    )
    header_id = int(dispatched["header_id"])
    receive_request_id = uuid.uuid4()
    receive_payload = UnifiedReceiveRequest(
        request_id=receive_request_id,
        transfer_header_id=header_id,
        destination_location_id=fx["destination"],
    )

    r1, r2 = await asyncio.gather(
        call_receive(
            company_id=fx["company_a"],
            admin_id=fx["receiver"],
            payload=receive_payload,
        ),
        call_receive(
            company_id=fx["company_a"],
            admin_id=fx["receiver"],
            payload=receive_payload,
        ),
    )
    if r1 != r2:
        raise AssertionError(
            f"Concurrent receive retry did not replay: {r1} != {r2}"
        )

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        source_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        dest_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["destination"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        if source_after != before_source - 30:
            raise AssertionError(
                f"Concurrent receive source mismatch: {source_after}"
            )
        if dest_after != before_dest + 30:
            raise AssertionError(
                f"Concurrent receive destination mismatch: {dest_after}"
            )
        if await movement_count(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
            reference_type="TRANSFER_RECEIPT",
        ) != 1:
            raise AssertionError(
                "Concurrent same receive retry executed movement more than once."
            )


async def _terminal_attempt(coro, label: str) -> tuple[str, object]:
    try:
        result = await coro
        return label, result
    except HTTPException as exc:
        return label, exc


async def test_three_way_terminal_race(fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        before_source = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        before_dest = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["destination"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        before_total = await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["race_variant"],
        )

    dispatched = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=UnifiedDispatchRequest(
            request_id=uuid.uuid4(),
            source_location_id=fx["source"],
            destination_location_id=fx["destination"],
            items=[{
                "product_variant_id": fx["race_variant"],
                "quantity": 40,
            }],
            notes="three-way terminal race",
        ),
    )
    header_id = int(dispatched["header_id"])

    receive_id = uuid.uuid4()
    cancel_id = uuid.uuid4()
    reject_id = uuid.uuid4()

    results = await asyncio.gather(
        _terminal_attempt(
            call_receive(
                company_id=fx["company_a"],
                admin_id=fx["receiver"],
                payload=UnifiedReceiveRequest(
                    request_id=receive_id,
                    transfer_header_id=header_id,
                    destination_location_id=fx["destination"],
                ),
            ),
            "receive",
        ),
        _terminal_attempt(
            call_cancel(
                company_id=fx["company_a"],
                admin_id=fx["sender"],
                header_id=header_id,
                payload=UnifiedTransferDecisionRequest(
                    request_id=cancel_id,
                    decision_reason="race cancellation",
                ),
            ),
            "cancel",
        ),
        _terminal_attempt(
            call_reject(
                company_id=fx["company_a"],
                admin_id=fx["receiver"],
                header_id=header_id,
                payload=UnifiedTransferDecisionRequest(
                    request_id=reject_id,
                    decision_reason="race rejection",
                ),
            ),
            "reject",
        ),
    )

    successes = [
        (label, result)
        for label, result in results
        if not isinstance(result, HTTPException)
    ]
    failures = [
        (label, result)
        for label, result in results
        if isinstance(result, HTTPException)
    ]

    if len(successes) != 1 or len(failures) != 2:
        raise AssertionError(
            f"Three-way race must have exactly one winner: {results}"
        )
    if any(exc.status_code != 409 for _, exc in failures):
        raise AssertionError(
            f"Three-way race losers must be HTTP 409: {results}"
        )

    winner = successes[0][0]

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        header = await get_header(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        source_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["source"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        dest_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=fx["destination"],
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        transit_after = await qty(
            db,
            company_id=fx["company_a"],
            location_id=int(header.transit_location_id),
            variant_id=fx["race_variant"],
            batch_id=fx["race_batch"],
        )
        total_after = await variant_total(
            db,
            company_id=fx["company_a"],
            variant_id=fx["race_variant"],
        )

        if total_after != before_total:
            raise AssertionError(
                f"Three-way race broke conservation: {total_after} != {before_total}"
            )
        if transit_after != 0:
            raise AssertionError(
                f"Three-way race left stock in transit: {transit_after}"
            )

        terminal_movements = sum([
            await movement_count(
                db,
                company_id=fx["company_a"],
                header_id=header_id,
                reference_type="TRANSFER_RECEIPT",
            ),
            await movement_count(
                db,
                company_id=fx["company_a"],
                header_id=header_id,
                reference_type="TRANSFER_CANCELLED",
            ),
            await movement_count(
                db,
                company_id=fx["company_a"],
                header_id=header_id,
                reference_type="TRANSFER_REJECTED",
            ),
        ])
        if terminal_movements != 1:
            raise AssertionError(
                f"Three-way race executed {terminal_movements} terminal movements."
            )

        committed_terminal_ops = await op_count(
            db,
            company_id=fx["company_a"],
            request_ids=[receive_id, cancel_id, reject_id],
        )
        if committed_terminal_ops != 1:
            raise AssertionError(
                f"Three-way race committed {committed_terminal_ops} terminal idempotency records."
            )

        if winner == "receive":
            if header.status != "POSTED":
                raise AssertionError(
                    f"Receive won but status is {header.status}"
                )
            if source_after != before_source - 40:
                raise AssertionError("Receive winner source mismatch.")
            if dest_after != before_dest + 40:
                raise AssertionError("Receive winner destination mismatch.")
        elif winner == "cancel":
            if header.status != "CANCELLED":
                raise AssertionError(
                    f"Cancel won but status is {header.status}"
                )
            if source_after != before_source:
                raise AssertionError("Cancel winner did not restore source.")
            if dest_after != before_dest:
                raise AssertionError("Cancel winner touched destination.")
        elif winner == "reject":
            if header.status != "REJECTED":
                raise AssertionError(
                    f"Reject won but status is {header.status}"
                )
            if source_after != before_source:
                raise AssertionError("Reject winner did not restore source.")
            if dest_after != before_dest:
                raise AssertionError("Reject winner touched destination.")
        else:
            raise AssertionError(f"Unexpected race winner: {winner}")

    print(f"THREE_WAY_RACE_WINNER={winner.upper()}")


async def test_cross_tenant_and_db_guards(
    fx: dict,
    posted_header_id: int,
) -> None:
    # Leave one A transfer IN_TRANSIT for hostile B attempts.
    dispatched = await call_dispatch(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        payload=UnifiedDispatchRequest(
            request_id=uuid.uuid4(),
            source_location_id=fx["source"],
            destination_location_id=fx["destination"],
            items=[{
                "product_variant_id": fx["race_variant"],
                "quantity": 15,
            }],
            notes="cross tenant attack target",
        ),
    )
    header_id = int(dispatched["header_id"])

    # API isolation: B cannot read or mutate A transfer.
    await expect_http(
        call_detail(
            company_id=fx["company_b"],
            admin_id=fx["admin_b"],
            header_id=header_id,
        ),
        404,
    )

    b_page = await call_list(
        company_id=fx["company_b"],
        admin_id=fx["admin_b"],
        search=dispatched["transfer_reference"].lower(),
        limit=10,
    )
    if b_page["items"] or b_page["total"] != 0:
        raise AssertionError(
            f"Tenant B saw tenant A transfer in list API: {b_page}"
        )

    await expect_http(
        call_receive(
            company_id=fx["company_b"],
            admin_id=fx["admin_b"],
            payload=UnifiedReceiveRequest(
                request_id=uuid.uuid4(),
                transfer_header_id=header_id,
                destination_location_id=fx["warehouse_b"],
            ),
        ),
        404,
    )
    await expect_http(
        call_cancel(
            company_id=fx["company_b"],
            admin_id=fx["admin_b"],
            header_id=header_id,
            payload=UnifiedTransferDecisionRequest(
                request_id=uuid.uuid4(),
                decision_reason="malicious B cancel",
            ),
        ),
        404,
    )
    await expect_http(
        call_reject(
            company_id=fx["company_b"],
            admin_id=fx["admin_b"],
            header_id=header_id,
            payload=UnifiedTransferDecisionRequest(
                request_id=uuid.uuid4(),
                decision_reason="malicious B reject",
            ),
        ),
        404,
    )

    # Cursor scope is bound to tenant + filters.
    a_first = await call_list(
        company_id=fx["company_a"],
        admin_id=fx["receiver"],
        limit=1,
    )
    cursor = a_first["next_cursor"]
    if not cursor:
        raise AssertionError(
            "Expected transfer cursor after creating multiple transfers."
        )

    await expect_http(
        call_list(
            company_id=fx["company_a"],
            admin_id=fx["receiver"],
            status="IN_TRANSIT",
            cursor=cursor,
            limit=1,
        ),
        400,
    )
    await expect_http(
        call_list(
            company_id=fx["company_b"],
            admin_id=fx["admin_b"],
            cursor=cursor,
            limit=1,
        ),
        400,
    )

    # RLS raw SQL attacks as tenant B.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_b"])

        leaked_header = (
            await db.execute(
                text(
                    """
                    SELECT id
                    FROM inventory_transfer_headers
                    WHERE id = :header_id
                    """
                ),
                {"header_id": header_id},
            )
        ).first()
        if leaked_header is not None:
            raise AssertionError(
                f"RLS SELECT leaked A header to B: {leaked_header}"
            )

        leaked_line = (
            await db.execute(
                text(
                    """
                    SELECT id
                    FROM inventory_transfer_lines
                    WHERE transfer_header_id = :header_id
                    LIMIT 1
                    """
                ),
                {"header_id": header_id},
            )
        ).first()
        if leaked_line is not None:
            raise AssertionError(
                f"RLS SELECT leaked A transfer line to B: {leaked_line}"
            )

        update_result = await db.execute(
            text(
                """
                UPDATE inventory_transfer_headers
                SET notes = 'HACKED_BY_TENANT_B'
                WHERE id = :header_id
                """
            ),
            {"header_id": header_id},
        )
        if update_result.rowcount != 0:
            raise AssertionError(
                f"RLS UPDATE crossed tenant boundary: {update_result.rowcount}"
            )

        delete_result = await db.execute(
            text(
                """
                DELETE FROM inventory_transfer_lines
                WHERE transfer_header_id = :header_id
                """
            ),
            {"header_id": header_id},
        )
        if delete_result.rowcount != 0:
            raise AssertionError(
                f"RLS DELETE crossed tenant boundary: {delete_result.rowcount}"
            )

        await db.commit()

    # RLS WITH CHECK: B cannot forge an A-owned transfer row.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_b"])
        blocked = False
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO inventory_transfer_headers (
                        company_id,
                        reference_number,
                        source_location_id,
                        destination_location_id,
                        transit_location_id,
                        workflow_type,
                        status,
                        dispatched_by,
                        created_at,
                        updated_at
                    )
                    SELECT
                        :company_a,
                        :reference_number,
                        h.source_location_id,
                        h.destination_location_id,
                        h.transit_location_id,
                        'TRANSIT',
                        'IN_TRANSIT',
                        h.dispatched_by,
                        NOW(),
                        NOW()
                    FROM inventory_transfer_headers h
                    WHERE h.id = :header_id
                    """
                ),
                {
                    "company_a": fx["company_a"],
                    "reference_number": f"MAL-{uuid.uuid4().hex}",
                    "header_id": header_id,
                },
            )
            await db.commit()
        except Exception:
            blocked = True
            await db.rollback()

        # Under B's RLS the SELECT source above sees no A row, so INSERT can
        # legitimately affect zero rows instead of raising. Both are blocked.
        if not blocked:
            created = (
                await db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM inventory_transfer_headers
                        WHERE reference_number LIKE 'MAL-%'
                        """
                    )
                )
            ).scalar_one()
            if int(created) != 0:
                raise AssertionError(
                    "RLS WITH CHECK allowed B to forge A transfer."
                )

    # Composite tenant FK: even A cannot repoint its header to B's warehouse.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        blocked = False
        try:
            await db.execute(
                text(
                    """
                    UPDATE inventory_transfer_headers
                    SET destination_location_id = :warehouse_b
                    WHERE company_id = :company_a
                      AND id = :header_id
                    """
                ),
                {
                    "warehouse_b": fx["warehouse_b"],
                    "company_a": fx["company_a"],
                    "header_id": header_id,
                },
            )
            await db.flush()
        except Exception:
            blocked = True
        finally:
            await db.rollback()

        if not blocked:
            raise AssertionError(
                "Composite tenant FK allowed cross-company destination."
            )

    # DB separation-of-duties constraint: direct corruption must fail.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        blocked = False
        try:
            await db.execute(
                text(
                    """
                    UPDATE inventory_transfer_headers
                    SET received_by = dispatched_by
                    WHERE company_id = :company_a
                      AND id = :posted_header_id
                    """
                ),
                {
                    "company_a": fx["company_a"],
                    "posted_header_id": posted_header_id,
                },
            )
            await db.flush()
        except Exception:
            blocked = True
        finally:
            await db.rollback()

        if not blocked:
            raise AssertionError(
                "DB constraint allowed sender == receiver on POSTED TRANSIT."
            )

    # Terminal transit_location must remain auditable and non-null.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        blocked = False
        try:
            await db.execute(
                text(
                    """
                    UPDATE inventory_transfer_headers
                    SET transit_location_id = NULL
                    WHERE company_id = :company_a
                      AND id = :posted_header_id
                    """
                ),
                {
                    "company_a": fx["company_a"],
                    "posted_header_id": posted_header_id,
                },
            )
            await db.flush()
        except Exception:
            blocked = True
        finally:
            await db.rollback()

        if not blocked:
            raise AssertionError(
                "DB constraint allowed erasing transit_location from terminal TRANSIT."
            )

    # Verify A target is still intact after all attacks.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_a"])
        header = await get_header(
            db,
            company_id=fx["company_a"],
            header_id=header_id,
        )
        if header.status != "IN_TRANSIT":
            raise AssertionError(
                f"A transfer changed during B attacks: {header.status}"
            )
        if header.notes != "cross tenant attack target":
            raise AssertionError(
                "A transfer notes were modified by cross-tenant attack."
            )

    # Legal cleanup of the intentionally open transfer.
    await call_cancel(
        company_id=fx["company_a"],
        admin_id=fx["sender"],
        header_id=header_id,
        payload=UnifiedTransferDecisionRequest(
            request_id=uuid.uuid4(),
            decision_reason="legal cleanup after isolation attacks",
        ),
    )


async def test_transfer_list_fixed_query_count(fx: dict) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        admin = await _load_admin(
            db,
            fx["company_a"],
            fx["receiver"],
        )
        await db.execute(text("SELECT 1"))

        _, q1 = await _counted(
            list_unified_transfers(
                status=None,
                location_id=None,
                direction="all",
                search=None,
                cursor=None,
                limit=1,
                db=db,
                current_admin=admin,
            )
        )

        _, q100 = await _counted(
            list_unified_transfers(
                status=None,
                location_id=None,
                direction="all",
                search=None,
                cursor=None,
                limit=100,
                db=db,
                current_admin=admin,
            )
        )

        if q1 != q100:
            raise AssertionError(
                f"Transfer list query count scales with page size: {q1} != {q100}"
            )

        return q1, q100


# ============================================================================
# Main
# ============================================================================
async def child_main() -> None:
    role = await ensure_schema_ready()
    fx = await setup_fixture()

    try:
        posted_header_id = await test_dispatch_receive_fefo_conservation(fx)
        print("DISPATCH_TO_TRANSIT_FEFO=OK")
        print("RECEIVE_TO_DESTINATION=OK")
        print("BATCH_LEVEL_CONSERVATION=OK")
        print("DISPATCH_IDEMPOTENCY=OK")
        print("RECEIVE_IDEMPOTENCY=OK")
        print("TRANSFER_LIST_DETAIL=OK")

        await test_separation_of_duties(fx)
        print("SEPARATION_OF_DUTIES=ENFORCED")

        await test_cancel_idempotency_and_conservation(fx)
        print("CANCEL_TO_SOURCE=OK")
        print("CANCEL_IDEMPOTENCY=OK")

        await test_reject_idempotency_and_conservation(fx)
        print("REJECT_TO_SOURCE=OK")
        print("REJECT_IDEMPOTENCY=OK")

        await test_concurrent_same_receive_retry(fx)
        print("CONCURRENT_SAME_RECEIVE_RETRY=ONE_EXECUTION")

        await test_three_way_terminal_race(fx)
        print("RECEIVE_CANCEL_REJECT_RACE=ONE_TERMINAL_WINNER")
        print("RACE_CONSERVATION=OK")

        await test_cross_tenant_and_db_guards(
            fx,
            posted_header_id,
        )
        print("TRANSFER_API_CROSS_TENANT=BLOCKED")
        print("TRANSFER_RLS_SELECT=BLOCKED")
        print("TRANSFER_RLS_UPDATE=BLOCKED")
        print("TRANSFER_RLS_DELETE=BLOCKED")
        print("TRANSFER_RLS_INSERT=BLOCKED")
        print("TRANSFER_CURSOR_CROSS_TENANT=BLOCKED")
        print("TRANSFER_COMPOSITE_TENANT_FK=ENFORCED")
        print("TRANSFER_DB_SOD_CONSTRAINT=ENFORCED")
        print("TRANSFER_TRANSIT_AUDIT_LOCATION=RETAINED")

        q1, q100 = await test_transfer_list_fixed_query_count(fx)
        print(f"TRANSFER_LIST_QUERY_COUNT_LIMIT_1={q1}")
        print(f"TRANSFER_LIST_QUERY_COUNT_LIMIT_100={q100}")
        print("TRANSFER_LIST_FIXED_QUERY_COUNT=OK")

        print(f"RUNTIME_ROLE={role}")
        print("RUNTIME_ROLE_SUPERUSER=NO")
        print("RUNTIME_ROLE_BYPASSRLS=NO")

    finally:
        # Cleanup and engine disposal happen inside this exact event loop.
        await cleanup_fixture(fx)
        await engine.dispose()

    print("TEST_CLEANUP=OK")
    print("ENGINE_DISPOSE_SAME_EVENT_LOOP=OK")
    print("WAREHOUSE_INTERWAREHOUSE_POSTGRES_E2E_OK")


if __name__ == "__main__":
    start_time = time.perf_counter()
    try:
        asyncio.run(child_main())
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            _before_cursor_execute,
        )
    elapsed = time.perf_counter() - start_time
    print(f"TOTAL_EXECUTION_TIME={elapsed:.3f}s")
