from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, text

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from api.auth import create_access_token
from api.dependencies import get_current_driver
from api.warehouse import (
    get_warehouse_inventory,
    get_warehouse_inventory_alert_summary,
    get_warehouse_inventory_summary,
)
from domains.live_stock_projection.service import rebuild_live_stock_company
from models import Driver
from scripts import gate_stage821_live_stock_projector_runtime as fixture


RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def seed_read_model_scenario(ids: dict[str, int]) -> dict[str, int]:
    company_id = int(ids["a"])
    warehouse_id = int(ids["a_wh"])
    active_variant_id = int(ids["a_variant"])
    as_of = date.fromordinal(int(ids["as_of_ordinal"]))

    async with fixture.SessionSU() as su:
        await su.begin()

        base = (
            await su.execute(
                text(
                    """
                    SELECT
                        pv.product_id,
                        pv.base_uom_id,
                        il.branch_id,
                        b.batch_id
                    FROM product_variants pv
                    JOIN inventory_locations il
                      ON il.company_id=pv.company_id
                     AND il.id=:warehouse_id
                    JOIN inventory_balances b
                      ON b.company_id=pv.company_id
                     AND b.id=:balance_id
                    WHERE pv.company_id=:company_id
                      AND pv.id=:variant_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": warehouse_id,
                    "variant_id": active_variant_id,
                    "balance_id": int(ids["a_bal1"]),
                },
            )
        ).mappings().one()

        admin_id = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO drivers
                            (company_id, username, password_hash, full_name,
                             is_active, is_admin, can_allow_debt,
                             max_debt_limit, created_at)
                        VALUES
                            (:company_id, :username, 'x', 'Stage823 Admin',
                             true, true, false, 0, NOW())
                        RETURNING id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "username": f"s823-admin-{uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )
        restricted_id = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO drivers
                            (company_id, username, password_hash, full_name,
                             is_active, is_admin, can_allow_debt,
                             max_debt_limit, created_at)
                        VALUES
                            (:company_id, :username, 'x', 'Stage823 Restricted',
                             true, false, false, 0, NOW())
                        RETURNING id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "username": f"s823-user-{uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )

        permission_value = (
            await su.execute(
                text(
                    "SELECT id FROM permissions "
                    "WHERE code='inventory.read'"
                )
            )
        ).scalar_one_or_none()
        permission_created_by_gate = permission_value is None
        if permission_value is None:
            permission_value = (
                await su.execute(
                    text(
                        """
                        INSERT INTO permissions (code)
                        VALUES ('inventory.read')
                        ON CONFLICT (code) DO UPDATE
                        SET code=EXCLUDED.code
                        RETURNING id
                        """
                    )
                )
            ).scalar_one()
        permission_id = int(permission_value)
        role_id = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO roles
                            (company_id, name, is_system_role)
                        VALUES (:company_id, :name, false)
                        RETURNING id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "name": f"Stage823 Inventory {uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )
        await su.execute(
            text(
                """
                INSERT INTO role_permissions
                    (company_id, role_id, permission_id)
                VALUES (:company_id, :role_id, :permission_id)
                """
            ),
            {
                "company_id": company_id,
                "role_id": role_id,
                "permission_id": permission_id,
            },
        )

        zone_id = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO zones
                            (company_id, name, governorate_id,
                             sequence_number, start_date, interval_days,
                             is_active)
                        VALUES
                            (:company_id, :name, NULL, NULL, NULL, NULL, true)
                        RETURNING id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "name": f"Stage823 Zone {uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )

        async def vehicle(label: str) -> tuple[int, int]:
            vehicle_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO vehicles
                                (company_id, plate_number, vehicle_type,
                                 current_mileage, maintenance_status, is_active)
                            VALUES
                                (:company_id, :plate, 'VAN', 0, 'Active', true)
                            RETURNING id
                            """
                        ),
                        {
                            "company_id": company_id,
                            "plate": f"S823-{label}-{uuid4().hex[:6]}",
                        },
                    )
                ).scalar_one()
            )
            location_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO inventory_locations
                                (company_id, branch_id, name, code,
                                 location_type, vehicle_id, system_role,
                                 is_system_managed, version, is_active,
                                 created_at, updated_at)
                            VALUES
                                (:company_id, :branch_id, :name, :code,
                                 'VEHICLE', :vehicle_id, NULL,
                                 false, 1, true, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "company_id": company_id,
                            "branch_id": int(base["branch_id"]),
                            "name": f"Stage823 {label} Vehicle",
                            "code": f"S823-{label}-{uuid4().hex[:7]}",
                            "vehicle_id": vehicle_id,
                        },
                    )
                ).scalar_one()
            )
            await su.execute(
                text(
                    """
                    INSERT INTO dispatch_routes
                        (company_id, zone_id, driver_id, vehicle_id,
                         work_session_id, source_location_id,
                         dispatch_date, status, created_at)
                    VALUES
                        (:company_id, :zone_id, NULL, :vehicle_id,
                         NULL, :source_location_id,
                         :dispatch_date, 'closed', NOW())
                    """
                ),
                {
                    "company_id": company_id,
                    "zone_id": zone_id,
                    "vehicle_id": vehicle_id,
                    "source_location_id": warehouse_id,
                    "dispatch_date": as_of,
                },
            )
            return vehicle_id, location_id

        readable_vehicle_id, readable_location_id = await vehicle("READ")
        hidden_vehicle_id, hidden_location_id = await vehicle("HIDDEN")

        await su.execute(
            text(
                """
                INSERT INTO user_location_access
                    (company_id, driver_id, location_id, role_id)
                VALUES
                    (:company_id, :driver_id, :warehouse_id, :role_id),
                    (:company_id, :driver_id, :vehicle_location_id, :role_id)
                """
            ),
            {
                "company_id": company_id,
                "driver_id": restricted_id,
                "warehouse_id": warehouse_id,
                "vehicle_location_id": readable_location_id,
                "role_id": role_id,
            },
        )

        async def retiring_variant(name: str) -> tuple[int, int]:
            variant_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO product_variants
                                (company_id, product_id, base_uom_id,
                                 name, sku, quantity_scale, quantity_step,
                                 lot_control_mode, expiry_control_mode,
                                 lifecycle_status, operational_hold,
                                 lifecycle_revision, version,
                                 published_at, retired_at,
                                 packs_per_carton,
                                 package_uses_base_barcode,
                                 default_max_samples_per_day,
                                 created_at, updated_at)
                            VALUES
                                (:company_id, :product_id, :uom_id,
                                 :name, :sku, 0, 1,
                                 'REQUIRED', 'REQUIRED',
                                 'RETIRING', 'NONE',
                                 1, 1, NOW(), NOW(),
                                 50, false, 0, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "company_id": company_id,
                            "product_id": int(base["product_id"]),
                            "uom_id": int(base["base_uom_id"]),
                            "name": name,
                            "sku": f"S823-{uuid4().hex[:10]}",
                        },
                    )
                ).scalar_one()
            )
            batch_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO product_batches
                                (company_id, product_variant_id,
                                 batch_number, production_date, expiry_date,
                                 disposition, disposition_revision,
                                 is_active, created_at, updated_at)
                            VALUES
                                (:company_id, :variant_id, :batch_number,
                                 :production_date, :expiry_date,
                                 'RELEASED', 1, true, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "company_id": company_id,
                            "variant_id": variant_id,
                            "batch_number": f"S823-{uuid4().hex[:10]}",
                            "production_date": as_of - timedelta(days=10),
                            "expiry_date": as_of + timedelta(days=30),
                        },
                    )
                ).scalar_one()
            )
            return variant_id, batch_id

        readable_variant_id, readable_batch_id = await retiring_variant(
            "Readable Retiring"
        )
        hidden_variant_id, hidden_batch_id = await retiring_variant(
            "Hidden Retiring"
        )

        balance_rows = (
            {
                "location_id": readable_location_id,
                "variant_id": active_variant_id,
                "batch_id": int(base["batch_id"]),
                "qty": 5,
            },
            {
                "location_id": hidden_location_id,
                "variant_id": active_variant_id,
                "batch_id": int(base["batch_id"]),
                "qty": 7,
            },
            {
                "location_id": readable_location_id,
                "variant_id": readable_variant_id,
                "batch_id": readable_batch_id,
                "qty": 9,
            },
            {
                "location_id": hidden_location_id,
                "variant_id": hidden_variant_id,
                "batch_id": hidden_batch_id,
                "qty": 11,
            },
        )
        for row in balance_rows:
            await su.execute(
                text(
                    """
                    INSERT INTO inventory_balances
                        (company_id, location_id, product_variant_id,
                         batch_id, stock_status, on_hand_quantity,
                         reserved_quantity, last_updated)
                    VALUES
                        (:company_id, :location_id, :variant_id,
                         :batch_id, 'AVAILABLE', :qty, 0, NOW())
                    """
                ),
                {
                    "company_id": company_id,
                    **row,
                },
            )

        await su.commit()

    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        await rebuild_live_stock_company(
            app,
            company_id=company_id,
            batch_size=1000,
        )
        await app.commit()

    return {
        "company_id": company_id,
        "warehouse_id": warehouse_id,
        "active_variant_id": active_variant_id,
        "admin_id": admin_id,
        "restricted_id": restricted_id,
        "readable_variant_id": readable_variant_id,
        "hidden_variant_id": hidden_variant_id,
        "readable_vehicle_id": readable_vehicle_id,
        "hidden_vehicle_id": hidden_vehicle_id,
        "permission_created_by_gate": int(
            permission_created_by_gate
        ),
    }


