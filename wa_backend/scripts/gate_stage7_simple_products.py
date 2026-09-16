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

    carton_only = resolve_price_pair(
        units_per_carton=50,
        carton_price=Decimal("10"),
    )
    unit_only = resolve_price_pair(
        units_per_carton=50,
        unit_price=Decimal("0.300"),
    )
    independent = resolve_price_pair(
        units_per_carton=50,
        carton_price=Decimal("10"),
        unit_price=Decimal("0.300"),
    )
    check(
        carton_only.carton_price == Decimal("10.000000")
        and carton_only.unit_price == Decimal("0.200000")
        and carton_only.unit_derived,
        "Carton-only input derives unit price",
    )
    check(
        unit_only.carton_price == Decimal("15.000000")
        and unit_only.unit_price == Decimal("0.300000")
        and unit_only.carton_derived,
        "Unit-only input derives carton price",
    )
    check(
        independent.carton_price == Decimal("10.000000")
        and independent.unit_price == Decimal("0.300000")
        and not independent.carton_derived
        and not independent.unit_derived,
        "Explicit carton and unit prices remain independent",
    )

    headers, rows = parse_source(
        "products.csv",
        (
            "\ufeffسعر الحبة,اسم المنتج,عدد الحبات في الكرتونة,العائلة\n"
            "0.300,لولو جبنة,50,شيبس لولو\n"
        ).encode("utf-8"),
    )
    suggestions = suggest_mapping(headers)
    check(
        len(rows) == 1
        and suggestions.get("name") == "اسم المنتج"
        and suggestions.get("units_per_carton") == "عدد الحبات في الكرتونة"
        and suggestions.get("unit_price") == "سعر الحبة",
        "Flexible CSV column order is detected without positional guessing",
    )

    sidebar = (
        ROOT / "dashboard/src/components/operations/OperationsSidebar.tsx"
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
        'label: "المنتجات"' in sidebar
        and 'path: "/products"' in sidebar
        and 'label: "التسعير المتقدم"' in sidebar
        and 'disabled: true' in sidebar,
        "Sidebar keeps Advanced Pricing visible but globally disabled",
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
        "سعر الكرتونة" in page
        and "سعر الحبة" in page
        and "باركود الحبة" in page
        and "باركود الكرتونة" in page
        and "العائلة" in page,
        "Simple product flow exposes both prices, optional barcodes and family",
    )
    check(
        'form.append("request_id", importRequestId)' in page
        and "onDrop=" in page
        and ".xlsx" in page
        and "تحميل النموذج" in page
        and "50,000" in page,
        "Bulk upload has stable idempotency key, drag/drop, XLSX/CSV and template",
    )
    check(
        "request_id: UUID = Form(...)" in backend
        and 'status_code=202' in backend
        and "enqueue_new_import" in backend
        and "csv_text" not in backend,
        "Bulk import is multipart + asynchronous instead of synchronous CSV text",
    )
    check(
        "MAX_IMPORT_ROWS = 50_000" in worker
        and "MAX_XLSX_UNCOMPRESSED_BYTES" in worker
        and "MAX_XLSX_COMPRESSION_RATIO" in worker
        and "keep_links=False" in worker,
        "Worker bounds row count and defends XLSX decompression/external-link hazards",
    )
    check(
        "InventoryAccess(db, actor)" in worker
        and '"catalog.manage"' in worker
        and '"catalog.publish"' in worker
        and '"pricing.manage"' in worker,
        "Worker re-checks authorization at execution time",
    )
    check(
        "ProductImportTerminalError" in worker
        and 'status == "VALIDATING"' in worker
        and 'status == "IMPORTING"' in worker
        and 'ProductImportRow.status == "VALID"' in worker,
        "Retry path resumes the durable phase without re-importing committed rows",
    )
    check(
        "PsycopgConnector" in queue
        and "connection=conn" in queue
        and 'lock=f"product-import:{int(company_id)}"' in queue
        and "retry_failed_import" in queue,
        "Queue uses atomic external connection, per-company lock and controlled retry",
    )
    check(
        "request_id = Column(Uuid, nullable=False" in models
        and "uq_product_import_job_request" in models
        and "class ProductImportRow" in models,
        "Tenant staging has request idempotency and resumable row state",
    )
    check(
        "simple_products" in main_py
        and "app.include_router(simple_products.router)" in main_py
        and "product_import_app.open_async()" in main_py,
        "API and queue connector are registered in application lifecycle",
    )
    check(
        "isFormData" in auth_fetch
        and "timeoutMs" in auth_fetch
        and '...(isFormData ? {} : { "Content-Type": "application/json" })'
        in auth_fetch,
        "Authenticated transport preserves multipart boundary and upload timeout",
    )
    check(
        "python-multipart==0.0.20" in requirements
        and "openpyxl==3.1.5" in requirements
        and "procrastinate==3.9.0" in requirements,
        "Pinned import runtime dependencies are explicit",
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
        heads_cp.returncode == 0 and cli_heads == {"f8c4e6a2b1d9"},
        "Async product import migration is the single Alembic head",
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
            text("SELECT to_regclass('procrastinate_jobs')")
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

        queue_table_privileges = await conn.scalar(
            text(
                """
                SELECT bool_and(
                    has_table_privilege(
                        current_user,
                        c.oid,
                        'SELECT,INSERT,UPDATE,DELETE'
                    )
                )
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND c.relname IN (
                      'procrastinate_workers',
                      'procrastinate_jobs',
                      'procrastinate_periodic_defers',
                      'procrastinate_events'
                  )
                """
            )
        )
        check(
            bool(queue_table_privileges),
            "Runtime database role has exact queue table DML privileges",
        )

        queue_sequence_privileges = await conn.scalar(
            text(
                """
                SELECT bool_and(
                    has_sequence_privilege(
                        current_user,
                        c.oid,
                        'USAGE,SELECT,UPDATE'
                    )
                )
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'S'
                  AND c.relname LIKE 'procrastinate_%'
                """
            )
        )
        check(
            bool(queue_sequence_privileges),
            "Runtime database role can use Procrastinate sequences",
        )

        queue_function_privileges = await conn.scalar(
            text(
                """
                SELECT bool_and(
                    has_function_privilege(
                        current_user,
                        p.oid,
                        'EXECUTE'
                    )
                )
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.proname LIKE 'procrastinate_%'
                """
            )
        )
        check(
            bool(queue_function_privileges),
            "Runtime database role can execute Procrastinate functions",
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

        for table_name in ("product_import_jobs", "product_import_rows"):
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
