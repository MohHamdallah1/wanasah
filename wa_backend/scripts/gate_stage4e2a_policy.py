"""
Stage 4E.2A Gate — TenantOperationalPolicy / Data Integrity Guard
=================================================================
Checks:
  1. Invalid Cross-Tenant location IDs -> API HTTP 400.
  2. Inactive referenced location -> API HTTP 400.
  3. Wrong location type -> API HTTP 400.
  4. Valid Draft save succeeds.
  5. Publish revalidates current locations and rejects a stale/inactive reference with HTTP 400.
  6. Valid Publish succeeds and only one PUBLISHED revision exists.
  7. Runtime loader revalidates published policy and fails closed when a location becomes stale.
  8. Published policy blocks warehouse deactivation with the expected blocker.
  9. RLS read/write isolation on tenant_operational_policies.
 10. RLS catalog has ENABLE + FORCE.
 11. Validator holds the project shared Location Advisory Guard; an exclusive deactivation guard waits.

The gate seeds dedicated tenants and deletes them in finally blocks.
Run:
    python wa_backend/scripts/gate_stage4e2a_policy.py

Exit 0 = PASS, non-zero = FAIL.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

from dotenv import load_dotenv

load_dotenv(_backend_dir / ".env", override=False)

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.warehouse import (
    deactivate_warehouse_location,
    publish_transfer_destination_policy_endpoint,
    save_transfer_destination_policy,
)
from models import Driver, TenantOperationalPolicy
from schemas import (
    TransferDestinationPolicyPublishRequest,
    TransferDestinationPolicySaveRequest,
    WarehouseLocationStateRequest,
)
from services import (
    InventoryRuleError,
    acquire_inventory_location_guard,
    load_published_transfer_destination_policy,
    validate_transfer_destination_policy_payload,
)


_migration_url = os.environ["DATABASE_URL_MIGRATION"]
_app_url = os.environ["DATABASE_URL"]

engine_su = create_async_engine(
    _migration_url,
    echo=False,
    pool_size=5,
    max_overflow=5,
)
engine_app = create_async_engine(
    _app_url,
    echo=False,
    pool_size=5,
    max_overflow=5,
)

Session_su = async_sessionmaker(
    bind=engine_su,
    expire_on_commit=False,
    autobegin=False,
)
Session_app = async_sessionmaker(
    bind=engine_app,
    expire_on_commit=False,
    autobegin=False,
)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def set_tenant(conn, company_id: int) -> None:
    await conn.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(int(company_id))},
    )


async def cleanup_company(company_id: int | None) -> None:
    if not company_id:
        return
    try:
        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text("DELETE FROM companies WHERE id = :id"),
                {"id": int(company_id)},
            )
            await su.commit()
    except Exception:
        pass


async def make_company(conn) -> int:
    code = f"C{uuid4().hex[:10]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO companies "
                    "(name, company_code, is_active, subscription_status, "
                    " currency_code, timezone, created_at) "
                    "VALUES (:name, :code, true, 'active', 'JOD', "
                    " 'Asia/Amman', NOW()) RETURNING id"
                ),
                {"name": f"Gate-{code}", "code": code},
            )
        ).scalar_one()
    )


async def make_branch(conn, company_id: int) -> int:
    code = f"B{uuid4().hex[:8]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO branches "
                    "(company_id, name, branch_code, is_active, created_at) "
                    "VALUES (:company_id, 'Gate HQ', :code, true, NOW()) "
                    "RETURNING id"
                ),
                {"company_id": company_id, "code": code},
            )
        ).scalar_one()
    )


async def make_driver(conn, company_id: int) -> int:
    username = f"gate_{uuid4().hex[:10]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO drivers "
                    "(company_id, username, password_hash, full_name, "
                    " is_active, is_admin, created_at) "
                    "VALUES (:company_id, :username, '$2b$12$gate', "
                    " 'Gate Admin', true, true, NOW()) RETURNING id"
                ),
                {"company_id": company_id, "username": username},
            )
        ).scalar_one()
    )


async def make_location(
    conn,
    company_id: int,
    branch_id: int,
    *,
    location_type: str = "WAREHOUSE",
    is_active: bool = True,
) -> int:
    code = f"L{uuid4().hex[:10]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO inventory_locations "
                    "(company_id, branch_id, name, code, location_type, "
                    " system_role, is_system_managed, version, is_active, "
                    " created_at, updated_at) "
                    "VALUES (:company_id, :branch_id, 'Gate Location', :code, "
                    " :location_type, NULL, false, 1, :is_active, NOW(), NOW()) "
                    "RETURNING id"
                ),
                {
                    "company_id": company_id,
                    "branch_id": branch_id,
                    "code": code,
                    "location_type": location_type,
                    "is_active": is_active,
                },
            )
        ).scalar_one()
    )


async def load_admin(session, company_id: int, driver_id: int) -> Driver:
    row = (
        await session.execute(
            select(Driver).where(
                Driver.company_id == company_id,
                Driver.id == driver_id,
            )
        )
    ).scalar_one()
    return row


def payload(
    quarantine_id: int,
    disposal_id: int,
    vendor_id: int,
    *,
    allow_retiring: bool = False,
) -> dict:
    return {
        "quarantine_location_id": quarantine_id,
        "disposal_location_id": disposal_id,
        "vendor_return_staging_location_id": vendor_id,
        "allow_retiring_warehouse_balancing": allow_retiring,
    }


async def expect_save_http_400(
    *,
    company_id: int,
    driver_id: int,
    policy_payload: dict,
    label: str,
) -> None:
    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, company_id)
        admin = await load_admin(app, company_id, driver_id)
        request = TransferDestinationPolicySaveRequest(
            request_id=uuid4(),
            expected_revision=None,
            payload=policy_payload,
        )
        try:
            await save_transfer_destination_policy(
                payload=request,
                db=app,
                current_admin=admin,
            )
        except HTTPException as exc:
            record(label, exc.status_code == 400, f"status={exc.status_code}")
        else:
            record(label, False, "request unexpectedly succeeded")
            await app.rollback()


async def test_policy_integrity_and_lifecycle() -> tuple[int | None, int | None]:
    print("\n[1] Policy data-integrity / publish / runtime / deactivation")
    company_a = company_b = None

    try:
        async with Session_su() as su:
            await su.begin()
            company_a = await make_company(su)
            branch_a = await make_branch(su, company_a)
            admin_a = await make_driver(su, company_a)

            quarantine = await make_location(
                su, company_a, branch_a, location_type="WAREHOUSE"
            )
            disposal = await make_location(
                su, company_a, branch_a, location_type="SCRAP"
            )
            vendor_staging = await make_location(
                su, company_a, branch_a, location_type="WAREHOUSE"
            )
            inactive_wh = await make_location(
                su,
                company_a,
                branch_a,
                location_type="WAREHOUSE",
                is_active=False,
            )
            wrong_type = await make_location(
                su,
                company_a,
                branch_a,
                location_type="IN_TRANSIT",
            )

            company_b = await make_company(su)
            branch_b = await make_branch(su, company_b)
            await make_driver(su, company_b)
            foreign_wh = await make_location(
                su, company_b, branch_b, location_type="WAREHOUSE"
            )
            await su.commit()

        await expect_save_http_400(
            company_id=company_a,
            driver_id=admin_a,
            policy_payload=payload(foreign_wh, disposal, vendor_staging),
            label="Cross-tenant location rejected with HTTP 400",
        )
        await expect_save_http_400(
            company_id=company_a,
            driver_id=admin_a,
            policy_payload=payload(inactive_wh, disposal, vendor_staging),
            label="Inactive location rejected with HTTP 400",
        )
        await expect_save_http_400(
            company_id=company_a,
            driver_id=admin_a,
            policy_payload=payload(wrong_type, disposal, vendor_staging),
            label="Wrong location type rejected with HTTP 400",
        )

        # Save a valid Draft through the real API function.
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            admin = await load_admin(app, company_a, admin_a)
            request = TransferDestinationPolicySaveRequest(
                request_id=uuid4(),
                expected_revision=None,
                payload=payload(quarantine, disposal, vendor_staging),
            )
            response = await save_transfer_destination_policy(
                payload=request,
                db=app,
                current_admin=admin,
            )
            policy_id = int(response["policy"]["id"])
            revision = int(response["policy"]["revision"])
            record(
                "Valid Draft save succeeds",
                response["policy"]["status"] == "DRAFT",
                f"policy_id={policy_id} revision={revision}",
            )

        # Simulate stale configuration through privileged maintenance and verify
        # publish revalidation catches it at the API boundary.
        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE inventory_locations "
                    "SET is_active=false, version=version+1, updated_at=NOW() "
                    "WHERE id=:id AND company_id=:company_id"
                ),
                {"id": quarantine, "company_id": company_a},
            )
            await su.commit()

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            admin = await load_admin(app, company_a, admin_a)
            request = TransferDestinationPolicyPublishRequest(
                request_id=uuid4(),
                expected_revision=revision,
            )
            try:
                await publish_transfer_destination_policy_endpoint(
                    policy_id=policy_id,
                    payload=request,
                    db=app,
                    current_admin=admin,
                )
            except HTTPException as exc:
                record(
                    "Publish revalidates stale/inactive location with HTTP 400",
                    exc.status_code == 400,
                    f"status={exc.status_code}",
                )
            else:
                record(
                    "Publish revalidates stale/inactive location with HTTP 400",
                    False,
                    "publish unexpectedly succeeded",
                )
                await app.rollback()

        # Restore active and publish successfully.
        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE inventory_locations "
                    "SET is_active=true, version=version+1, updated_at=NOW() "
                    "WHERE id=:id AND company_id=:company_id"
                ),
                {"id": quarantine, "company_id": company_a},
            )
            await su.commit()

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            admin = await load_admin(app, company_a, admin_a)
            request = TransferDestinationPolicyPublishRequest(
                request_id=uuid4(),
                expected_revision=revision,
            )
            response = await publish_transfer_destination_policy_endpoint(
                policy_id=policy_id,
                payload=request,
                db=app,
                current_admin=admin,
            )
            record(
                "Valid Publish succeeds",
                response["policy"]["status"] == "PUBLISHED",
                f"revision={response['policy']['revision']}",
            )

        async with Session_su() as su:
            await su.begin()
            published_count = int(
                (
                    await su.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM tenant_operational_policies "
                            "WHERE company_id=:company_id "
                            "AND policy_code='INVENTORY_TRANSFER_DESTINATIONS' "
                            "AND status='PUBLISHED'"
                        ),
                        {"company_id": company_a},
                    )
                ).scalar_one()
            )
            await su.rollback()
        record(
            "Exactly one PUBLISHED revision",
            published_count == 1,
            f"count={published_count}",
        )

        # Runtime loader must fail closed if privileged maintenance makes a
        # published destination stale after publication.
        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE inventory_locations "
                    "SET is_active=false, version=version+1, updated_at=NOW() "
                    "WHERE id=:id AND company_id=:company_id"
                ),
                {"id": vendor_staging, "company_id": company_a},
            )
            await su.commit()

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            try:
                await load_published_transfer_destination_policy(
                    app,
                    company_id=company_a,
                    revalidate_locations=True,
                )
            except InventoryRuleError as exc:
                record(
                    "Runtime published-policy revalidation fails closed",
                    exc.code == "TRANSFER_POLICY_STALE",
                    f"code={exc.code}",
                )
                await app.rollback()
            else:
                record(
                    "Runtime published-policy revalidation fails closed",
                    False,
                    "stale published policy unexpectedly loaded",
                )
                await app.rollback()

        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE inventory_locations "
                    "SET is_active=true, version=version+1, updated_at=NOW() "
                    "WHERE id=:id AND company_id=:company_id"
                ),
                {"id": vendor_staging, "company_id": company_a},
            )
            await su.commit()

        # Published policy must block normal warehouse deactivation.
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            admin = await load_admin(app, company_a, admin_a)
            current_version = int(
                (
                    await app.execute(
                        text(
                            "SELECT version FROM inventory_locations "
                            "WHERE company_id=:company_id AND id=:id"
                        ),
                        {"company_id": company_a, "id": quarantine},
                    )
                ).scalar_one()
            )
            request = WarehouseLocationStateRequest(
                request_id=uuid4(),
                expected_version=current_version,
                reason="stage4e2a gate",
            )
            try:
                await deactivate_warehouse_location(
                    location_id=quarantine,
                    payload=request,
                    db=app,
                    current_admin=admin,
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                blocker = (detail.get("context") or {}).get("blocker_type")
                record(
                    "Published policy blocks warehouse deactivation",
                    exc.status_code == 409
                    and blocker == "PUBLISHED_OPERATIONAL_POLICY",
                    f"status={exc.status_code} blocker={blocker}",
                )
            else:
                record(
                    "Published policy blocks warehouse deactivation",
                    False,
                    "deactivation unexpectedly succeeded",
                )
                await app.rollback()

        return company_a, company_b

    except Exception as exc:
        record("Policy integrity lifecycle test", False, repr(exc))
        return company_a, company_b


async def test_rls(company_a: int, company_b: int) -> None:
    print("\n[2] TenantOperationalPolicy RLS")

    async with Session_su() as su:
        await su.begin()
        policy_row = (
            await su.execute(
                text(
                    "SELECT id, created_by "
                    "FROM tenant_operational_policies "
                    "WHERE company_id=:company_id "
                    "AND policy_code='INVENTORY_TRANSFER_DESTINATIONS' "
                    "AND status='PUBLISHED' LIMIT 1"
                ),
                {"company_id": company_a},
            )
        ).one()
        policy_id = int(policy_row.id)
        created_by = int(policy_row.created_by)
        await su.rollback()

    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, company_b)
        visible = int(
            (
                await app.execute(
                    text(
                        "SELECT COUNT(*) FROM tenant_operational_policies "
                        "WHERE id=:id"
                    ),
                    {"id": policy_id},
                )
            ).scalar_one()
        )
        await app.rollback()
    record(
        "RLS read isolation: tenant B cannot see tenant A policy",
        visible == 0,
        f"rows_visible={visible}",
    )

    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, company_b)
        try:
            await app.execute(
                text(
                    "INSERT INTO tenant_operational_policies "
                    "(company_id, policy_code, schema_version, revision, "
                    " validated_payload, status, created_by, created_at, updated_at) "
                    "VALUES (:company_id, 'INVENTORY_TRANSFER_DESTINATIONS', "
                    " 1, 999999, '{}'::jsonb, 'DRAFT', :created_by, NOW(), NOW())"
                ),
                {
                    "company_id": company_a,
                    "created_by": created_by,
                },
            )
        except Exception as exc:
            await app.rollback()
            record(
                "RLS write isolation: tenant B cannot insert tenant A policy",
                True,
                type(exc).__name__,
            )
        else:
            await app.rollback()
            record(
                "RLS write isolation: tenant B cannot insert tenant A policy",
                False,
                "INSERT unexpectedly succeeded",
            )

    async with Session_su() as su:
        await su.begin()
        catalog = (
            await su.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                    "       COUNT(p.policyname) AS policy_count "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "LEFT JOIN pg_policies p "
                    "  ON p.schemaname=n.nspname AND p.tablename=c.relname "
                    "WHERE n.nspname=current_schema() "
                    "  AND c.relname='tenant_operational_policies' "
                    "GROUP BY c.relrowsecurity, c.relforcerowsecurity"
                )
            )
        ).one()
        await su.rollback()

    record(
        "RLS catalog: ENABLE + FORCE + policy exists",
        bool(catalog.relrowsecurity)
        and bool(catalog.relforcerowsecurity)
        and int(catalog.policy_count) >= 1,
        (
            f"enable={catalog.relrowsecurity} "
            f"force={catalog.relforcerowsecurity} "
            f"policies={catalog.policy_count}"
        ),
    )


async def test_location_guard_race(company_id: int) -> None:
    print("\n[3] Policy validator vs exclusive deactivation Location Guard")

    async with Session_su() as su:
        await su.begin()
        row = (
            await su.execute(
                text(
                    "SELECT validated_payload "
                    "FROM tenant_operational_policies "
                    "WHERE company_id=:company_id "
                    "AND policy_code='INVENTORY_TRANSFER_DESTINATIONS' "
                    "AND status='PUBLISHED' LIMIT 1"
                ),
                {"company_id": company_id},
            )
        ).one()
        policy_payload = dict(row.validated_payload)
        quarantine_id = int(policy_payload["quarantine_location_id"])
        await su.rollback()

    ready = asyncio.Event()
    release = asyncio.Event()
    s1_pid_box: list[int] = []

    async def validator_worker() -> None:
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_id)
            pid = int(
                (await app.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            )
            s1_pid_box.append(pid)
            await validate_transfer_destination_policy_payload(
                app,
                company_id=company_id,
                payload=policy_payload,
                lock_locations=True,
            )
            ready.set()
            await release.wait()
            await app.rollback()

    async def exclusive_worker() -> None:
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_id)
            await acquire_inventory_location_guard(
                app,
                company_id,
                quarantine_id,
                exclusive=True,
            )
            await app.rollback()

    t1 = asyncio.create_task(validator_worker())
    t2 = None
    try:
        await asyncio.wait_for(ready.wait(), timeout=10)
        t2 = asyncio.create_task(exclusive_worker())
        await asyncio.sleep(0.2)

        s1_pid = s1_pid_box[0]
        async with engine_su.connect() as chk:
            held = (
                await chk.execute(
                    text(
                        "SELECT classid, objid "
                        "FROM pg_locks "
                        "WHERE locktype='advisory' AND granted=true "
                        "AND pid=:pid "
                        "ORDER BY classid, objid"
                    ),
                    {"pid": s1_pid},
                )
            ).all()

        waiting_confirmed = False
        matched = None
        for classid, objid in held:
            for _ in range(20):
                async with engine_su.connect() as chk:
                    count = int(
                        (
                            await chk.execute(
                                text(
                                    "SELECT COUNT(*) FROM pg_locks "
                                    "WHERE locktype='advisory' "
                                    "AND granted=false "
                                    "AND classid=:classid AND objid=:objid"
                                ),
                                {"classid": classid, "objid": objid},
                            )
                        ).scalar_one()
                    )
                if count > 0:
                    waiting_confirmed = True
                    matched = (classid, objid, count)
                    break
                await asyncio.sleep(0.05)
            if waiting_confirmed:
                break

        record(
            "Exclusive deactivation guard waits behind policy validator shared guard",
            waiting_confirmed,
            f"matched={matched}",
        )

    finally:
        release.set()
        await asyncio.gather(
            t1,
            *(tuple([t2]) if t2 is not None else tuple()),
            return_exceptions=True,
        )


async def main() -> int:
    company_a = company_b = None
    try:
        company_a, company_b = await test_policy_integrity_and_lifecycle()
        if company_a and company_b:
            await test_rls(company_a, company_b)
            await test_location_guard_race(company_a)
    finally:
        await cleanup_company(company_a)
        await cleanup_company(company_b)
        await engine_app.dispose()
        await engine_su.dispose()

    print("\n" + "=" * 72)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    failed = [(name, detail) for name, ok, detail in RESULTS if not ok]
    print(f"STAGE4E2A_GATE: {passed}/{total} passed")

    if failed:
        for name, detail in failed:
            print(f"  FAIL: {name}" + (f" — {detail}" if detail else ""))
        print("STAGE4E2A_POLICY_GATE=FAIL")
        return 1

    print("STAGE4E2A_POLICY_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
