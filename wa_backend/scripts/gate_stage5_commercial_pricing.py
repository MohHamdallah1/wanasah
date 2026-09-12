from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

_backend_dir = Path(__file__).resolve().parent.parent
_repo_root = _backend_dir.parent
sys.path.insert(0, str(_backend_dir))

from dotenv import load_dotenv

load_dotenv(_backend_dir / ".env", override=False)

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from domains.pricing.context import (
    commercial_context_payload,
    lock_route_commercial_context,
)
from domains.pricing.core import PricingError
from domains.pricing.driver_authority import resolve_legacy_driver_prices_bulk
from domains.pricing.publishing import (
    approve_publication,
    create_assignment,
    create_draft_entry,
    create_price_book,
    create_publication,
    publish_publication,
    submit_publication,
    update_draft_entry,
)
from domains.pricing.resolver import resolve_price


EXPECTED_GIT_HEAD = "7e032dfdae65d5cde3b29e549b1d5f15323ae726"
EXPECTED_ALEMBIC_HEAD = "e42b7c9d5a13"
STAGE5_TABLES = (
    "price_books",
    "price_publications",
    "price_book_entries",
    "price_book_assignments",
    "route_commercial_contexts",
)
EXPECTED_TRIGGERS = {
    "trg_published_price_entry_guard",
    "trg_price_publication_history_guard",
    "trg_price_assignment_history_guard",
    "trg_route_commercial_context_immutable",
    "trg_work_session_commercial_context_immutable",
}
EXPECTED_CONSTRAINTS = {
    "excl_price_book_entry_published_overlap",
    "excl_price_book_assignment_equal_priority_overlap",
    "fk_work_session_tenant_commercial_context",
    "uq_work_sessions_commercial_context",
}
EXPECTED_PRICING_PERMISSIONS = {
    "pricing.view",
    "pricing.manage",
    "pricing.approve",
}
FORBIDDEN_LEGACY_PERMISSIONS = {
    "pricing.read",
    "pricing.publish",
    "pricing.assign",
}
TARGET_5F_FILES = (
    "wa_backend/api/pricing.py",
    "dashboard/src/pages/PricingDashboard.tsx",
    "wa_backend/api/dispatch.py",
    "wa_backend/schemas.py",
    "dashboard/src/types/dispatch.ts",
    "dashboard/src/components/dispatch/PendingRoutesTable.tsx",
)

RESULTS: list[tuple[str, bool, str]] = []


class GateFailure(RuntimeError):
    pass


@dataclass
class Fixture:
    company_a: int
    company_b: int
    actor_a: int
    checker_a: int
    actor_b: int
    branch_a: int
    zone_a: int
    shop_a: int
    source_location_a: int
    variant_a: int
    missing_variant_a: int
    uom_id: int
    route_a: int
    created_uom: bool


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")


def must(name: str, condition: bool, detail: str = "") -> None:
    record(name, bool(condition), detail)
    if not condition:
        raise GateFailure(name)


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=_repo_root,
        text=True,
        capture_output=True,
    )


def source_contract_checks() -> None:
    head = run_git("rev-parse", "HEAD")
    must(
        "Git HEAD is reviewed Stage-5 baseline",
        head.returncode == 0 and head.stdout.strip() == EXPECTED_GIT_HEAD,
        head.stdout.strip() if head.returncode == 0 else head.stderr.strip(),
    )

    diff_check = run_git("diff", "--check", "--", *TARGET_5F_FILES)
    must(
        "Stage5F tracked diff has no whitespace errors",
        diff_check.returncode == 0,
        (diff_check.stdout + diff_check.stderr).strip(),
    )

    requirements = {
        "wa_backend/api/pricing.py": (
            '@router.get("/policy")',
            'await _require(db, actor, "pricing.view")',
            "maker_checker_enabled(db, actor.company_id)",
            'return {"maker_checker_enabled": enabled}',
        ),
        "dashboard/src/pages/PricingDashboard.tsx": (
            'authFetch("/pricing/policy")',
            "makerCheckerEnabled === true ? (",
            "makerCheckerEnabled === false ? (",
            'action: "submit"',
            'action: "publish"',
        ),
        "wa_backend/api/dispatch.py": (
            "RouteCommercialContext,",
            ".outerjoin(",
            "RouteCommercialContext.company_id == DispatchRoute.company_id",
            "RouteCommercialContext.dispatch_route_id == DispatchRoute.id",
            '"commercial_context": commercial_context_by_route.get(r.id)',
        ),
        "wa_backend/schemas.py": (
            "class RouteCommercialContextResponse(BaseModel):",
            "pricing_locked_at: str",
            "price_publication_revision: int",
            "assignment_revision: int",
            "commercial_context: Optional[RouteCommercialContextResponse] = None",
        ),
        "dashboard/src/types/dispatch.ts": (
            "export interface RouteCommercialContext {",
            "pricing_locked_at: string;",
            "price_publication_revision: number;",
            "assignment_revision: number;",
            "commercial_context: RouteCommercialContext | null;",
        ),
        "dashboard/src/components/dispatch/PendingRoutesTable.tsx": (
            "formatCommercialLockTime",
            "route.commercial_context",
            "price_publication_revision",
            "assignment_revision",
            "سياق تجاري غير متاح",
        ),
    }

    for rel_path, fragments in requirements.items():
        path = _repo_root / rel_path
        must(f"{rel_path} exists", path.is_file())
        body = path.read_text(encoding="utf-8")
        missing = [fragment for fragment in fragments if fragment not in body]
        must(
            f"{rel_path} Stage5F contract",
            not missing,
            "" if not missing else f"missing={missing}",
        )

    driver_authority = (
        _repo_root / "wa_backend/domains/pricing/driver_authority.py"
    ).read_text(encoding="utf-8")
    must(
        "Driver pricing authority uses locked RouteCommercialContext",
        "as_of=context.pricing_locked_at" in driver_authority
        and "publication_revision_ceiling=int(" in driver_authority
        and "assignment_revision_ceiling=int(context.assignment_revision)"
        in driver_authority,
    )
    must(
        "Driver pricing authority does not read legacy ProductVariant prices",
        "ProductVariant.price_per_pack" not in driver_authority
        and "ProductVariant.price_per_carton" not in driver_authority,
    )

    for rel_path in (
        "wa_backend/api/pricing.py",
        "wa_backend/api/dispatch.py",
        "wa_backend/schemas.py",
    ):
        source = (_repo_root / rel_path).read_text(encoding="utf-8")
        try:
            compile(source, rel_path, "exec")
        except SyntaxError as exc:
            must(f"{rel_path} Python syntax", False, str(exc))
        else:
            record(f"{rel_path} Python syntax", True)


