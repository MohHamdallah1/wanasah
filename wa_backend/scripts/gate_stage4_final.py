from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

_backend_dir = Path(__file__).resolve().parent.parent
_repo_root = _backend_dir.parent
sys.path.insert(0, str(_backend_dir))

from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=False)

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from inventory_access import PERMISSIONS, COMPANY_ONLY
from models import Driver, InventoryTransferHeader, InventoryBalance, SystemAuditLog
from schemas import (
    SpecialTransferDispatchRequest,
    SpecialTransferItem,
    UnifiedReceiveRequest,
    UnifiedDispatchRequest,
    UnifiedTransferItem,
)
from services import (
    InventoryRuleError,
    SPECIAL_TRANSFER_PERMISSION,
    SPECIAL_TRANSFER_PURPOSES,
    TRANSFER_DESTINATION_POLICY_CODE,
    acquire_inventory_location_guards,
    resolve_retiring_warehouse_balancing_override_context,
    resolve_special_transfer_direction_context,
    resolve_special_transfer_terminal_statuses,
    validate_special_transfer_policy_snapshot,
    validate_special_transfer_source_items_locked,
)
from product_lifecycle import acquire_product_lifecycle_guards
from api.warehouse.transfers import (
    special_transfer_dispatch,
    unified_transfer_dispatch,
    unified_transfer_receive,
)

EXPECTED_ALEMBIC_HEAD = "b48467088c16"
EXPECTED_SPECIAL_PURPOSES = {
    "RETURN_TO_VENDOR",
    "QUARANTINE",
    "RECALL_RETURN",
    "DISPOSAL",
}
EXPECTED_SPECIAL_PERMISSIONS = {
    "RETURN_TO_VENDOR": "transfer.special.return_to_vendor",
    "QUARANTINE": "transfer.special.quarantine",
    "RECALL_RETURN": "transfer.special.recall_return",
    "DISPOSAL": "transfer.special.disposal",
}
EXPECTED_PERMISSION_CODES = set(EXPECTED_SPECIAL_PERMISSIONS.values()) | {
    "transfer.warehouse_balancing_override",
}

_migration_url = os.environ["DATABASE_URL_MIGRATION"]
_app_url = os.environ["DATABASE_URL"]

engine_su = create_async_engine(
    _migration_url, echo=False, pool_size=5, max_overflow=5
)
engine_app = create_async_engine(
    _app_url, echo=False, pool_size=5, max_overflow=5
)
Session_su = async_sessionmaker(
    bind=engine_su, expire_on_commit=False, autobegin=False
)
Session_app = async_sessionmaker(
    bind=engine_app, expire_on_commit=False, autobegin=False
)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def set_tenant(conn, company_id: int) -> None:
    await conn.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(int(company_id))},
    )


async def cleanup_company(company_id: int | None) -> None:
    """Hard-delete only the disposable tenant created by this gate.

    Production inventory/audit tables intentionally use RESTRICT in several
    places, so DELETE FROM companies is not a valid cleanup primitive after the
    gate has posted movements. Test cleanup therefore deletes the exact fixture
    graph in dependency order under the migration/superuser connection.
    """
    if not company_id:
        return

    cleanup_tables = (
        "inventory_movement_impacts",
        "inventory_movements",
        "inventory_transfer_lines",
        "inventory_transfer_headers",
        "operation_idempotency",
        "system_audit_logs",
        "inventory_balances",
        "product_locations",
        "tenant_operational_policies",
        "product_batches",
        "product_variants",
        "products",
        "inventory_locations",
        "drivers",
        "branches",
    )

    try:
        async with Session_su() as su:
            await su.begin()
            for table_name in cleanup_tables:
                await su.execute(
                    text(
                        f'DELETE FROM "{table_name}" '
                        "WHERE company_id=:company_id"
                    ),
                    {"company_id": int(company_id)},
                )
            await su.execute(
                text("DELETE FROM companies WHERE id=:company_id"),
                {"company_id": int(company_id)},
            )
            await su.commit()
            print(f"  [CLEANUP] Disposable tenant {company_id} removed")
    except Exception as exc:
        # Cleanup hygiene must be visible, but it is not a Stage-4 business
        # invariant and must not falsify BATCH_DISPOSITION_GATE results.
        print(
            f"  [CLEANUP-WARN] Disposable tenant {company_id} "
            f"was not fully removed — {type(exc).__name__}: {exc}"
        )


async def ensure_gate_uom(conn) -> int:
    existing = (
        await conn.execute(select(text("id")).select_from(text("uom")).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)

    code = f"G{uuid4().hex[:10]}"[:20]
    name = f"Gate-{uuid4().hex[:8]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO uom (name, code) "
                    "VALUES (:name, :code) RETURNING id"
                ),
                {"name": name, "code": code},
            )
        ).scalar_one()
    )


async def make_company(conn) -> int:
    code = f"C{uuid4().hex[:10]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO companies "
                    "(name, company_code, is_active, subscription_status, "
                    "currency_code, timezone, created_at) "
                    "VALUES (:name, :code, true, 'active', 'JOD', "
                    "'Asia/Amman', NOW()) RETURNING id"
                ),
                {"name": f"Stage4Final-{code}", "code": code},
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
                    "VALUES (:c, 'Stage4 Final HQ', :code, true, NOW()) "
                    "RETURNING id"
                ),
                {"c": company_id, "code": code},
            )
        ).scalar_one()
    )


async def make_driver(
    conn,
    company_id: int,
    *,
    is_admin: bool,
    label: str,
) -> int:
    username = f"{label}_{uuid4().hex[:10]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO drivers "
                    "(company_id, username, password_hash, full_name, "
                    "is_active, is_admin, created_at) "
                    "VALUES (:c, :u, '$2b$12$stage4gate', :name, "
                    "true, :is_admin, NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "u": username,
                    "name": f"Stage4 {label}",
                    "is_admin": is_admin,
                },
            )
        ).scalar_one()
    )


async def make_location(
    conn,
    company_id: int,
    branch_id: int | None,
    *,
    location_type: str,
    label: str,
) -> int:
    code = f"{label[:3].upper()}-{uuid4().hex[:8]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO inventory_locations "
                    "(company_id, branch_id, name, code, location_type, "
                    "system_role, is_system_managed, version, is_active, "
                    "created_at, updated_at) "
                    "VALUES (:c, :b, :name, :code, :type, NULL, false, "
                    "1, true, NOW(), NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "b": branch_id,
                    "name": f"Stage4 {label}",
                    "code": code,
                    "type": location_type,
                },
            )
        ).scalar_one()
    )


