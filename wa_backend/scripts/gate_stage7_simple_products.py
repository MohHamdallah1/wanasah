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
    from domains.simple_products.service import resolve_price_pair
    from product_import_worker import parse_source, suggest_mapping

    package_only = resolve_price_pair(
        units_per_package=50,
        package_uom_code="CARTON",
        package_price=Decimal("10"),
    )
    unit_only = resolve_price_pair(
        units_per_package=50,
        package_uom_code="CARTON",
        unit_price=Decimal("0.300"),
    )
    independent = resolve_price_pair(
        units_per_package=50,
        package_uom_code="BAG",
        package_price=Decimal("10"),
        unit_price=Decimal("0.300"),
    )
    no_package = resolve_price_pair(
        units_per_package=1,
        package_uom_code=None,
        unit_price=Decimal("0.300"),
    )

    check(
        package_only.unit_price == Decimal("0.200000"),
        "Package-only input derives unit price",
    )
    check(
        unit_only.package_price == Decimal("15.000000"),
        "Unit-only input derives package price",
    )
    check(
        independent.package_price == Decimal("10.000000")
        and independent.unit_price == Decimal("0.300000")
        and not independent.package_derived
        and not independent.unit_derived,
        "Explicit package and unit prices remain independent",
    )
    check(
        no_package.package_price is None
        and no_package.unit_price == Decimal("0.300000"),
        "Unit-only product is supported without an outer package",
    )

    headers, rows = parse_source(
        "products.csv",
        (
            "سعر الوحدة,اسم المنتج,عدد الوحدات في العبوة,نوع العبوة,العائلة\n"
            "0.300,لولو جبنة,50,كرتونة,شيبس لولو\n"
        ).encode("utf-8"),
    )
    suggestions = suggest_mapping(headers)
    check(
        len(rows) == 1
        and suggestions.get("name") == "اسم المنتج"
        and suggestions.get("package_uom") == "نوع العبوة"
        and suggestions.get("units_per_package") == "عدد الوحدات في العبوة"
        and suggestions.get("unit_price") == "سعر الوحدة",
        "Flexible localized import headers map without positional guessing",
    )

    sidebar = (
        ROOT
        / "dashboard/src/components/operations/OperationsSidebar.tsx"
    ).read_text(encoding="utf-8")
    app = (ROOT / "dashboard/src/App.tsx").read_text(encoding="utf-8")
    inventory = (
        ROOT / "dashboard/src/pages/inventory/MainInventory.tsx"
    ).read_text(encoding="utf-8")
    page = (
        ROOT / "dashboard/src/pages/ProductsDashboard.tsx"
    ).read_text(encoding="utf-8")
    backend = (BACKEND / "api/simple_products.py").read_text(encoding="utf-8")
    worker = (BACKEND / "product_import_worker.py").read_text(encoding="utf-8")
    queue = (BACKEND / "product_import_queue.py").read_text(encoding="utf-8")
    models = (BACKEND / "models.py").read_text(encoding="utf-8")
    main_py = (BACKEND / "main.py").read_text(encoding="utf-8")
    auth_fetch = (
        ROOT / "dashboard/src/hooks/useAuthFetch.ts"
    ).read_text(encoding="utf-8")
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")

    check(
        'path: "/products"' in sidebar
        and "التسعير المتقدم" not in sidebar
        and "products.advancedPricing" in page
        and "LockKeyhole" in page,
        "Advanced Pricing is disabled inside Products and absent from Sidebar",
    )
    check(
        '<Route path="/products" element={<ProductsDashboard />} />' in app
        and '<Route path="/pricing" element={<Navigate to="/products" replace />} />'
        in app,
        "Direct legacy pricing navigation remains frozen behind Products",
    )
    check(
        'id: "catalog"' not in inventory
        and "TabProductCatalog" not in inventory,
        "Technical catalog remains hidden from Inventory",
    )
    check(
        "package_uom_code" in page
        and "unit_price" in page
        and "package_barcode" in page
        and "familiesTitle" in page,
        "Simple product flow exposes generalized package, price, barcode and family workflow",
    )
    check(
        'form.append(' in page
        and '"request_id"' in page
        and "fileFingerprint" in page
        and "onDrop=" in page
        and ".xlsx" in page
        and "products.importLimit" in page
        and "MAX_IMPORT_ROWS = 50_000" in worker,
        "Bulk upload has durable request identity, drag/drop and large async import UX",
    )
    check(
        "request_id: UUID = Form(...)" in backend
        and "status_code=202" in backend
        and "enqueue_new_import" in backend
        and "csv_text" not in backend,
        "Bulk import is multipart and asynchronous",
    )
    check(
        "MAX_IMPORT_ROWS = 50_000" in worker
        and "MAX_XLSX_UNCOMPRESSED_BYTES" in worker
        and "MAX_XLSX_COMPRESSION_RATIO" in worker
        and "keep_links=False" in worker,
        "Worker bounds import size and defends XLSX archive hazards",
    )
    check(
        "InventoryAccess(" in worker
        and '"catalog.manage"' in worker
        and '"catalog.publish"' in worker
        and '"pricing.manage"' in worker,
        "Worker re-checks actor permissions at execution time",
    )
    check(
        "ProductImportTerminalError" in worker
        and 'status == "VALIDATING"' in worker
        and 'status == "IMPORTING"' in worker
        and "ProductImportRow.status" in worker
        and '== "VALID"' in worker
        and 'row.status = "IMPORTED"' in worker,
        "Retry path resumes durable phases without replaying committed rows",
    )
    check(
        "pg_advisory_xact_lock" in queue
        and "source_sha256" in queue
        and "existing_size" in queue
        and "replayed" in queue
        and 'lock=f"product-import:{int(company_id)}"' in queue,
        "Import request replay is serialized and rejects changed payload",
    )
    check(
        "request_id = Column(Uuid, nullable=False" in models
        and "uq_product_import_job_request" in models
        and "class ProductImportRow" in models
        and "package_uses_base_barcode" in models,
        "Tenant staging and shared-barcode intent are persisted",
    )
    check(
        "simple_products" in main_py
        and "app.include_router(simple_products.router)" in main_py
        and "product_import_app.open_async()" in main_py,
        "API and queue connector remain registered in application lifecycle",
    )
    check(
        "isFormData" in auth_fetch
        and "NETWORK_UNAVAILABLE" in auth_fetch
        and "REQUEST_TIMEOUT" in auth_fetch,
        "Authenticated transport distinguishes multipart, offline and timeout states",
    )
    check(
        "python-multipart==0.0.20" in requirements
        and "openpyxl==3.1.5" in requirements
        and "procrastinate==3.9.0" in requirements,
        "Pinned import runtime dependencies remain explicit",
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
    check(
        heads_cp.returncode == 0 and len(cli_heads) == 1,
        "Alembic exposes exactly one current head",
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

        procrastinate_table = await conn.scalar(
            text("SELECT to_regclass('public.procrastinate_jobs')")
        )
        check(
            procrastinate_table is not None,
            "Procrastinate durable queue schema is installed",
        )

        runtime_can_create = await conn.scalar(
            text(
                "SELECT has_schema_privilege("
                "current_user, 'public', 'CREATE')"
            )
        )
        check(
            runtime_can_create is False,
            "Runtime database role remains blocked from schema DDL",
        )

        request_unique = await conn.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'uq_product_import_job_request'
                """
            )
        )
        check(
            int(request_unique or 0) == 1,
            "Import request idempotency is enforced by the database",
        )

        for table_name in (
            "product_import_jobs",
            "product_import_rows",
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
                    and "app.current_tenant" in str(row.with_check or "")
                    and "company_id" in str(row.with_check or "")
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
        print("STAGE7_SIMPLE_PRODUCTS_GATE=FAIL")
        return 1

    print("STAGE7_SIMPLE_PRODUCTS_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