def run_external(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        command = subprocess.list2cmdline(argv)
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            shell=True,
        )
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def frontend_gate() -> None:
    dashboard = _repo_root / "dashboard"
    npm = shutil.which("npm")
    must("npm available", npm is not None, npm or "")
    assert npm is not None

    eslint_cmd = [
        npm,
        "exec",
        "--",
        "eslint",
        "src/pages/PricingDashboard.tsx",
        "src/components/dispatch/PendingRoutesTable.tsx",
        "src/types/dispatch.ts",
    ]
    lint = run_external(eslint_cmd, cwd=dashboard)
    lint_detail = (lint.stdout + lint.stderr).strip()
    must(
        "Stage5F targeted ESLint",
        lint.returncode == 0,
        lint_detail[-1200:] if lint_detail else "",
    )

    build = run_external([npm, "run", "build"], cwd=dashboard)
    build_detail = (build.stdout + build.stderr).strip()
    must(
        "Dashboard production build",
        build.returncode == 0,
        build_detail[-1200:] if build_detail else "",
    )


async def set_tenant(target, company_id: int | None) -> None:
    tenant = "" if company_id is None else str(int(company_id))
    await target.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": tenant},
    )


async def make_company(conn, label: str) -> int:
    code = f"S5-{label}-{uuid4().hex[:10]}"
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
                {"name": f"Stage5 Gate {label}", "code": code},
            )
        ).scalar_one()
    )


async def make_driver(conn, company_id: int, label: str) -> int:
    username = f"s5_{label}_{uuid4().hex[:10]}"
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO drivers "
                    "(company_id, username, password_hash, full_name, "
                    "is_active, is_admin, created_at) "
                    "VALUES (:c, :u, '$2b$12$stage5gate', :name, "
                    "true, true, NOW()) RETURNING id"
                ),
                {
                    "c": company_id,
                    "u": username,
                    "name": f"Stage5 {label}",
                },
            )
        ).scalar_one()
    )


async def ensure_uom(conn) -> tuple[int, bool]:
    existing = (
        await conn.execute(text("SELECT id FROM uom ORDER BY id ASC LIMIT 1"))
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing), False

    code = f"S5{uuid4().hex[:8]}"[:20]
    uom_id = int(
        (
            await conn.execute(
                text(
                    "INSERT INTO uom (name, code) "
                    "VALUES (:name, :code) RETURNING id"
                ),
                {"name": f"Stage5 Gate {code}", "code": code},
            )
        ).scalar_one()
    )
    return uom_id, True


async def make_product_variant(
    conn,
    *,
    company_id: int,
    uom_id: int,
    label: str,
) -> int:
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
                    "code": f"S5P-{uuid4().hex[:10]}",
                    "name": f"Stage5 Product {label}",
                },
            )
        ).scalar_one()
    )
    return int(
        (
            await conn.execute(
                text(
                    "INSERT INTO product_variants "
                    "(company_id, product_id, base_uom_id, name, sku, "
                    "quantity_scale, quantity_step, lot_control_mode, "
                    "expiry_control_mode, lifecycle_status, operational_hold, "
                    "lifecycle_revision, version, published_at, packs_per_carton, "
                    "default_max_samples_per_day, created_at, updated_at) "
                    "VALUES (:c, :p, :uom, :name, :sku, 0, 1, 'REQUIRED', "
                    "'NONE', 'ACTIVE', 'NONE', 1, 1, NOW(), 1, 0, NOW(), NOW()) "
                    "RETURNING id"
                ),
                {
                    "c": company_id,
                    "p": product_id,
                    "uom": uom_id,
                    "name": f"Stage5 Variant {label}",
                    "sku": f"S5SKU-{uuid4().hex[:12]}",
                },
            )
        ).scalar_one()
    )