def make_actor(
    *,
    company_id: int,
    driver_id: int,
    is_admin: bool,
) -> Driver:
    return Driver(
        id=int(driver_id),
        company_id=int(company_id),
        username=f"stage823-{driver_id}",
        password_hash="x",
        full_name="Stage823 Actor",
        is_active=True,
        is_admin=bool(is_admin),
        can_allow_debt=False,
        max_debt_limit=0,
    )


async def page(
    actor: Driver,
    *,
    warehouse_id: int,
    search: str | None = None,
    only_alerts: bool = False,
) -> dict:
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, int(actor.company_id))
        result = await get_warehouse_inventory(
            location_id=warehouse_id,
            cursor=None,
            limit=50,
            search=search,
            only_alerts=only_alerts,
            db=app,
            current_admin=actor,
        )
        await app.rollback()
        return result


async def summary(actor: Driver, warehouse_id: int) -> dict:
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, int(actor.company_id))
        result = await get_warehouse_inventory_summary(
            location_id=warehouse_id,
            db=app,
            current_admin=actor,
        )
        await app.rollback()
        return result


async def alerts(actor: Driver, warehouse_id: int) -> dict:
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, int(actor.company_id))
        result = await get_warehouse_inventory_alert_summary(
            location_id=warehouse_id,
            db=app,
            current_admin=actor,
        )
        await app.rollback()
        return result