async def make_policy(
    conn,
    *,
    company_id: int,
    actor_id: int,
    quarantine_id: int,
    disposal_id: int,
    vendor_id: int,
    allow_retiring: bool,
    revision: int = 1,
) -> int:
    policy_payload = {
        "quarantine_location_id": int(quarantine_id),
        "disposal_location_id": int(disposal_id),
        "vendor_return_staging_location_id": int(vendor_id),
        "allow_retiring_warehouse_balancing": bool(allow_retiring),
    }
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO tenant_operational_policies "
                    "(company_id, policy_code, schema_version, revision, "
                    "effective_from, effective_to, validated_payload, status, "
                    "approved_by, approved_at, created_by, created_at, updated_at) "
                    "VALUES (:c, :code, 1, :revision, NOW(), NULL, "
                    "CAST(:payload AS jsonb), 'PUBLISHED', :actor, NOW(), "
                    ":actor, NOW(), NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "code": TRANSFER_DESTINATION_POLICY_CODE,
                    "revision": revision,
                    "payload": json.dumps(policy_payload),
                    "actor": actor_id,
                },
            )
        ).scalar_one()
    )


async def update_policy_payload(
    conn,
    *,
    policy_id: int,
    company_id: int,
    payload: dict,
) -> None:
    await conn.execute(
        text(
            "UPDATE tenant_operational_policies "
            "SET validated_payload=CAST(:payload AS jsonb), updated_at=NOW() "
            "WHERE id=:id AND company_id=:c"
        ),
        {
            "payload": json.dumps(payload),
            "id": policy_id,
            "c": company_id,
        },
    )


async def load_admin(session, company_id: int, driver_id: int) -> Driver:
    return (
        await session.execute(
            select(Driver).where(
                Driver.company_id == company_id,
                Driver.id == driver_id,
            )
        )
    ).scalar_one()


async def make_product_variant(
    conn,
    *,
    company_id: int,
    uom_id: int,
    lifecycle_status: str,
    operational_hold: str,
    label: str,
) -> tuple[int, int]:
    product_code = f"P-{uuid4().hex[:10]}"
    product_id = int(
        (
            await conn.execute(
                text(
                    "INSERT INTO products "
                    "(company_id, code, name, version, created_at, updated_at) "
                    "VALUES (:c, :code, :name, 1, NOW(), NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "code": product_code,
                    "name": f"Gate Product {label}",
                },
            )
        ).scalar_one()
    )

    published_at = datetime.now(timezone.utc).replace(tzinfo=None)
    retired_at = None
    archived_at = None
    if lifecycle_status == "RETIRING":
        published_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        retired_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    elif lifecycle_status == "DRAFT":
        published_at = None
    elif lifecycle_status == "ARCHIVED":
        published_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
        retired_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        archived_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)

    variant_id = int(
        (
            await conn.execute(
                text(
                    "INSERT INTO product_variants "
                    "(company_id, product_id, base_uom_id, name, sku, "
                    "quantity_scale, quantity_step, lot_control_mode, "
                    "expiry_control_mode, lifecycle_status, operational_hold, "
                    "lifecycle_revision, version, published_at, retired_at, "
                    "archived_at, packs_per_carton, default_max_samples_per_day, "
                    "created_at, updated_at) "
                    "VALUES (:c, :p, :uom, :name, :sku, 0, 1, 'REQUIRED', "
                    "'NONE', :lifecycle, :hold, 1, 1, :published, :retired, "
                    ":archived, 50, 0, NOW(), NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "p": product_id,
                    "uom": uom_id,
                    "name": f"Gate Variant {label}",
                    "sku": f"SKU-{uuid4().hex[:12]}",
                    "lifecycle": lifecycle_status,
                    "hold": operational_hold,
                    "published": published_at,
                    "retired": retired_at,
                    "archived": archived_at,
                },
            )
        ).scalar_one()
    )
    return product_id, variant_id


async def make_batch(
    conn,
    *,
    company_id: int,
    variant_id: int,
    disposition: str,
    label: str,
) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO product_batches "
                    "(company_id, product_variant_id, batch_number, "
                    "production_date, expiry_date, disposition, "
                    "disposition_reason, disposition_revision, is_active, "
                    "created_at, updated_at) "
                    "VALUES (:c, :v, :bn, CURRENT_DATE - 5, NULL, :disp, "
                    ":reason, 1, true, NOW(), NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "v": variant_id,
                    "bn": f"BN-{label}-{uuid4().hex[:8]}",
                    "disp": disposition,
                    "reason": (
                        None if disposition == "RELEASED"
                        else f"Stage4 gate {disposition}"
                    ),
                },
            )
        ).scalar_one()
    )


async def make_balance(
    conn,
    *,
    company_id: int,
    location_id: int,
    variant_id: int,
    batch_id: int,
    status: str,
    qty: str = "20",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO inventory_balances "
            "(company_id, location_id, product_variant_id, batch_id, "
            "stock_status, on_hand_quantity, reserved_quantity, last_updated) "
            "VALUES (:c, :l, :v, :b, :s, CAST(:q AS numeric), 0, NOW())"
        ),
        {
            "c": company_id,
            "l": location_id,
            "v": variant_id,
            "b": batch_id,
            "s": status,
            "q": qty,
        },
    )


async def make_product_location(
    conn,
    *,
    company_id: int,
    location_id: int,
    variant_id: int,
    actor_id: int,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO product_locations "
            "(company_id, location_id, product_variant_id, operational_flags, "
            "version, created_by, created_at, updated_at) "
            "VALUES (:c, :l, :v, "
            "'{\"inbound_enabled\": true, \"outbound_enabled\": true}'::jsonb, "
            "1, :actor, NOW(), NOW())"
        ),
        {
            "c": company_id,
            "l": location_id,
            "v": variant_id,
            "actor": actor_id,
        },
    )


def run_subgate(path: Path, label: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=_repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-4:])
    record(label, proc.returncode == 0, tail.replace("\n", " | ")[:700])