async def create_fixture(Session_su) -> Fixture:
    async with Session_su() as su:
        await su.begin()
        uom_id, created_uom = await ensure_uom(su)

        company_a = await make_company(su, "A")
        company_b = await make_company(su, "B")
        actor_a = await make_driver(su, company_a, "maker")
        checker_a = await make_driver(su, company_a, "checker")
        actor_b = await make_driver(su, company_b, "sentinel")

        branch_a = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO branches "
                        "(company_id, name, branch_code, is_active, created_at) "
                        "VALUES (:c, 'Stage5 HQ', :code, true, NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "c": company_a,
                        "code": f"S5B-{uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )

        zone_a = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO zones (company_id, name, is_active) "
                        "VALUES (:c, :name, true) RETURNING id"
                    ),
                    {
                        "c": company_a,
                        "name": f"Stage5 Zone {uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )

        shop_a = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO shops "
                        "(company_id, name, zone_id, current_balance, "
                        "max_debt_limit, is_active, created_at, sequence, "
                        "is_archived) "
                        "VALUES (:c, :name, :z, 0, 0, true, NOW(), 1, false) "
                        "RETURNING id"
                    ),
                    {
                        "c": company_a,
                        "z": zone_a,
                        "name": f"Stage5 Shop {uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )

        source_location_a = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO inventory_locations "
                        "(company_id, branch_id, name, code, location_type, "
                        "system_role, is_system_managed, version, is_active, "
                        "created_at, updated_at) "
                        "VALUES (:c, :b, :name, :code, 'WAREHOUSE', NULL, "
                        "false, 1, true, NOW(), NOW()) RETURNING id"
                    ),
                    {
                        "c": company_a,
                        "b": branch_a,
                        "name": "Stage5 Gate Warehouse",
                        "code": f"S5W-{uuid4().hex[:8]}",
                    },
                )
            ).scalar_one()
        )

        variant_a = await make_product_variant(
            su,
            company_id=company_a,
            uom_id=uom_id,
            label="priced",
        )
        missing_variant_a = await make_product_variant(
            su,
            company_id=company_a,
            uom_id=uom_id,
            label="missing-price",
        )

        route_a = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO dispatch_routes "
                        "(company_id, zone_id, driver_id, vehicle_id, "
                        "work_session_id, source_location_id, dispatch_date, "
                        "status, created_at) "
                        "VALUES (:c, :z, NULL, NULL, NULL, :src, CURRENT_DATE, "
                        "'waiting', NOW()) RETURNING id"
                    ),
                    {
                        "c": company_a,
                        "z": zone_a,
                        "src": source_location_a,
                    },
                )
            ).scalar_one()
        )

        for company_id, actor_id, suffix in (
            (company_a, actor_a, "A"),
            (company_b, actor_b, "B"),
        ):
            await su.execute(
                text(
                    "INSERT INTO price_books "
                    "(company_id, code, name, currency_code, status, "
                    "applicability_metadata, version, created_by, "
                    "created_at, updated_at) "
                    "VALUES (:c, :code, :name, 'JOD', 'ACTIVE', "
                    "'{}'::jsonb, 1, :actor, NOW(), NOW())"
                ),
                {
                    "c": company_id,
                    "code": f"RLS-SENTINEL-{suffix}",
                    "name": f"RLS Sentinel {suffix}",
                    "actor": actor_id,
                },
            )

        await su.commit()

    return Fixture(
        company_a=company_a,
        company_b=company_b,
        actor_a=actor_a,
        checker_a=checker_a,
        actor_b=actor_b,
        branch_a=branch_a,
        zone_a=zone_a,
        shop_a=shop_a,
        source_location_a=source_location_a,
        variant_a=variant_a,
        missing_variant_a=missing_variant_a,
        uom_id=uom_id,
        route_a=route_a,
        created_uom=created_uom,
    )


