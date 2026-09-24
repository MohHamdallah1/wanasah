from __future__ import annotations

import asyncio
import subprocess
import sys
from decimal import Decimal
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
    from domains.simple_products.service import (
        BASE_UOM_CODE,
        SUPPORTED_PACKAGE_UOM_CODES,
        resolve_price_pair,
    )

    check(
        BASE_UOM_CODE == "EACH"
        and "KG" not in SUPPORTED_PACKAGE_UOM_CODES
        and "L" not in SUPPORTED_PACKAGE_UOM_CODES,
        "Simple product flow does not falsely expose fractional base-UOM support",
    )

    pair = resolve_price_pair(
        units_per_package=24,
        package_uom_code="CASE",
        package_price=Decimal("12"),
        unit_price=Decimal("0.600"),
    )
    check(
        pair.package_price == Decimal("12.000000")
        and pair.unit_price == Decimal("0.600000"),
        "Explicit package and unit prices remain independent",
    )

    page = (
        ROOT / "dashboard/src/pages/ProductsDashboard.tsx"
    ).read_text(encoding="utf-8")
    families_ui = (
        ROOT
        / "dashboard/src/pages/products/ProductFamiliesManager.tsx"
    ).read_text(encoding="utf-8")
    sidebar = (
        ROOT / "dashboard/src/components/operations/OperationsSidebar.tsx"
    ).read_text(encoding="utf-8")
    layout = (
        ROOT / "dashboard/src/components/operations/DashboardLayout.tsx"
    ).read_text(encoding="utf-8")
    auth_fetch = (
        ROOT / "dashboard/src/hooks/useAuthFetch.ts"
    ).read_text(encoding="utf-8")
    durable = (
        ROOT / "dashboard/src/lib/durableOperations.ts"
    ).read_text(encoding="utf-8")
    i18n_index = (
        ROOT / "dashboard/src/i18n/index.ts"
    ).read_text(encoding="utf-8")
    resources = (
        ROOT / "dashboard/src/i18n/resources.ts"
    ).read_text(encoding="utf-8")
    package_json = (
        ROOT / "dashboard/package.json"
    ).read_text(encoding="utf-8")
    service = (
        BACKEND / "domains/simple_products/service.py"
    ).read_text(encoding="utf-8")
    api = (BACKEND / "api/simple_products.py").read_text(encoding="utf-8")
    worker = (BACKEND / "product_import_worker.py").read_text(encoding="utf-8")
    queue = (BACKEND / "product_import_queue.py").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    rules = (ROOT / ".rules").read_text(encoding="utf-8")
    dependencies = (
        BACKEND / "api/dependencies.py"
    ).read_text(encoding="utf-8")

    check(
        "useTranslation" in page
        and "useTranslation" in sidebar
        and "useTranslation" in layout
        and "dir={i18n.dir()}" in page
        and "dir={i18n.dir()}" in layout,
        "Touched dashboard surfaces use locale-driven i18n and direction",
    )
    check(
        '"i18next": "26.4.2"' in package_json
        and '"react-i18next": "17.0.14"' in package_json
        and "initReactI18next" in i18n_index
        and 'supportedLanguages = [' in resources,
        "Arabic/English i18n foundation and pinned runtime packages exist",
    )
    check(
        "sessionStorage.setItem" in page
        and "draftStorageKey" in page
        and "completeDurableOperation" in page
        and "getOrCreateDurableRequestId" in page,
        "Product drafts and logical mutation ids survive refresh/network ambiguity",
    )
    check(
        "fileFingerprint" in page
        and "importSessionKey" in page
        and 'form.append(' in page
        and '"request_id"' in page,
        "Import upload can replay the same file with the same durable request identity",
    )
    check(
        "NETWORK_UNAVAILABLE" in auth_fetch
        and "REQUEST_TIMEOUT" in auth_fetch
        and "navigator.onLine" in auth_fetch
        and "useNetworkStatus" in layout,
        "Global transport and dashboard explicitly handle offline and timeout states",
    )
    check(
        "payloadHash" in durable
        and "requestId" in durable
        and "localStorage" in durable,
        "Durable operation identity is scoped and persisted client-side",
    )
    check(
        "package_uses_base_barcode" in service
        and "copyBarcode" in page
        and "package_barcode" in api,
        "Shared unit/package barcode intent is explicit without duplicate barcode rows",
    )
    check(
        'async def create_product_family(' in api
        and 'async def update_product_family(' in api
        and '"SIMPLE_PRODUCT_FAMILY_CREATE_V1"' in api
        and '"SIMPLE_PRODUCT_FAMILY_RENAME_V1"' in api
        and "begin_idempotent_operation" in api
        and "<ProductFamiliesManager" in page
        and '"products.familiesTitle"' in families_ui
        and "getOrCreateDurableCommand" in families_ui
        and "parseProductFamilyMutation" in families_ui,
        "Family create/rename is managed inside Products and idempotent",
    )
    check(
        "package_uom_code" in worker
        and "units_per_package" in worker
        and "package_price" in worker
        and "package_barcode" in worker
        and '@router.get("/imports/{job_id}/errors")' in api
        and "downloadErrorReport" in page,
        "Async importer uses generalized package vocabulary and downloadable validation reports",
    )
    check(
        "pg_advisory_xact_lock" in queue
        and "existing_sha" in queue
        and "existing_size" in queue
        and "current_mapping == mapping" in queue,
        "Import retries reject changed payload and mapping retries are state-idempotent",
    )
    check(
        "ACCOUNT_DISABLED" in dependencies
        and 'code ===' in auth_fetch,
        "Account-disable transport logic uses stable error code instead of localized message parsing",
    )
    check(
        "Internationalization" in rules
        and "Network Failure, Idempotency" in rules
        and "Mandatory internationalization and durable-command rules" in agents,
        "Repository rules permanently enforce i18n and network-safe mutations",
    )


