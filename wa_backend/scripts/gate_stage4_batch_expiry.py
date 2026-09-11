"""
Stage 4 Gate — Batch Disposition, Expiry and Transfer Purposes
==============================================================
Invariants checked:
  1. Transfer purposes allowed values.
  2. InventoryBalance stock_status includes disposition statuses.
  3. Synchronous expiry/shelf-life check in allocate_fefo_inventory_batch.

Run:  python wa_backend/scripts/gate_stage4_batch_expiry.py
Exit 0 = PASS, non-zero = FAIL.
"""

import asyncio
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=False)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Import services for FEFO test
from services import allocate_fefo_inventory_batch, InventoryMutationError

_migration_url = os.environ["DATABASE_URL_MIGRATION"]
_app_url       = os.environ["DATABASE_URL"]

engine_su  = create_async_engine(_migration_url, echo=False, pool_size=5, max_overflow=5)
engine_app = create_async_engine(_app_url,       echo=False, pool_size=5, max_overflow=5)

Session_su  = async_sessionmaker(bind=engine_su,  expire_on_commit=False, autobegin=False)

RESULTS: list[tuple[str, bool, str]] = []

def record(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))

async def cleanup_company(company_id: int) -> None:
    try:
        async with Session_su() as su:
            await su.begin()
            await su.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company_id})
            await su.commit()
    except Exception:
        pass

async def make_company(conn) -> int:
    code = f"C{uuid4().hex[:8]}"
    row = (await conn.execute(text(
        "INSERT INTO companies (name, company_code, is_active, subscription_status, currency_code, timezone, created_at) "
        "VALUES (:n, :c, true, 'active', 'JOD', 'Asia/Riyadh', NOW()) RETURNING id"
    ), {"n": f"Co-{code}", "c": code})).fetchone()
    return row[0]

async def make_branch(conn, company_id: int) -> int:
    code = f"B{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO branches (company_id, name, branch_code, is_active, created_at) "
        "VALUES (:c, 'HQ', :bc, true, NOW()) RETURNING id"
    ), {"c": company_id, "bc": code})).fetchone()
    return row[0]

async def make_location(conn, company_id: int, branch_id: int) -> int:
    code = f"L{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO inventory_locations "
        "(company_id, branch_id, name, code, location_type, is_system_managed, version, is_active, created_at, updated_at) "
        "VALUES (:c, :b, 'WH', :code, 'WAREHOUSE', false, 1, true, NOW(), NOW()) RETURNING id"
    ), {"c": company_id, "b": branch_id, "code": code})).fetchone()
    return row[0]

async def make_product(conn, company_id: int) -> int:
    code = f"P{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO products (company_id, code, name, created_at, updated_at) "
        "VALUES (:c, :code, 'Prod', NOW(), NOW()) RETURNING id"
    ), {"c": company_id, "code": code})).fetchone()
    return row[0]

async def make_variant(conn, company_id: int, product_id: int, min_shelf_life: int = 0) -> int:
    sku = f"SKU-{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO product_variants "
        "(company_id, product_id, sku, name, base_uom_id, quantity_scale, quantity_step, "
        " lot_control_mode, expiry_control_mode, lifecycle_status, operational_hold, lifecycle_revision, version, created_at, updated_at, min_shelf_life_days) "
        "VALUES (:c, :p, :sku, 'SKU', 1, 0, '1', 'NONE', 'NONE', 'DRAFT', 'NONE', 1, 1, NOW(), NOW(), :msl) RETURNING id"
    ), {"c": company_id, "p": product_id, "sku": sku, "msl": min_shelf_life})).fetchone()
    return row[0]

async def make_driver(conn, company_id: int) -> int:
    uname = f"d{uuid4().hex[:8]}"
    row = (await conn.execute(text(
        "INSERT INTO drivers (company_id, username, password_hash, full_name, phone_number, is_active, is_admin, created_at) "
        "VALUES (:c, :u, '$2b$12$xxx', 'Admin', :ph, true, true, NOW()) RETURNING id"
    ), {"c": company_id, "u": uname, "ph": f"+9627{uuid4().hex[:7]}"})).fetchone()
    return row[0]