async def cleanup_fixture(Session_su, fixture: Fixture) -> bool:
    try:
        async with Session_su() as su:
            await su.begin()
            for company_id in (fixture.company_a, fixture.company_b):
                for table_name in (
                    "route_commercial_contexts",
                    "price_book_entries",
                    "price_book_assignments",
                    "price_publications",
                    "price_books",
                    "dispatch_routes",
                    "system_settings",
                    "product_uom_conversions",
                    "product_variants",
                    "products",
                    "shops",
                    "inventory_locations",
                    "drivers",
                    "branches",
                    "zones",
                ):
                    await su.execute(
                        text(
                            f'DELETE FROM "{table_name}" '
                            "WHERE company_id=:company_id"
                        ),
                        {"company_id": company_id},
                    )
                await su.execute(
                    text("DELETE FROM companies WHERE id=:company_id"),
                    {"company_id": company_id},
                )
            if fixture.created_uom:
                await su.execute(
                    text("DELETE FROM uom WHERE id=:id"),
                    {"id": fixture.uom_id},
                )
            await su.commit()
        return True
    except Exception as exc:
        print(
            "  [CLEANUP-ERROR] "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return False


async def schema_gate(Session_su) -> None:
    async with Session_su() as su:
        await su.begin()

        alembic = (
            await su.execute(text("SELECT version_num FROM alembic_version"))
        ).scalars().all()
        must(
            "Alembic is at Stage5E head",
            alembic == [EXPECTED_ALEMBIC_HEAD],
            f"actual={alembic}",
        )

        extension = (
            await su.execute(
                text(
                    "SELECT extname FROM pg_extension "
                    "WHERE extname='btree_gist'"
                )
            )
        ).scalar_one_or_none()
        must("btree_gist extension present", extension == "btree_gist")

        table_list = ", ".join(f"'{name}'" for name in STAGE5_TABLES)
        rows = (
            await su.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() "
                    f"AND c.relname IN ({table_list})"
                )
            )
        ).mappings().all()
        rls = {
            str(row["relname"]): (
                bool(row["relrowsecurity"]),
                bool(row["relforcerowsecurity"]),
            )
            for row in rows
        }
        must(
            "All Stage5 tables exist",
            set(rls) == set(STAGE5_TABLES),
            f"found={sorted(rls)}",
        )
        must(
            "All Stage5 tables have ENABLE + FORCE RLS",
            all(rls[name] == (True, True) for name in STAGE5_TABLES),
            str(rls),
        )

        policy_rows = (
            await su.execute(
                text(
                    "SELECT tablename, policyname, qual, with_check "
                    "FROM pg_policies "
                    f"WHERE schemaname=current_schema() "
                    f"AND tablename IN ({table_list})"
                )
            )
        ).mappings().all()
        policies_by_table: dict[str, list[dict]] = {}
        for row in policy_rows:
            policies_by_table.setdefault(str(row["tablename"]), []).append(row)

        policy_ok = True
        policy_detail = []
        for table_name in STAGE5_TABLES:
            rows_for_table = policies_by_table.get(table_name, [])
            if not rows_for_table:
                policy_ok = False
                policy_detail.append(f"{table_name}:missing")
                continue
            joined = " ".join(
                f"{row['qual'] or ''} {row['with_check'] or ''}"
                for row in rows_for_table
            )
            if "app.current_tenant" not in joined:
                policy_ok = False
                policy_detail.append(f"{table_name}:tenant-setting-missing")
        must(
            "Stage5 RLS policies are tenant-context based",
            policy_ok,
            ", ".join(policy_detail),
        )

        columns = set(
            (
                await su.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=current_schema() "
                        "AND table_name='product_variants'"
                    )
                )
            ).scalars().all()
        )
        must(
            "Legacy ProductVariant price columns are absent",
            "price_per_pack" not in columns
            and "price_per_carton" not in columns,
            f"legacy_present={sorted({'price_per_pack','price_per_carton'} & columns)}",
        )

        work_session_columns = set(
            (
                await su.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=current_schema() "
                        "AND table_name='work_sessions'"
                    )
                )
            ).scalars().all()
        )
        must(
            "WorkSession commercial_context_id exists",
            "commercial_context_id" in work_session_columns,
        )

        triggers = set(
            (
                await su.execute(
                    text(
                        "SELECT tg.tgname "
                        "FROM pg_trigger tg "
                        "JOIN pg_class c ON c.oid=tg.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=current_schema() "
                        "AND NOT tg.tgisinternal"
                    )
                )
            ).scalars().all()
        )
        missing_triggers = EXPECTED_TRIGGERS - triggers
        must(
            "Stage5 immutability triggers installed",
            not missing_triggers,
            f"missing={sorted(missing_triggers)}",
        )

        constraints = set(
            (
                await su.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE connamespace = "
                        "(SELECT oid FROM pg_namespace "
                        " WHERE nspname=current_schema())"
                    )
                )
            ).scalars().all()
        )
        missing_constraints = EXPECTED_CONSTRAINTS - constraints
        must(
            "Stage5 exclusion/context constraints installed",
            not missing_constraints,
            f"missing={sorted(missing_constraints)}",
        )

        permissions = set(
            (
                await su.execute(
                    text(
                        "SELECT code FROM permissions "
                        "WHERE code LIKE 'pricing.%'"
                    )
                )
            ).scalars().all()
        )
        must(
            "Canonical pricing permissions installed",
            EXPECTED_PRICING_PERMISSIONS <= permissions,
            f"actual={sorted(permissions)}",
        )
        must(
            "Temporary Stage5B1 pricing permissions removed",
            not (FORBIDDEN_LEGACY_PERMISSIONS & permissions),
            f"legacy={sorted(FORBIDDEN_LEGACY_PERMISSIONS & permissions)}",
        )

        await su.rollback()