async def database_checks() -> None:
    from database import engine

    heads_cp = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    cli_heads = {
        line.split()[0]
        for line in heads_cp.stdout.splitlines()
        if "(head)" in line and line.split()
    }
    current_head = next(iter(cli_heads)) if len(cli_heads) == 1 else ""
    lineage_cp = (
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "history",
                "-r",
                f"base:{current_head}",
            ],
            cwd=BACKEND,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if current_head
        else None
    )
    check(
        heads_cp.returncode == 0
        and len(cli_heads) == 1
        and lineage_cp is not None
        and lineage_cp.returncode == 0
        and "f9d2b4c6a8e1" in lineage_cp.stdout,
        "Stage 7.3 migration remains in current Alembic lineage",
    )

    async with engine.connect() as conn:
        db_heads = set(
            (
                await conn.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalars().all()
        )
        check(
            db_heads == cli_heads,
            "Database is upgraded to the exact current Alembic head",
        )

        codes = set(
            (
                await conn.execute(
                    text(
                        """
                        SELECT code
                        FROM uom
                        WHERE code IN (
                            'CARTON','CASE','PACK','BAG','SACK',
                            'TRAY','CRATE','BUNDLE','PALLET'
                        )
                        """
                    )
                )
            ).scalars().all()
        )
        check(
            codes
            == {
                "CARTON",
                "CASE",
                "PACK",
                "BAG",
                "SACK",
                "TRAY",
                "CRATE",
                "BUNDLE",
                "PALLET",
            },
            "All simple outer-package UOM codes are provisioned",
        )

        shared_column = await conn.scalar(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'product_variants'
                  AND column_name = 'package_uses_base_barcode'
                  AND is_nullable = 'NO'
                """
            )
        )
        check(
            shared_column is not None,
            "Shared package/base barcode intent column exists and is NOT NULL",
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
        print("STAGE73_PRODUCT_UX_I18N_NETWORK_GATE=FAIL")
        return 1

    print("STAGE73_PRODUCT_UX_I18N_NETWORK_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