def static_contract_tests() -> None:
    print("\n[1] Static contract / source-surface invariants")
    warehouse_src = (_backend_dir / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    services_src = (_backend_dir / "services.py").read_text(encoding="utf-8")
    access_src = (_backend_dir / "inventory_access.py").read_text(encoding="utf-8")

    record(
        "B1/B2/B3/B4 implementation markers exist",
        all(
            marker in services_src
            for marker in (
                "STAGE4E2B1_SPECIAL_TRANSFER_CONTRACT",
                "STAGE4E2B2_SPECIAL_TRANSFER_EXECUTION",
                "STAGE4E2B3_SPECIAL_TRANSFER_TERMINAL_MATRIX",
                "STAGE4E2B4_RETIRING_BALANCING_OVERRIDE",
            )
        ),
    )
    record(
        "Special purposes exact set",
        set(SPECIAL_TRANSFER_PURPOSES) == EXPECTED_SPECIAL_PURPOSES,
        repr(sorted(SPECIAL_TRANSFER_PURPOSES)),
    )
    record(
        "Special purpose permission mapping exact",
        dict(SPECIAL_TRANSFER_PERMISSION) == EXPECTED_SPECIAL_PERMISSIONS,
    )
    record(
        "Special-transfer request has no client destination",
        "destination_location_id"
        not in SpecialTransferDispatchRequest.model_fields,
        repr(sorted(SpecialTransferDispatchRequest.model_fields)),
    )
    record(
        "Special/elevated permissions are in Python allowlist",
        EXPECTED_PERMISSION_CODES <= set(PERMISSIONS),
    )
    record(
        "Special/elevated permissions are company-only",
        EXPECTED_PERMISSION_CODES <= set(COMPANY_ONLY),
    )
    record(
        "Generic transfer map does not own special purposes",
        (
            '"REPLENISHMENT": REPLENISHMENT_NEW' in warehouse_src
            and '"WAREHOUSE_BALANCING": WAREHOUSE_BALANCING' in warehouse_src
            and '"RETURN_TO_VENDOR":' not in warehouse_src.split(
                "_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {", 1
            )[1].split("}", 1)[0]
            and '"QUARANTINE":' not in warehouse_src.split(
                "_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {", 1
            )[1].split("}", 1)[0]
            and '"RECALL_RETURN":' not in warehouse_src.split(
                "_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {", 1
            )[1].split("}", 1)[0]
            and '"DISPOSAL":' not in warehouse_src.split(
                "_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {", 1
            )[1].split("}", 1)[0]
        ),
    )
    record(
        "RETIRING override requires elevated permission",
        'await access.require("transfer.warehouse_balancing_override")'
        in warehouse_src,
    )
    record(
        "RETIRING override audit is explicit",
        'action_type="RETIRING_WAREHOUSE_BALANCING_OVERRIDE"'
        in warehouse_src,
    )
    record(
        "No default-warehouse fallback in Stage4 special/B4 markers",
        (
            "first warehouse" not in services_src.lower()
            and "wh-main" not in services_src.lower()
            and "WH-MAIN" not in warehouse_src
        ),
        "supplemental static scan",
    )
    record(
        "DISPOSAL terminal is pending, never auto-destroy",
        (
            'final_status = "DISPOSAL_PENDING"' in services_src
            and "SPECIAL_TRANSFER_TERMINAL_STATUS" in services_src
        ),
    )
    record(
        "BLOCKED cannot enter QUARANTINE special path",
        "QUARANTINE_SOURCE_BLOCKED" in services_src,
    )
    record(
        "RECALL_RETURN requires active recall at dispatch",
        "RECALL_RETURN_REQUIRES_RECALL" in services_src,
    )
    record(
        "Inventory access source still fail-closed on unknown permissions",
        "raise ValueError('Unknown inventory permission')" in access_src,
    )


async def db_catalog_tests() -> None:
    print("\n[2] Database schema / permission / RLS catalog")
    async with Session_su() as su:
        await su.begin()

        head = str(
            (
                await su.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
        )
        lineage_cp = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "history",
                "-r",
                f"base:{head}",
            ],
            cwd=_backend_dir,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        record(
            "Stage4 migration remains in current Alembic lineage",
            lineage_cp.returncode == 0
            and EXPECTED_ALEMBIC_HEAD in lineage_cp.stdout,
            f"head={head}",
        )

        # Check constraints are created under Base.metadata's naming
        # convention: ck_<table>_<constraint_name>. Long PostgreSQL identifiers
        # may also be truncated by the dialect. Verify the actual DB semantics,
        # not the pre-convention logical names used in model/migration source.
        constraint_rows = (
            await su.execute(
                text(
                    "SELECT c.conrelid::regclass::text AS table_name, "
                    "c.contype, c.conname, "
                    "pg_get_constraintdef(c.oid, true) AS definition "
                    "FROM pg_constraint c "
                    "WHERE c.conrelid = ANY(ARRAY["
                    "'product_batches'::regclass,"
                    "'inventory_balances'::regclass,"
                    "'inventory_transfer_headers'::regclass,"
                    "'inventory_transfer_lines'::regclass"
                    "])"
                )
            )
        ).all()

        checks_by_table: dict[str, list[str]] = {}
        fk_names: set[str] = set()
        for row in constraint_rows:
            table_name = str(row.table_name)
            definition = str(row.definition or "").upper()

            raw_contype = row.contype
            constraint_type = (
                raw_contype.decode("ascii")
                if isinstance(raw_contype, (bytes, bytearray))
                else str(raw_contype)
            )

            if constraint_type == "c":
                checks_by_table.setdefault(table_name, []).append(definition)
            elif constraint_type == "f":
                fk_names.add(str(row.conname))

        def _has_check(
            table_name: str,
            *,
            required: tuple[str, ...],
            forbidden: tuple[str, ...] = (),
        ) -> bool:
            return any(
                all(token in definition for token in required)
                and all(token not in definition for token in forbidden)
                for definition in checks_by_table.get(table_name, [])
            )

        stage4_constraint_semantics = {
            "product_batch_disposition": _has_check(
                "product_batches",
                required=(
                    "DISPOSITION",
                    "RELEASED",
                    "QUARANTINED",
                    "BLOCKED",
                    "RECALLED",
                ),
            ),
            "inventory_balance_status": _has_check(
                "inventory_balances",
                required=(
                    "STOCK_STATUS",
                    "AVAILABLE",
                    "QUARANTINED",
                    "BLOCKED",
                    "RECALLED",
                    "DAMAGED",
                    "DISPOSAL_PENDING",
                ),
            ),
            "inventory_balance_nonavailable_reserved_zero": _has_check(
                "inventory_balances",
                required=("STOCK_STATUS", "AVAILABLE", "RESERVED_QUANTITY"),
            ),
            "transfer_header_purpose": _has_check(
                "inventory_transfer_headers",
                required=(
                    "TRANSFER_PURPOSE",
                    "REPLENISHMENT",
                    "ROUTE_LOAD",
                    "ROUTE_RETURN",
                    "WAREHOUSE_BALANCING",
                    "RETURN_TO_VENDOR",
                    "QUARANTINE",
                    "RECALL_RETURN",
                    "DISPOSAL",
                ),
            ),
            "transfer_header_policy_pair": _has_check(
                "inventory_transfer_headers",
                required=("TENANT_POLICY_ID", "TENANT_POLICY_REVISION"),
                forbidden=("TRANSFER_PURPOSE",),
            ),
            "transfer_header_special_policy_required": _has_check(
                "inventory_transfer_headers",
                required=(
                    "TRANSFER_PURPOSE",
                    "TENANT_POLICY_ID",
                    "TENANT_POLICY_REVISION",
                    "RETURN_TO_VENDOR",
                    "QUARANTINE",
                    "RECALL_RETURN",
                    "DISPOSAL",
                ),
            ),
            "transfer_line_source_status": _has_check(
                "inventory_transfer_lines",
                required=(
                    "SOURCE_STOCK_STATUS",
                    "AVAILABLE",
                    "QUARANTINED",
                    "BLOCKED",
                    "RECALLED",
                    "DAMAGED",
                    "DISPOSAL_PENDING",
                ),
            ),
            "transfer_policy_composite_fk": (
                "fk_transfer_header_tenant_policy_snapshot" in fk_names
            ),
        }
        failed_constraint_semantics = sorted(
            key
            for key, ok in stage4_constraint_semantics.items()
            if not ok
        )
        record(
            "Stage4 database constraint semantics complete",
            not failed_constraint_semantics,
            f"missing_or_wrong={failed_constraint_semantics}",
        )

        db_permissions = set(
            (
                await su.execute(
                    text(
                        "SELECT code FROM permissions "
                        "WHERE code = ANY(:codes)"
                    ),
                    {"codes": sorted(EXPECTED_PERMISSION_CODES)},
                )
            ).scalars().all()
        )
        record(
            "Special/elevated permissions seeded in DB",
            db_permissions == EXPECTED_PERMISSION_CODES,
            f"missing={sorted(EXPECTED_PERMISSION_CODES - db_permissions)}",
        )

        # These are tenant operational tables participating directly in Stage 4.
        # A missing RLS/force flag is a hard SaaS isolation failure, not a warning.
        stage4_rls_tables = [
            "tenant_operational_policies",
            "inventory_locations",
            "product_variants",
            "product_batches",
            "inventory_balances",
            "inventory_transfer_headers",
            "inventory_transfer_lines",
        ]
        rls_rows = (
            await su.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "EXISTS(SELECT 1 FROM pg_policies p "
                    "WHERE p.schemaname='public' AND p.tablename=c.relname) AS has_policy "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
                ),
                {"tables": stage4_rls_tables},
            )
        ).all()
        rls_map = {
            str(row.relname): (
                bool(row.relrowsecurity),
                bool(row.relforcerowsecurity),
                bool(row.has_policy),
            )
            for row in rls_rows
        }
        missing_rls = [
            table
            for table in stage4_rls_tables
            if rls_map.get(table) != (True, True, True)
        ]
        record(
            "Stage4 tenant tables have ENABLE + FORCE RLS + policy",
            not missing_rls,
            f"missing_or_weak={missing_rls}",
        )

        await su.rollback()