async def rls_gate(Session_app, fixture: Fixture) -> None:
    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, None)
        count = int(
            (
                await app.execute(
                    text(
                        "SELECT count(*) FROM price_books "
                        "WHERE code LIKE 'RLS-SENTINEL-%'"
                    )
                )
            ).scalar_one()
        )
        must(
            "RLS fail-closed with no tenant context",
            count == 0,
            f"visible={count}",
        )
        await app.rollback()

    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, fixture.company_a)
        visible = (
            await app.execute(
                text(
                    "SELECT company_id, code FROM price_books "
                    "WHERE code LIKE 'RLS-SENTINEL-%' ORDER BY code"
                )
            )
        ).all()
        must(
            "Tenant A cannot see Tenant B pricing rows",
            len(visible) == 1
            and int(visible[0].company_id) == fixture.company_a
            and str(visible[0].code) == "RLS-SENTINEL-A",
            f"visible={visible}",
        )
        await app.rollback()

    async with Session_app() as app:
        await app.begin()
        await set_tenant(app, fixture.company_b)
        visible = (
            await app.execute(
                text(
                    "SELECT company_id, code FROM price_books "
                    "WHERE code LIKE 'RLS-SENTINEL-%' ORDER BY code"
                )
            )
        ).all()
        must(
            "Tenant B cannot see Tenant A pricing rows",
            len(visible) == 1
            and int(visible[0].company_id) == fixture.company_b
            and str(visible[0].code) == "RLS-SENTINEL-B",
            f"visible={visible}",
        )
        await app.rollback()


async def set_maker_checker(db, company_id: int, enabled: bool) -> None:
    await db.execute(
        text(
            "INSERT INTO system_settings "
            "(company_id, setting_key, setting_value, description) "
            "VALUES (:c, 'pricing_maker_checker_enabled', :v, "
            "'Stage5 final gate') "
            "ON CONFLICT (company_id, setting_key) DO UPDATE "
            "SET setting_value=EXCLUDED.setting_value, "
            "description=EXCLUDED.description"
        ),
        {"c": company_id, "v": "true" if enabled else "false"},
    )


async def expect_pricing_error(
    name: str,
    expected_code: str,
    action: Callable[[], Awaitable[object]],
) -> PricingError:
    try:
        await action()
    except PricingError as exc:
        must(
            name,
            exc.code == expected_code,
            f"expected={expected_code}, actual={exc.code}",
        )
        return exc
    except Exception as exc:
        must(
            name,
            False,
            f"unexpected {type(exc).__name__}: {exc}",
        )
        raise
    else:
        must(name, False, f"expected {expected_code}, operation succeeded")
        raise GateFailure(name)


async def expect_db_guard(
    db,
    *,
    name: str,
    sql: str,
    params: dict,
) -> None:
    try:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        must(
            name,
            sqlstate == "55000",
            f"sqlstate={sqlstate}, error={exc.orig}",
        )
    else:
        must(name, False, "database mutation unexpectedly succeeded")


async def make_direct_price(
    db,
    *,
    fixture: Fixture,
    code: str,
    amount: Decimal,
):
    book = await create_price_book(
        db,
        company_id=fixture.company_a,
        actor_id=fixture.actor_a,
        code=code,
        name=f"Stage5 {code}",
        currency_code="JOD",
        applicability_metadata={},
    )
    publication = await create_publication(
        db,
        company_id=fixture.company_a,
        actor_id=fixture.actor_a,
        book_id=int(book.id),
        expected_book_version=int(book.version),
        effective_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        request_id=uuid4(),
    )
    entry = await create_draft_entry(
        db,
        company_id=fixture.company_a,
        publication_id=int(publication.id),
        expected_publication_version=int(publication.version),
        product_variant_id=fixture.variant_a,
        uom_id=fixture.uom_id,
        amount=amount,
        effective_from=publication.effective_at,
        effective_to=None,
        priority=0,
        metadata={},
    )
    await db.refresh(publication)
    await publish_publication(
        db,
        company_id=fixture.company_a,
        actor_id=fixture.actor_a,
        publication_id=int(publication.id),
        expected_version=int(publication.version),
    )
    await db.refresh(publication)
    await db.refresh(entry)
    return book, publication, entry