def item_by_name(payload: dict, name: str) -> dict | None:
    return next(
        (row for row in payload["items"] if row["name"] == name),
        None,
    )


async def cleanup_gate_permission_if_owned(
    created_by_gate: bool,
) -> None:
    if not created_by_gate:
        return
    async with fixture.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                """
                DELETE FROM permissions p
                WHERE p.code='inventory.read'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM role_permissions rp
                      WHERE rp.permission_id=p.id
                  )
                """
            )
        )
        await su.commit()


async def run() -> None:
    await fixture.cleanup_test_companies()
    ids: dict[str, int] = {}
    try:
        base_ids = await fixture.seed()
        ids = await seed_read_model_scenario(base_ids)
        auth_token = create_access_token(
            {
                "sub": str(ids["admin_id"]),
                "is_admin": True,
                "username": "stage823-admin",
            },
            company_id=ids["company_id"],
            role_name="Admin",
        )
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=auth_token,
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            valid_driver = await get_current_driver(
                credentials=credentials,
                db=app,
            )
            valid_identity = (
                int(valid_driver.id),
                int(valid_driver.company_id),
            )
            await app.rollback()
        record(
            "collapsed auth query preserves valid-token authentication",
            valid_identity
            == (int(ids["admin_id"]), int(ids["company_id"])),
        )

        async with fixture.SessionSU() as su:
            await su.begin()
            await su.execute(
                text(
                    """
                    INSERT INTO token_blacklist (token, blacklisted_at)
                    VALUES (:token, NOW())
                    """
                ),
                {"token": auth_token},
            )
            await su.commit()

        blacklisted_status = None
        try:
            async with fixture.SessionApp() as app:
                await app.begin()
                await get_current_driver(
                    credentials=credentials,
                    db=app,
                )
        except HTTPException as exc:
            blacklisted_status = exc.status_code
        record(
            "collapsed auth query preserves blacklist rejection",
            blacklisted_status == 401,
            f"status={blacklisted_status}",
        )

        async with fixture.SessionSU() as su:
            await su.begin()
            await su.execute(
                text("DELETE FROM token_blacklist WHERE token=:token"),
                {"token": auth_token},
            )
            await su.execute(
                text(
                    """
                    UPDATE drivers
                    SET is_active=false
                    WHERE company_id=:company_id AND id=:driver_id
                    """
                ),
                {
                    "company_id": ids["company_id"],
                    "driver_id": ids["admin_id"],
                },
            )
            await su.commit()

        disabled_status = None
        try:
            async with fixture.SessionApp() as app:
                await app.begin()
                await get_current_driver(
                    credentials=credentials,
                    db=app,
                )
        except HTTPException as exc:
            disabled_status = exc.status_code
        record(
            "collapsed auth query preserves disabled-account rejection",
            disabled_status == 403,
            f"status={disabled_status}",
        )

        async with fixture.SessionSU() as su:
            await su.begin()
            await su.execute(
                text(
                    """
                    UPDATE drivers
                    SET is_active=true
                    WHERE company_id=:company_id AND id=:driver_id
                    """
                ),
                {
                    "company_id": ids["company_id"],
                    "driver_id": ids["admin_id"],
                },
            )
            await su.commit()

        admin = make_actor(
            company_id=ids["company_id"],
            driver_id=ids["admin_id"],
            is_admin=True,
        )
        restricted = make_actor(
            company_id=ids["company_id"],
            driver_id=ids["restricted_id"],
            is_admin=False,
        )

        admin_page = await page(
            admin,
            warehouse_id=ids["warehouse_id"],
        )
        restricted_page = await page(
            restricted,
            warehouse_id=ids["warehouse_id"],
        )

        admin_names = {row["name"] for row in admin_page["items"]}
        restricted_names = {
            row["name"] for row in restricted_page["items"]
        }
        record(
            "admin sees global vehicle-backed nonactive variants",
            {
                "A Variant",
                "Readable Retiring",
                "Hidden Retiring",
            }.issubset(admin_names),
            f"names={sorted(admin_names)}",
        )
        record(
            "restricted actor sees only permission-readable vehicle variant",
            "Readable Retiring" in restricted_names
            and "Hidden Retiring" not in restricted_names,
            f"names={sorted(restricted_names)}",
        )

        admin_active = item_by_name(admin_page, "A Variant")
        restricted_active = item_by_name(
            restricted_page,
            "A Variant",
        )
        record(
            "vehicle quantity remains permission-aware after read switch",
            admin_active is not None
            and restricted_active is not None
            and str(admin_active["vehicle_quantity"]) == "12"
            and str(restricted_active["vehicle_quantity"]) == "5",
            (
                f"admin={None if admin_active is None else admin_active['vehicle_quantity']} "
                f"restricted={None if restricted_active is None else restricted_active['vehicle_quantity']}"
            ),
        )

        if restricted_active is None:
            raise RuntimeError("Restricted active inventory row is missing.")
        expected = {
            "on_hand_quantity": "24",
            "reserved_quantity": "2",
            "available_for_sale_quantity": "12",
            "unavailable_quantity": "10",
            "blocked_quantity": "9",
            "damaged_quantity": "1",
            "minimum_quantity": "12",
        }
        actual = {
            key: str(restricted_active[key])
            for key in expected
        }
        record(
            "projection-backed warehouse quantities match SSOT truth",
            actual == expected,
            f"actual={actual}",
        )

        admin_summary = await summary(
            admin,
            ids["warehouse_id"],
        )
        restricted_summary = await summary(
            restricted,
            ids["warehouse_id"],
        )
        record(
            "company-wide summary uses exact global visibility",
            int(admin_summary["stock_total"]) == 3
            and int(admin_summary["alert_count"]) == 1,
            f"summary={admin_summary}",
        )
        record(
            "restricted summary preserves vehicle permission semantics",
            int(restricted_summary["stock_total"]) == 2
            and int(restricted_summary["alert_count"]) == 1,
            f"summary={restricted_summary}",
        )

        alert_summary = await alerts(
            restricted,
            ids["warehouse_id"],
        )
        alert_page = await page(
            restricted,
            warehouse_id=ids["warehouse_id"],
            only_alerts=True,
        )
        record(
            "projection alert summary and alert seek remain exact",
            int(alert_summary["alert_count"]) == 1
            and [row["name"] for row in alert_page["items"]]
            == ["A Variant"],
            (
                f"summary={alert_summary} "
                f"items={[row['name'] for row in alert_page['items']]}"
            ),
        )

        hidden_search_restricted = await page(
            restricted,
            warehouse_id=ids["warehouse_id"],
            search="Hidden Retiring",
        )
        hidden_search_admin = await page(
            admin,
            warehouse_id=ids["warehouse_id"],
            search="Hidden Retiring",
        )
        record(
            "search cannot bypass vehicle location authorization",
            hidden_search_restricted["items"] == []
            and [
                row["name"]
                for row in hidden_search_admin["items"]
            ] == ["Hidden Retiring"],
        )

    finally:
        await fixture.cleanup_test_companies()
        await cleanup_gate_permission_if_owned(
            bool(ids.get("permission_created_by_gate", 0))
        )

    failures = [
        (name, detail)
        for name, ok, detail in RESULTS
        if not ok
    ]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for name, detail in failures:
        print(f"FAIL:{name}" + (f":{detail}" if detail else ""))
    if failures:
        raise SystemExit(1)
    print("STAGE823_LIVE_STOCK_READ_MODEL_GATE=PASS")


async def main() -> None:
    try:
        await run()
    finally:
        await fixture.engine_app.dispose()
        await fixture.engine_su.dispose()


if __name__ == "__main__":
    asyncio.run(main())