async def expect_rule_error(
    *,
    company_id: int,
    source_location_id: int,
    purpose: str,
    item: SimpleNamespace,
    expected_code: str,
) -> None:
    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, company_id)
        await acquire_product_lifecycle_guards(
            app,
            company_id,
            [int(item.product_variant_id)],
            exclusive=False,
        )
        await acquire_inventory_location_guards(
            app,
            company_id,
            [source_location_id],
        )
        try:
            await validate_special_transfer_source_items_locked(
                app,
                company_id=company_id,
                source_location_id=source_location_id,
                transfer_purpose=purpose,
                items=[item],
                as_of_date=date.today(),
            )
        except InventoryRuleError as exc:
            record(
                f"{purpose} rejects invalid source: {expected_code}",
                exc.code == expected_code,
                f"code={exc.code}",
            )
        else:
            record(
                f"{purpose} rejects invalid source: {expected_code}",
                False,
                "unexpected success",
            )
        await app.rollback()


async def expect_source_valid(
    *,
    company_id: int,
    source_location_id: int,
    purpose: str,
    item: SimpleNamespace,
    label: str,
) -> None:
    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, company_id)
        await acquire_product_lifecycle_guards(
            app,
            company_id,
            [int(item.product_variant_id)],
            exclusive=False,
        )
        await acquire_inventory_location_guards(
            app,
            company_id,
            [source_location_id],
        )
        try:
            rows = await validate_special_transfer_source_items_locked(
                app,
                company_id=company_id,
                source_location_id=source_location_id,
                transfer_purpose=purpose,
                items=[item],
                as_of_date=date.today(),
            )
            passed = (
                len(rows) == 1
                and int(rows[0]["product_variant_id"])
                == int(item.product_variant_id)
                and str(rows[0]["source_stock_status"])
                == str(item.source_status)
            )
            record(label, passed)
        except Exception as exc:
            record(label, False, f"{type(exc).__name__}: {exc}")
        await app.rollback()