async def business_gate(Session_app, fixture: Fixture) -> None:
    async with Session_app() as db:
        await db.begin()
        await set_tenant(db, fixture.company_a)

        try:
            await set_maker_checker(db, fixture.company_a, False)

            default_book, default_pub, default_entry = await make_direct_price(
                db,
                fixture=fixture,
                code=f"S5-DEFAULT-{uuid4().hex[:8]}",
                amount=Decimal("10.000000"),
            )
            default_assignment = await create_assignment(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                price_book_id=int(default_book.id),
                scope_type="COMPANY_DEFAULT",
                scope_id=None,
                priority=10,
                effective_from=datetime.now(timezone.utc)
                - timedelta(minutes=10),
                effective_to=None,
            )

            branch_book, branch_pub, branch_entry = await make_direct_price(
                db,
                fixture=fixture,
                code=f"S5-BRANCH-{uuid4().hex[:8]}",
                amount=Decimal("20.000000"),
            )
            branch_assignment = await create_assignment(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                price_book_id=int(branch_book.id),
                scope_type="BRANCH",
                scope_id=fixture.branch_a,
                priority=10,
                effective_from=datetime.now(timezone.utc)
                - timedelta(minutes=10),
                effective_to=None,
            )

            customer_book, customer_pub, customer_entry = await make_direct_price(
                db,
                fixture=fixture,
                code=f"S5-CUSTOMER-{uuid4().hex[:8]}",
                amount=Decimal("30.000000"),
            )
            customer_assignment = await create_assignment(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                price_book_id=int(customer_book.id),
                scope_type="CUSTOMER",
                scope_id=fixture.shop_a,
                priority=10,
                effective_from=datetime.now(timezone.utc)
                - timedelta(minutes=10),
                effective_to=None,
            )

            resolve_at = datetime.now(timezone.utc)

            resolved_default = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                as_of=resolve_at,
            )
            must(
                "Resolver precedence: COMPANY_DEFAULT",
                resolved_default.amount == Decimal("10.000000")
                and resolved_default.assignment_scope_type
                == "COMPANY_DEFAULT",
                str(resolved_default),
            )

            resolved_branch = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                branch_id=fixture.branch_a,
                as_of=resolve_at,
            )
            must(
                "Resolver precedence: BRANCH > COMPANY_DEFAULT",
                resolved_branch.amount == Decimal("20.000000")
                and resolved_branch.assignment_scope_type == "BRANCH",
                str(resolved_branch),
            )

            resolved_customer_1 = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                customer_id=fixture.shop_a,
                branch_id=fixture.branch_a,
                as_of=resolve_at,
            )
            resolved_customer_2 = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                customer_id=fixture.shop_a,
                branch_id=fixture.branch_a,
                as_of=resolve_at,
            )
            must(
                "Resolver precedence: CUSTOMER > BRANCH",
                resolved_customer_1.amount == Decimal("30.000000")
                and resolved_customer_1.assignment_scope_type == "CUSTOMER",
                str(resolved_customer_1),
            )
            must(
                "Deterministic resolver: same query returns identical result",
                resolved_customer_1 == resolved_customer_2,
            )

            await expect_pricing_error(
                "No-price path fails closed without fallback",
                "PRICE_NOT_RESOLVED",
                lambda: resolve_price(
                    db,
                    company_id=fixture.company_a,
                    product_variant_id=fixture.missing_variant_a,
                    uom_id=fixture.uom_id,
                    customer_id=fixture.shop_a,
                    branch_id=fixture.branch_a,
                    as_of=resolve_at,
                ),
            )

            await expect_pricing_error(
                "Application layer rejects published entry edits",
                "PRICE_ENTRY_IMMUTABLE",
                lambda: update_draft_entry(
                    db,
                    company_id=fixture.company_a,
                    entry_id=int(customer_entry.id),
                    expected_entry_version=int(customer_entry.version),
                    expected_publication_version=int(customer_pub.version),
                    amount=Decimal("99.000000"),
                    effective_from=customer_entry.effectivity.lower,
                    effective_to=None,
                    priority=0,
                    metadata={},
                ),
            )

            await expect_db_guard(
                db,
                name="DB trigger rejects published price amount mutation",
                sql=(
                    "UPDATE price_book_entries SET amount=99 "
                    "WHERE company_id=:c AND id=:id"
                ),
                params={
                    "c": fixture.company_a,
                    "id": int(customer_entry.id),
                },
            )
            await expect_db_guard(
                db,
                name="DB trigger rejects published publication deletion",
                sql=(
                    "DELETE FROM price_publications "
                    "WHERE company_id=:c AND id=:id"
                ),
                params={
                    "c": fixture.company_a,
                    "id": int(customer_pub.id),
                },
            )
            await expect_db_guard(
                db,
                name="DB trigger rejects assignment deletion",
                sql=(
                    "DELETE FROM price_book_assignments "
                    "WHERE company_id=:c AND id=:id"
                ),
                params={
                    "c": fixture.company_a,
                    "id": int(customer_assignment.id),
                },
            )

            await set_maker_checker(db, fixture.company_a, True)
            maker_book = await create_price_book(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                code=f"S5-MC-{uuid4().hex[:8]}",
                name="Stage5 Maker Checker",
                currency_code="JOD",
                applicability_metadata={},
            )
            maker_pub = await create_publication(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                book_id=int(maker_book.id),
                expected_book_version=int(maker_book.version),
                effective_at=datetime.now(timezone.utc)
                - timedelta(minutes=5),
                request_id=uuid4(),
            )
            await create_draft_entry(
                db,
                company_id=fixture.company_a,
                publication_id=int(maker_pub.id),
                expected_publication_version=int(maker_pub.version),
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                amount=Decimal("40.000000"),
                effective_from=maker_pub.effective_at,
                effective_to=None,
                priority=0,
                metadata={},
            )
            await db.refresh(maker_pub)

            await expect_pricing_error(
                "Maker/Checker blocks direct publish",
                "PRICING_APPROVAL_REQUIRED",
                lambda: publish_publication(
                    db,
                    company_id=fixture.company_a,
                    actor_id=fixture.actor_a,
                    publication_id=int(maker_pub.id),
                    expected_version=int(maker_pub.version),
                ),
            )

            await submit_publication(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                publication_id=int(maker_pub.id),
                expected_version=int(maker_pub.version),
            )
            await db.refresh(maker_pub)
            must(
                "Maker/Checker submit reaches PENDING_APPROVAL",
                maker_pub.status == "PENDING_APPROVAL",
                str(maker_pub.status),
            )

            await expect_pricing_error(
                "Maker cannot approve own publication",
                "PRICING_SEPARATION_OF_DUTIES",
                lambda: approve_publication(
                    db,
                    company_id=fixture.company_a,
                    actor_id=fixture.actor_a,
                    publication_id=int(maker_pub.id),
                    expected_version=int(maker_pub.version),
                ),
            )

            await approve_publication(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.checker_a,
                publication_id=int(maker_pub.id),
                expected_version=int(maker_pub.version),
            )
            await db.refresh(maker_pub)
            must(
                "Independent checker publishes successfully",
                maker_pub.status == "PUBLISHED"
                and int(maker_pub.approved_by) == fixture.checker_a,
                f"status={maker_pub.status}, approved_by={maker_pub.approved_by}",
            )

            await set_maker_checker(db, fixture.company_a, False)

            context_1 = await lock_route_commercial_context(
                db,
                company_id=fixture.company_a,
                dispatch_route_id=fixture.route_a,
            )
            context_2 = await lock_route_commercial_context(
                db,
                company_id=fixture.company_a,
                dispatch_route_id=fixture.route_a,
            )
            must(
                "RouteCommercialContext lock is idempotent",
                int(context_1.id) == int(context_2.id),
                f"{context_1.id} vs {context_2.id}",
            )
            payload = commercial_context_payload(context_1)
            must(
                "RouteCommercialContext payload carries lock + revision ceilings",
                payload["pricing_locked_at"] is not None
                and payload["price_publication_revision"] > 0
                and payload["assignment_revision"] > 0
                and payload["transaction_currency_code"] == "JOD",
                str(payload),
            )

            frozen_before = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                customer_id=fixture.shop_a,
                branch_id=fixture.branch_a,
                as_of=context_1.pricing_locked_at,
                publication_revision_ceiling=int(
                    context_1.price_publication_revision
                ),
                assignment_revision_ceiling=int(
                    context_1.assignment_revision
                ),
            )
            must(
                "Locked context resolves the customer price",
                frozen_before.amount == Decimal("30.000000"),
                str(frozen_before),
            )

            driver_prices = await resolve_legacy_driver_prices_bulk(
                db,
                company_id=fixture.company_a,
                dispatch_route_id=fixture.route_a,
                variant_ids=[fixture.variant_a],
                customer_id=fixture.shop_a,
                expected_commercial_context_id=int(context_1.id),
            )
            driver_price = driver_prices[fixture.variant_a]
            must(
                "Driver authority resolves price from locked context",
                driver_price.price_per_pack == Decimal("30.000")
                and driver_price.price_per_carton == Decimal("30.000")
                and driver_price.pack_resolution.price_publication_revision
                <= int(context_1.price_publication_revision)
                and driver_price.pack_resolution.assignment_revision
                <= int(context_1.assignment_revision),
                str(driver_price),
            )

            backdated_pub = await create_publication(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                book_id=int(customer_book.id),
                expected_book_version=int(customer_book.version),
                effective_at=context_1.pricing_locked_at,
                request_id=uuid4(),
            )
            await create_draft_entry(
                db,
                company_id=fixture.company_a,
                publication_id=int(backdated_pub.id),
                expected_publication_version=int(backdated_pub.version),
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                amount=Decimal("31.000000"),
                effective_from=context_1.pricing_locked_at,
                effective_to=None,
                priority=0,
                metadata={},
            )
            await db.refresh(backdated_pub)
            await expect_pricing_error(
                "Locked commercial history blocks price backdating",
                "COMMERCIAL_CONTEXT_LOCKED",
                lambda: publish_publication(
                    db,
                    company_id=fixture.company_a,
                    actor_id=fixture.actor_a,
                    publication_id=int(backdated_pub.id),
                    expected_version=int(backdated_pub.version),
                ),
            )

            await expect_pricing_error(
                "Locked commercial history blocks assignment backdating",
                "COMMERCIAL_CONTEXT_LOCKED",
                lambda: create_assignment(
                    db,
                    company_id=fixture.company_a,
                    actor_id=fixture.actor_a,
                    price_book_id=int(customer_book.id),
                    scope_type="CUSTOMER",
                    scope_id=fixture.shop_a,
                    priority=int(customer_assignment.priority),
                    effective_from=context_1.pricing_locked_at,
                    effective_to=None,
                ),
            )

            future_start = context_1.pricing_locked_at + timedelta(seconds=2)
            future_pub = await create_publication(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                book_id=int(customer_book.id),
                expected_book_version=int(customer_book.version),
                effective_at=future_start,
                request_id=uuid4(),
            )
            await create_draft_entry(
                db,
                company_id=fixture.company_a,
                publication_id=int(future_pub.id),
                expected_publication_version=int(future_pub.version),
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                amount=Decimal("35.000000"),
                effective_from=future_start,
                effective_to=None,
                priority=0,
                metadata={},
            )
            await db.refresh(future_pub)
            await publish_publication(
                db,
                company_id=fixture.company_a,
                actor_id=fixture.actor_a,
                publication_id=int(future_pub.id),
                expected_version=int(future_pub.version),
            )
            await db.refresh(future_pub)
            must(
                "A later non-backdated publication is allowed",
                future_pub.status == "PUBLISHED",
                str(future_pub.status),
            )

            live_future = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                customer_id=fixture.shop_a,
                branch_id=fixture.branch_a,
                as_of=future_start + timedelta(seconds=1),
            )
            frozen_after = await resolve_price(
                db,
                company_id=fixture.company_a,
                product_variant_id=fixture.variant_a,
                uom_id=fixture.uom_id,
                customer_id=fixture.shop_a,
                branch_id=fixture.branch_a,
                as_of=context_1.pricing_locked_at,
                publication_revision_ceiling=int(
                    context_1.price_publication_revision
                ),
                assignment_revision_ceiling=int(
                    context_1.assignment_revision
                ),
            )
            must(
                "Live pricing advances to the newer revision",
                live_future.amount == Decimal("35.000000"),
                str(live_future),
            )
            must(
                "Locked route remains on its original commercial history",
                frozen_after == frozen_before
                and frozen_after.amount == Decimal("30.000000"),
                f"before={frozen_before}, after={frozen_after}",
            )

            await expect_db_guard(
                db,
                name="RouteCommercialContext is immutable at DB layer",
                sql=(
                    "UPDATE route_commercial_contexts "
                    "SET assignment_revision=assignment_revision + 1 "
                    "WHERE company_id=:c AND id=:id"
                ),
                params={
                    "c": fixture.company_a,
                    "id": int(context_1.id),
                },
            )

            record(
                "Commercial pricing runtime scenario completed",
                True,
                (
                    f"default_assignment={default_assignment.id}, "
                    f"branch_assignment={branch_assignment.id}, "
                    f"customer_assignment={customer_assignment.id}, "
                    f"context={context_1.id}"
                ),
            )
        finally:
            await db.rollback()