async def make_batch(conn, company_id: int, variant_id: int, expiry_date: date, disposition: str = 'RELEASED') -> int:
    bn = f"BN-{uuid4().hex[:6]}"
    row = (await conn.execute(text(
        "INSERT INTO product_batches "
        "(company_id, product_variant_id, batch_number, expiry_date, disposition, is_active, created_at) "
        "VALUES (:c, :v, :bn, :exp, :disp, true, NOW()) RETURNING id"
    ), {"c": company_id, "v": variant_id, "bn": bn, "exp": expiry_date, "disp": disposition})).fetchone()
    return row[0]

async def make_balance(conn, company_id: int, location_id: int, variant_id: int, batch_id: int, qty: int, status: str = 'AVAILABLE') -> int:
    row = (await conn.execute(text(
        "INSERT INTO inventory_balances "
        "(company_id, location_id, product_variant_id, batch_id, stock_status, on_hand_quantity, reserved_quantity, last_updated) "
        "VALUES (:c, :l, :v, :b, :s, :q, 0, NOW()) RETURNING id"
    ), {"c": company_id, "l": location_id, "v": variant_id, "b": batch_id, "s": status, "q": qty})).fetchone()
    return row[0]


async def test_transfer_purpose() -> None:
    print("\n[1] Transfer Purposes Constraints")
    co = None
    try:
        async with Session_su() as su:
            await su.begin()
            co = await make_company(su)
            br = await make_branch(su, co)
            loc1 = await make_location(su, co, br)
            loc2 = await make_location(su, co, br)
            drv = await make_driver(su, co)
            await su.commit()

        # Try to insert valid purpose
        async with Session_su() as su:
            await su.begin()
            try:
                await su.execute(text(
                    "INSERT INTO inventory_transfer_headers "
                    "(company_id, reference_number, source_location_id, destination_location_id, "
                    "workflow_type, status, transfer_purpose, dispatched_by, created_at, posted_at, updated_at) "
                    "VALUES (:c, 'REF1', :l1, :l2, 'DIRECT', 'POSTED', 'QUARANTINE', :d, NOW(), NOW(), NOW())"
                ), {"c": co, "l1": loc1, "l2": loc2, "d": drv})
                await su.commit()
                record("TransferPurpose valid insert", True)
            except Exception as e:
                await su.rollback()
                record("TransferPurpose valid insert", False, str(e))

        # Try to insert invalid purpose
        async with Session_su() as su:
            await su.begin()
            try:
                await su.execute(text(
                    "INSERT INTO inventory_transfer_headers "
                    "(company_id, reference_number, source_location_id, destination_location_id, "
                    "workflow_type, status, transfer_purpose, dispatched_by, created_at, posted_at) "
                    "VALUES (:c, 'REF2', :l1, :l2, 'DIRECT', 'POSTED', 'INVALID_PURPOSE', :d, NOW(), NOW())"
                ), {"c": co, "l1": loc1, "l2": loc2, "d": drv})
                await su.rollback()
                record("TransferPurpose invalid insert blocked", False, "Succeeded!")
            except Exception as e:
                await su.rollback()
                record("TransferPurpose invalid insert blocked", "chk_transfer_header_purpose" in str(e) or "constraint" in str(e).lower(), type(e).__name__)

    finally:
        if co:
            await cleanup_company(co)


async def test_batch_disposition_status() -> None:
    print("\n[2] Batch Disposition & Stock Status Constraints")
    co = None
    try:
        async with Session_su() as su:
            await su.begin()
            co = await make_company(su)
            br = await make_branch(su, co)
            loc = await make_location(su, co, br)
            prd = await make_product(su, co)
            var = await make_variant(su, co, prd)
            await su.commit()

        async with Session_su() as su:
            await su.begin()
            try:
                # Invalid batch disposition
                await make_batch(su, co, var, date(2030, 1, 1), 'INVALID')
                await su.rollback()
                record("Invalid batch disposition blocked", False)
            except Exception as e:
                await su.rollback()
                record("Invalid batch disposition blocked", "chk_product_batch_disposition" in str(e) or "constraint" in str(e).lower())
            
        async with Session_su() as su:
            await su.begin()
            b1 = await make_batch(su, co, var, date(2030, 1, 1), 'RELEASED')
            await su.commit()

        # Valid stock status in balance
        async with Session_su() as su:
            await su.begin()
            try:
                await make_balance(su, co, loc, var, b1, 10, 'QUARANTINED')
                await su.commit()
                record("Valid stock_status in balance", True)
            except Exception as e:
                await su.rollback()
                record("Valid stock_status in balance", False, str(e))

        # Invalid stock status in balance
        async with Session_su() as su:
            await su.begin()
            try:
                await make_balance(su, co, loc, var, b1, 10, 'UNKNOWN')
                await su.rollback()
                record("Invalid stock_status blocked", False)
            except Exception as e:
                await su.rollback()
                record("Invalid stock_status blocked", "chk_inv_bal_status" in str(e) or "constraint" in str(e).lower(), type(e).__name__)

    finally:
        if co:
            await cleanup_company(co)