async def dynamic_stage4_tests() -> None:
    print("\n[3] Dynamic Stage4E.2B special/terminal/RETIRING semantics")
    company_a = company_b = None

    try:
        async with Session_su() as su:
            await su.begin()
            uom_id = await ensure_gate_uom(su)

            company_a = await make_company(su)
            branch_a = await make_branch(su, company_a)
            dispatcher_id = await make_driver(
                su, company_a, is_admin=True, label="Dispatcher"
            )
            receiver_id = await make_driver(
                su, company_a, is_admin=True, label="Receiver"
            )

            source = await make_location(
                su, company_a, branch_a,
                location_type="WAREHOUSE", label="Source",
            )
            normal_dest = await make_location(
                su, company_a, branch_a,
                location_type="WAREHOUSE", label="Dest",
            )
            quarantine = await make_location(
                su, company_a, branch_a,
                location_type="WAREHOUSE", label="Quarantine",
            )
            vendor = await make_location(
                su, company_a, branch_a,
                location_type="WAREHOUSE", label="Vendor",
            )
            disposal = await make_location(
                su, company_a, branch_a,
                location_type="SCRAP", label="Disposal",
            )

            policy_id = await make_policy(
                su,
                company_id=company_a,
                actor_id=dispatcher_id,
                quarantine_id=quarantine,
                disposal_id=disposal,
                vendor_id=vendor,
                allow_retiring=False,
            )

            company_b = await make_company(su)
            branch_b = await make_branch(su, company_b)
            foreign_location = await make_location(
                su, company_b, branch_b,
                location_type="WAREHOUSE", label="Foreign",
            )

            # Healthy ACTIVE / RELEASED / AVAILABLE
            _, healthy_v = await make_product_variant(
                su,
                company_id=company_a,
                uom_id=uom_id,
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                label="Healthy",
            )
            healthy_b = await make_batch(
                su,
                company_id=company_a,
                variant_id=healthy_v,
                disposition="RELEASED",
                label="Healthy",
            )
            await make_balance(
                su,
                company_id=company_a,
                location_id=source,
                variant_id=healthy_v,
                batch_id=healthy_b,
                status="AVAILABLE",
            )

            # QUARANTINED source
            _, quarantine_v = await make_product_variant(
                su,
                company_id=company_a,
                uom_id=uom_id,
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                label="Quarantine",
            )
            quarantine_b = await make_batch(
                su,
                company_id=company_a,
                variant_id=quarantine_v,
                disposition="QUARANTINED",
                label="Quarantine",
            )
            await make_balance(
                su,
                company_id=company_a,
                location_id=source,
                variant_id=quarantine_v,
                batch_id=quarantine_b,
                status="QUARANTINED",
            )

            # BLOCKED source
            _, blocked_v = await make_product_variant(
                su,
                company_id=company_a,
                uom_id=uom_id,
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                label="Blocked",
            )
            blocked_b = await make_batch(
                su,
                company_id=company_a,
                variant_id=blocked_v,
                disposition="BLOCKED",
                label="Blocked",
            )
            await make_balance(
                su,
                company_id=company_a,
                location_id=source,
                variant_id=blocked_v,
                batch_id=blocked_b,
                status="BLOCKED",
            )

            # RECALLED source
            _, recalled_v = await make_product_variant(
                su,
                company_id=company_a,
                uom_id=uom_id,
                lifecycle_status="ACTIVE",
                operational_hold="RECALL",
                label="Recalled",
            )
            recalled_b = await make_batch(
                su,
                company_id=company_a,
                variant_id=recalled_v,
                disposition="RECALLED",
                label="Recalled",
            )
            await make_balance(
                su,
                company_id=company_a,
                location_id=source,
                variant_id=recalled_v,
                batch_id=recalled_b,
                status="RECALLED",
            )

            # RETIRING source for B4
            _, retiring_v = await make_product_variant(
                su,
                company_id=company_a,
                uom_id=uom_id,
                lifecycle_status="RETIRING",
                operational_hold="NONE",
                label="Retiring",
            )
            retiring_b = await make_batch(
                su,
                company_id=company_a,
                variant_id=retiring_v,
                disposition="RELEASED",
                label="Retiring",
            )
            await make_balance(
                su,
                company_id=company_a,
                location_id=source,
                variant_id=retiring_v,
                batch_id=retiring_b,
                status="AVAILABLE",
            )
            await make_product_location(
                su,
                company_id=company_a,
                location_id=source,
                variant_id=retiring_v,
                actor_id=dispatcher_id,
            )
            await make_product_location(
                su,
                company_id=company_a,
                location_id=normal_dest,
                variant_id=retiring_v,
                actor_id=dispatcher_id,
            )

            await su.commit()

        # Policy disabled by default for RETIRING balancing.
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            try:
                await resolve_retiring_warehouse_balancing_override_context(
                    app, company_id=company_a
                )
            except InventoryRuleError as exc:
                record(
                    "RETIRING balancing policy=false is blocked",
                    exc.code
                    == "RETIRING_WAREHOUSE_BALANCING_POLICY_DISABLED",
                    f"code={exc.code}",
                )
            else:
                record(
                    "RETIRING balancing policy=false is blocked",
                    False,
                    "unexpected success",
                )
            await app.rollback()

        # Server-derived destination and no cross-tenant policy destination.
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            direction = await resolve_special_transfer_direction_context(
                app,
                company_id=company_a,
                source_location_id=source,
                transfer_purpose="QUARANTINE",
            )
            record(
                "QUARANTINE destination comes from published tenant policy",
                int(direction["destination_location_id"]) == quarantine
                and int(direction["tenant_policy_id"]) == policy_id,
                f"destination={direction['destination_location_id']}",
            )
            await app.rollback()

        async with Session_su() as su:
            await su.begin()
            bad_payload = {
                "quarantine_location_id": foreign_location,
                "disposal_location_id": disposal,
                "vendor_return_staging_location_id": vendor,
                "allow_retiring_warehouse_balancing": False,
            }
            await update_policy_payload(
                su,
                policy_id=policy_id,
                company_id=company_a,
                payload=bad_payload,
            )
            await su.commit()

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            try:
                await resolve_special_transfer_direction_context(
                    app,
                    company_id=company_a,
                    source_location_id=source,
                    transfer_purpose="QUARANTINE",
                )
            except InventoryRuleError as exc:
                record(
                    "Cross-tenant destination in policy fails closed",
                    exc.code == "TRANSFER_POLICY_STALE",
                    f"code={exc.code}",
                )
            else:
                record(
                    "Cross-tenant destination in policy fails closed",
                    False,
                    "unexpected success",
                )
            await app.rollback()

        good_payload = {
            "quarantine_location_id": quarantine,
            "disposal_location_id": disposal,
            "vendor_return_staging_location_id": vendor,
            "allow_retiring_warehouse_balancing": False,
        }
        async with Session_su() as su:
            await su.begin()
            await update_policy_payload(
                su,
                policy_id=policy_id,
                company_id=company_a,
                payload=good_payload,
            )
            await su.commit()

        healthy_item = SimpleNamespace(
            product_variant_id=healthy_v,
            batch_id=healthy_b,
            source_status="AVAILABLE",
            quantity=Decimal("1"),
            uom_id=uom_id,
        )
        quarantined_item = SimpleNamespace(
            product_variant_id=quarantine_v,
            batch_id=quarantine_b,
            source_status="QUARANTINED",
            quantity=Decimal("2"),
            uom_id=uom_id,
        )
        blocked_item = SimpleNamespace(
            product_variant_id=blocked_v,
            batch_id=blocked_b,
            source_status="BLOCKED",
            quantity=Decimal("2"),
            uom_id=uom_id,
        )
        recalled_item = SimpleNamespace(
            product_variant_id=recalled_v,
            batch_id=recalled_b,
            source_status="RECALLED",
            quantity=Decimal("2"),
            uom_id=uom_id,
        )

        await expect_rule_error(
            company_id=company_a,
            source_location_id=source,
            purpose="DISPOSAL",
            item=healthy_item,
            expected_code="DISPOSAL_NOT_ELIGIBLE",
        )
        await expect_rule_error(
            company_id=company_a,
            source_location_id=source,
            purpose="RETURN_TO_VENDOR",
            item=healthy_item,
            expected_code="RETURN_TO_VENDOR_NOT_ELIGIBLE",
        )
        await expect_rule_error(
            company_id=company_a,
            source_location_id=source,
            purpose="RECALL_RETURN",
            item=healthy_item,
            expected_code="RECALL_RETURN_REQUIRES_RECALL",
        )
        await expect_rule_error(
            company_id=company_a,
            source_location_id=source,
            purpose="QUARANTINE",
            item=blocked_item,
            expected_code="QUARANTINE_SOURCE_BLOCKED",
        )
        await expect_source_valid(
            company_id=company_a,
            source_location_id=source,
            purpose="QUARANTINE",
            item=quarantined_item,
            label="QUARANTINED stock is eligible for QUARANTINE path",
        )
        await expect_source_valid(
            company_id=company_a,
            source_location_id=source,
            purpose="RECALL_RETURN",
            item=recalled_item,
            label="RECALLED stock under RECALL is eligible for RECALL_RETURN",
        )
        await expect_source_valid(
            company_id=company_a,
            source_location_id=source,
            purpose="DISPOSAL",
            item=blocked_item,
            label="BLOCKED stock is eligible for DISPOSAL",
        )

        # Pure terminal resolution against current database state.
        terminal_cases = [
            (
                "QUARANTINE",
                quarantine,
                SimpleNamespace(
                    id=1001,
                    product_variant_id=quarantine_v,
                    batch_id=quarantine_b,
                    source_stock_status="QUARANTINED",
                    lifecycle_revision_snapshot=1,
                    lifecycle_status_snapshot="ACTIVE",
                    operational_hold_snapshot="NONE",
                ),
                "QUARANTINED",
                "QUARANTINE receive stays non-sellable",
            ),
            (
                "RECALL_RETURN",
                quarantine,
                SimpleNamespace(
                    id=1002,
                    product_variant_id=recalled_v,
                    batch_id=recalled_b,
                    source_stock_status="RECALLED",
                    lifecycle_revision_snapshot=1,
                    lifecycle_status_snapshot="ACTIVE",
                    operational_hold_snapshot="RECALL",
                ),
                "RECALLED",
                "RECALL_RETURN receive resolves to RECALLED",
            ),
            (
                "DISPOSAL",
                disposal,
                SimpleNamespace(
                    id=1003,
                    product_variant_id=blocked_v,
                    batch_id=blocked_b,
                    source_stock_status="BLOCKED",
                    lifecycle_revision_snapshot=1,
                    lifecycle_status_snapshot="ACTIVE",
                    operational_hold_snapshot="NONE",
                ),
                "DISPOSAL_PENDING",
                "DISPOSAL receive resolves to DISPOSAL_PENDING",
            ),
            (
                "RETURN_TO_VENDOR",
                vendor,
                SimpleNamespace(
                    id=1004,
                    product_variant_id=quarantine_v,
                    batch_id=quarantine_b,
                    source_stock_status="QUARANTINED",
                    lifecycle_revision_snapshot=1,
                    lifecycle_status_snapshot="ACTIVE",
                    operational_hold_snapshot="NONE",
                ),
                "QUARANTINED",
                "RETURN_TO_VENDOR staging remains non-sellable",
            ),
        ]
        for purpose, destination, line, expected, label in terminal_cases:
            async with Session_app() as app:
                await app.begin()
                await set_tenant(app, company_a)
                statuses = await resolve_special_transfer_terminal_statuses(
                    app,
                    company_id=company_a,
                    destination_location_id=destination,
                    transfer_purpose=purpose,
                    terminal_action="RECEIVE",
                    lines=[line],
                )
                record(
                    label,
                    statuses.get(line.id) == expected,
                    f"status={statuses.get(line.id)}",
                )
                await app.rollback()

        # Policy snapshot survives supersession for valid in-flight terminal docs.
        header_stub = SimpleNamespace(
            id=9001,
            tenant_policy_id=policy_id,
            tenant_policy_revision=1,
            destination_location_id=quarantine,
            transfer_purpose="QUARANTINE",
            commercial_context={
                "schema_version": 1,
                "tenant_policy_code": TRANSFER_DESTINATION_POLICY_CODE,
                "tenant_policy_id": policy_id,
                "tenant_policy_revision": 1,
                "transfer_purpose": "QUARANTINE",
            },
        )
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            evidence = await validate_special_transfer_policy_snapshot(
                app,
                company_id=company_a,
                header=header_stub,
            )
            record(
                "Original policy snapshot validates before supersession",
                evidence["policy_id"] == policy_id
                and evidence["policy_revision"] == 1,
            )
            await app.rollback()

        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE tenant_operational_policies "
                    "SET status='SUPERSEDED', effective_to=NOW(), updated_at=NOW() "
                    "WHERE company_id=:c AND id=:id"
                ),
                {"c": company_a, "id": policy_id},
            )
            await su.commit()

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            evidence = await validate_special_transfer_policy_snapshot(
                app,
                company_id=company_a,
                header=header_stub,
            )
            record(
                "Superseded original policy snapshot remains valid for in-flight terminal",
                evidence["policy_id"] == policy_id,
            )
            bad_header = SimpleNamespace(**vars(header_stub))
            bad_header.destination_location_id = vendor
            try:
                await validate_special_transfer_policy_snapshot(
                    app,
                    company_id=company_a,
                    header=bad_header,
                )
            except InventoryRuleError as exc:
                record(
                    "Tampered special-transfer destination fails policy evidence",
                    exc.code == "SPECIAL_TRANSFER_POLICY_EVIDENCE_INVALID",
                    f"code={exc.code}",
                )
            else:
                record(
                    "Tampered special-transfer destination fails policy evidence",
                    False,
                    "unexpected success",
                )
            await app.rollback()

        # Restore PUBLISHED and enable RETIRING balancing.
        good_payload["allow_retiring_warehouse_balancing"] = True
        async with Session_su() as su:
            await su.begin()
            await su.execute(
                text(
                    "UPDATE tenant_operational_policies "
                    "SET status='PUBLISHED', effective_to=NULL, "
                    "validated_payload=CAST(:payload AS jsonb), updated_at=NOW() "
                    "WHERE company_id=:c AND id=:id"
                ),
                {
                    "c": company_a,
                    "id": policy_id,
                    "payload": json.dumps(good_payload),
                },
            )
            await su.commit()

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            ctx = await resolve_retiring_warehouse_balancing_override_context(
                app, company_id=company_a
            )
            record(
                "RETIRING balancing policy=true returns exact revision evidence",
                int(ctx["tenant_policy_id"]) == policy_id
                and int(ctx["tenant_policy_revision"]) == 1,
            )
            await app.rollback()

        # End-to-end special QUARANTINE dispatch + replay + receive.
        special_request_id = uuid4()
        special_payload = SpecialTransferDispatchRequest(
            request_id=special_request_id,
            source_location_id=source,
            transfer_purpose="QUARANTINE",
            items=[
                SpecialTransferItem(
                    product_variant_id=quarantine_v,
                    batch_id=quarantine_b,
                    source_status="QUARANTINED",
                    quantity=Decimal("2"),
                    uom_id=uom_id,
                )
            ],
            notes="Stage4 final gate quarantine",
        )
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            dispatcher = await load_admin(app, company_a, dispatcher_id)
            first_response = await special_transfer_dispatch(
                payload=special_payload,
                db=app,
                current_admin=dispatcher,
            )
        special_header_id = int(first_response["header_id"])

        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            dispatcher = await load_admin(app, company_a, dispatcher_id)
            replay_response = await special_transfer_dispatch(
                payload=special_payload,
                db=app,
                current_admin=dispatcher,
            )
        record(
            "Special dispatch idempotency replays same document",
            int(replay_response["header_id"]) == special_header_id,
            f"header_id={special_header_id}",
        )

        async with Session_su() as su:
            await su.begin()
            header_row = (
                await su.execute(
                    text(
                        "SELECT tenant_policy_id, tenant_policy_revision, "
                        "destination_location_id, transit_location_id, status "
                        "FROM inventory_transfer_headers "
                        "WHERE company_id=:c AND id=:id"
                    ),
                    {"c": company_a, "id": special_header_id},
                )
            ).one()
            transit_qty = Decimal(
                str(
                    (
                        await su.execute(
                            text(
                                "SELECT COALESCE(SUM(on_hand_quantity),0) "
                                "FROM inventory_balances "
                                "WHERE company_id=:c AND location_id=:l "
                                "AND product_variant_id=:v AND batch_id=:b "
                                "AND stock_status='QUARANTINED'"
                            ),
                            {
                                "c": company_a,
                                "l": int(header_row.transit_location_id),
                                "v": quarantine_v,
                                "b": quarantine_b,
                            },
                        )
                    ).scalar_one()
                )
            )
            await su.rollback()

        record(
            "Special dispatch stores exact policy evidence",
            int(header_row.tenant_policy_id) == policy_id
            and int(header_row.tenant_policy_revision) == 1
            and int(header_row.destination_location_id) == quarantine
            and str(header_row.status) == "IN_TRANSIT",
        )
        record(
            "Special physical dispatch preserves source status in TRANSIT",
            transit_qty == Decimal("2"),
            f"transit_qty={transit_qty}",
        )

        receive_payload = UnifiedReceiveRequest(
            request_id=uuid4(),
            transfer_header_id=special_header_id,
            destination_location_id=quarantine,
        )
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            receiver = await load_admin(app, company_a, receiver_id)
            receive_response = await unified_transfer_receive(
                payload=receive_payload,
                db=app,
                current_admin=receiver,
            )
        record(
            "Special QUARANTINE terminal receive posts successfully",
            receive_response["status"] == "POSTED",
        )

        async with Session_su() as su:
            await su.begin()
            dest_qty = Decimal(
                str(
                    (
                        await su.execute(
                            text(
                                "SELECT COALESCE(SUM(on_hand_quantity),0) "
                                "FROM inventory_balances "
                                "WHERE company_id=:c AND location_id=:l "
                                "AND product_variant_id=:v AND batch_id=:b "
                                "AND stock_status='QUARANTINED'"
                            ),
                            {
                                "c": company_a,
                                "l": quarantine,
                                "v": quarantine_v,
                                "b": quarantine_b,
                            },
                        )
                    ).scalar_one()
                )
            )
            await su.rollback()
        record(
            "QUARANTINE receive lands in QUARANTINED bucket",
            dest_qty == Decimal("2"),
            f"destination_qty={dest_qty}",
        )

        # End-to-end DISPOSAL: BLOCKED -> TRANSIT BLOCKED -> SCRAP DISPOSAL_PENDING.
        disposal_payload = SpecialTransferDispatchRequest(
            request_id=uuid4(),
            source_location_id=source,
            transfer_purpose="DISPOSAL",
            items=[
                SpecialTransferItem(
                    product_variant_id=blocked_v,
                    batch_id=blocked_b,
                    source_status="BLOCKED",
                    quantity=Decimal("2"),
                    uom_id=uom_id,
                )
            ],
            notes="Stage4 final gate disposal",
        )
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            dispatcher = await load_admin(app, company_a, dispatcher_id)
            disposal_dispatch = await special_transfer_dispatch(
                payload=disposal_payload,
                db=app,
                current_admin=dispatcher,
            )
        disposal_header_id = int(disposal_dispatch["header_id"])
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            receiver = await load_admin(app, company_a, receiver_id)
            disposal_receive = await unified_transfer_receive(
                payload=UnifiedReceiveRequest(
                    request_id=uuid4(),
                    transfer_header_id=disposal_header_id,
                    destination_location_id=disposal,
                ),
                db=app,
                current_admin=receiver,
            )
        record(
            "DISPOSAL terminal receive posts successfully",
            disposal_receive["status"] == "POSTED",
        )
        async with Session_su() as su:
            await su.begin()
            disposal_qty = Decimal(
                str(
                    (
                        await su.execute(
                            text(
                                "SELECT COALESCE(SUM(on_hand_quantity),0) "
                                "FROM inventory_balances "
                                "WHERE company_id=:c AND location_id=:l "
                                "AND product_variant_id=:v AND batch_id=:b "
                                "AND stock_status='DISPOSAL_PENDING'"
                            ),
                            {
                                "c": company_a,
                                "l": disposal,
                                "v": blocked_v,
                                "b": blocked_b,
                            },
                        )
                    ).scalar_one()
                )
            )
            await su.rollback()
        record(
            "DISPOSAL ends at DISPOSAL_PENDING, not destruction",
            disposal_qty == Decimal("2"),
            f"disposal_pending_qty={disposal_qty}",
        )

        # B4 end-to-end generic WAREHOUSE_BALANCING for RETIRING.
        retiring_payload = UnifiedDispatchRequest(
            request_id=uuid4(),
            source_location_id=source,
            destination_location_id=normal_dest,
            transfer_purpose="WAREHOUSE_BALANCING",
            items=[
                UnifiedTransferItem(
                    product_variant_id=retiring_v,
                    quantity=Decimal("1"),
                    uom_id=uom_id,
                )
            ],
            notes="Stage4 final gate RETIRING balancing",
        )
        async with Session_app() as app:
            await app.begin()
            await set_tenant(app, company_a)
            dispatcher = await load_admin(app, company_a, dispatcher_id)
            retiring_response = await unified_transfer_dispatch(
                payload=retiring_payload,
                db=app,
                current_admin=dispatcher,
            )
        retiring_header_id = int(retiring_response["header_id"])

        async with Session_su() as su:
            await su.begin()
            retiring_header = (
                await su.execute(
                    text(
                        "SELECT tenant_policy_id, tenant_policy_revision, "
                        "commercial_context FROM inventory_transfer_headers "
                        "WHERE company_id=:c AND id=:id"
                    ),
                    {"c": company_a, "id": retiring_header_id},
                )
            ).one()
            audit_count = int(
                (
                    await su.execute(
                        text(
                            "SELECT COUNT(*) FROM system_audit_logs "
                            "WHERE company_id=:c "
                            "AND target_id=:target "
                            "AND action_type='RETIRING_WAREHOUSE_BALANCING_OVERRIDE'"
                        ),
                        {
                            "c": company_a,
                            "target": f"Transfer_{retiring_header_id}",
                        },
                    )
                ).scalar_one()
            )
            await su.rollback()
        context = dict(retiring_header.commercial_context or {})
        record(
            "RETIRING balancing stores exact policy revision on header/context",
            int(retiring_header.tenant_policy_id) == policy_id
            and int(retiring_header.tenant_policy_revision) == 1
            and context.get("retiring_warehouse_balancing_override") is True
            and context.get("tenant_policy_id") == policy_id
            and context.get("tenant_policy_revision") == 1,
        )
        record(
            "RETIRING balancing override has explicit audit evidence",
            audit_count == 1,
            f"audit_count={audit_count}",
        )

    finally:
        await cleanup_company(company_a)
        await cleanup_company(company_b)