async def run_db_gate() -> None:
    migration_url = os.environ.get("DATABASE_URL_MIGRATION")
    app_url = os.environ.get("DATABASE_URL")
    must(
        "DATABASE_URL_MIGRATION configured",
        bool(migration_url),
    )
    must("DATABASE_URL configured", bool(app_url))

    engine_su = create_async_engine(
        migration_url,
        echo=False,
        pool_size=5,
        max_overflow=5,
    )
    engine_app = create_async_engine(
        app_url,
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

    fixture: Fixture | None = None
    try:
        await schema_gate(Session_su)
        fixture = await create_fixture(Session_su)
        record(
            "Disposable Stage5 tenants created",
            True,
            f"tenant_a={fixture.company_a}, tenant_b={fixture.company_b}",
        )
        await rls_gate(Session_app, fixture)
        await business_gate(Session_app, fixture)
    finally:
        if fixture is not None:
            cleaned = await cleanup_fixture(Session_su, fixture)
            record(
                "Disposable Stage5 tenant cleanup",
                cleaned,
                "" if cleaned else "manual cleanup required; see error above",
            )
        await engine_app.dispose()
        await engine_su.dispose()


async def main() -> int:
    print("STAGE5_COMMERCIAL_PRICING_FINAL_GATE")
    print(f"EXPECTED_HEAD={EXPECTED_GIT_HEAD}")
    print(f"EXPECTED_ALEMBIC_HEAD={EXPECTED_ALEMBIC_HEAD}")

    phases: list[tuple[str, Callable[[], object]]] = [
        ("Source/5F contract phase", source_contract_checks),
    ]

    for phase_name, phase in phases:
        try:
            phase()
        except Exception as exc:
            if not isinstance(exc, GateFailure):
                record(
                    phase_name,
                    False,
                    f"{type(exc).__name__}: {exc}",
                )

    try:
        await run_db_gate()
    except Exception as exc:
        if not isinstance(exc, GateFailure):
            record(
                "Database/runtime phase",
                False,
                f"{type(exc).__name__}: {exc}",
            )

    try:
        frontend_gate()
    except Exception as exc:
        if not isinstance(exc, GateFailure):
            record(
                "Frontend gate phase",
                False,
                f"{type(exc).__name__}: {exc}",
            )

    failures = [item for item in RESULTS if not item[1]]
    print()
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    if failures:
        print("COMMERCIAL_PRICING_GATE=FAIL")
        for name, _, detail in failures:
            print(f"  - {name}" + (f": {detail}" if detail else ""))
        return 1

    print("COMMERCIAL_PRICING_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