async def test_fefo_expiry_shelf_life() -> None:
    print("\n[3] Synchronous Expiry & Shelf Life FEFO Checks")
    co = None
    try:
        async with Session_su() as su:
            await su.begin()
            co = await make_company(su)
            br = await make_branch(su, co)
            loc = await make_location(su, co, br)
            prd = await make_product(su, co)
            # Variant requires 10 days shelf life minimum
            var = await make_variant(su, co, prd, min_shelf_life=10)
            
            # Batch 1: Expired
            b1 = await make_batch(su, co, var, date(2026, 9, 1))
            await make_balance(su, co, loc, var, b1, 100)
            
            # Batch 2: Expires in 5 days (fails min_shelf_life=10)
            b2 = await make_batch(su, co, var, date(2026, 9, 17))
            await make_balance(su, co, loc, var, b2, 100)
            
            # Batch 3: Expires in 15 days (valid)
            b3 = await make_batch(su, co, var, date(2026, 9, 27))
            await make_balance(su, co, loc, var, b3, 100)
            
            # Batch 4: Valid expiry but QUARANTINED disposition
            b4 = await make_batch(su, co, var, date(2026, 9, 30), 'QUARANTINED')
            await make_balance(su, co, loc, var, b4, 100, 'AVAILABLE') # Should be filtered by disposition
            
            await su.commit()

        # Now test FEFO allocation
        async with Session_su() as su:
            await su.begin()
            try:
                allocations = await allocate_fefo_inventory_batch(
                    su,
                    company_id=co,
                    location_id=loc,
                    requests={var: Decimal('50')},
                    as_of_date=date(2026, 9, 12),
                    require_full=True
                )
                
                # Should only allocate from b3
                alloc_var = allocations[var]
                if len(alloc_var) == 1 and alloc_var[0][0] == b3 and alloc_var[0][1] == Decimal('50'):
                    record("FEFO properly filters expired, low shelf-life, and non-released batches", True)
                else:
                    record("FEFO allocation check", False, f"Allocated: {alloc_var}")
                
            except Exception as e:
                record("FEFO allocation check", False, str(e))
                
            await su.rollback()

        # Test shortage (requesting 150, but only 100 is valid)
        async with Session_su() as su:
            await su.begin()
            try:
                await allocate_fefo_inventory_batch(
                    su,
                    company_id=co,
                    location_id=loc,
                    requests={var: Decimal('150')},
                    as_of_date=date(2026, 9, 12),
                    require_full=True
                )
                record("FEFO shortage check", False, "Should have raised InventoryMutationError")
            except InventoryMutationError:
                record("FEFO shortage check", True)
            except Exception as e:
                record("FEFO shortage check", False, f"Wrong exception: {type(e).__name__}")
                
            await su.rollback()

    finally:
        if co:
            await cleanup_company(co)


async def main() -> int:
    print("=" * 60)
    print("Stage 4 Gate — BATCH_DISPOSITION_GATE")
    print("=" * 60)

    await test_transfer_purpose()
    await test_batch_disposition_status()
    await test_fefo_expiry_shelf_life()

    await engine_su.dispose()
    await engine_app.dispose()

    print("\n" + "=" * 60)
    total  = len(RESULTS)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = total - passed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\nBATCH_DISPOSITION_GATE=PASS")
        return 0
    else:
        print("\nBATCH_DISPOSITION_GATE=FAIL")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAILED: {name} — {detail}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