async def cross_tenant_policy_fk_test() -> None:
    print("\n[4] Composite FK / tenant evidence boundary")
    company_a = company_b = None
    try:
        async with Session_su() as su:
            await su.begin()
            company_a = await make_company(su)
            branch_a = await make_branch(su, company_a)
            admin_a = await make_driver(
                su, company_a, is_admin=True, label="A"
            )
            a1 = await make_location(
                su, company_a, branch_a,
                location_type="WAREHOUSE", label="A-Q",
            )
            a2 = await make_location(
                su, company_a, branch_a,
                location_type="SCRAP", label="A-D",
            )
            a3 = await make_location(
                su, company_a, branch_a,
                location_type="WAREHOUSE", label="A-V",
            )
            policy_a = await make_policy(
                su,
                company_id=company_a,
                actor_id=admin_a,
                quarantine_id=a1,
                disposal_id=a2,
                vendor_id=a3,
                allow_retiring=False,
            )

            company_b = await make_company(su)
            branch_b = await make_branch(su, company_b)
            admin_b = await make_driver(
                su, company_b, is_admin=True, label="B"
            )
            b1 = await make_location(
                su, company_b, branch_b,
                location_type="WAREHOUSE", label="B-Q",
            )
            b2 = await make_location(
                su, company_b, branch_b,
                location_type="SCRAP", label="B-D",
            )
            b3 = await make_location(
                su, company_b, branch_b,
                location_type="WAREHOUSE", label="B-V",
            )
            policy_b = await make_policy(
                su,
                company_id=company_b,
                actor_id=admin_b,
                quarantine_id=b1,
                disposal_id=b2,
                vendor_id=b3,
                allow_retiring=False,
            )
            await su.commit()

        # Database must reject company A header referencing company B's policy.
        async with Session_su() as su:
            await su.begin()
            try:
                await su.execute(
                    text(
                        "INSERT INTO inventory_transfer_headers "
                        "(company_id, reference_number, source_location_id, "
                        "destination_location_id, workflow_type, status, "
                        "transfer_purpose, commercial_context, "
                        "tenant_policy_id, tenant_policy_revision, "
                        "dispatched_by, created_at, updated_at) "
                        # DIRECT/DRAFT intentionally avoids every TRANSIT-only
                        # constraint so the only invalid edge in this fixture is
                        # company A -> company B policy evidence.
                        "VALUES (:c, :ref, :src, :dst, 'DIRECT', "
                        "'DRAFT', 'QUARANTINE', '{}'::jsonb, "
                        ":foreign_policy, 1, :actor, NOW(), NOW())"
                    ),
                    {
                        "c": company_a,
                        "ref": f"FK-{uuid4().hex}",
                        "src": a1,
                        "dst": a3,
                        "foreign_policy": policy_b,
                        "actor": admin_a,
                    },
                )
                await su.flush()
            except Exception as exc:
                error_text = str(exc)
                exact_fk_hit = (
                    "fk_transfer_header_tenant_policy_snapshot"
                    in error_text
                )
                record(
                    "Composite FK blocks cross-tenant policy snapshot",
                    exact_fk_hit,
                    (
                        "constraint=fk_transfer_header_tenant_policy_snapshot"
                        if exact_fk_hit
                        else (
                            f"wrong constraint/error: {type(exc).__name__}: "
                            f"{error_text[:500]}"
                        )
                    ),
                )
                await su.rollback()
            else:
                record(
                    "Composite FK blocks cross-tenant policy snapshot",
                    False,
                    "cross-tenant insert unexpectedly succeeded",
                )
                await su.rollback()

        record(
            "Fixture policies are tenant-distinct",
            policy_a != policy_b,
        )

    finally:
        await cleanup_company(company_a)
        await cleanup_company(company_b)


async def main() -> int:
    print("=" * 72)
    print("Stage 4 FINAL Gate — Batch/Expiry/Disposition/Transfer Safety")
    print("=" * 72)

    static_contract_tests()
    await db_catalog_tests()

    print("\n[Regression sub-gates]")
    run_subgate(
        _backend_dir / "scripts" / "stage4d_database.py",
        "Stage4D DB/RLS regression script",
    )
    run_subgate(
        _backend_dir / "scripts" / "stage4d_model_ddl_audit.py",
        "Stage4D model/DDL regression script",
    )
    run_subgate(
        _backend_dir / "scripts" / "gate_stage4e2a_policy.py",
        "Stage4E.2A policy/RLS/race gate",
    )

    await dynamic_stage4_tests()
    await cross_tenant_policy_fk_test()

    await engine_su.dispose()
    await engine_app.dispose()

    print("\n" + "=" * 72)
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print(f"STAGE4_FINAL_RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 72)

    if failed:
        print("BATCH_DISPOSITION_GATE=FAIL")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAILED: {name}" + (f" — {detail}" if detail else ""))
        return 1

    print("BATCH_DISPOSITION_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
