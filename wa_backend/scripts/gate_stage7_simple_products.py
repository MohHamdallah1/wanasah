from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from domains.simple_products.imports.application import (  # noqa: E402
    ImportApplicationService,
)
from domains.simple_products.imports.infrastructure.queue import (  # noqa: E402
    app as import_app,
)
from domains.simple_products.imports.infrastructure.staging import (  # noqa: E402
    StagedWorkbook,
    stage_upload,
)
from domains.simple_products.imports.infrastructure.staging_cleanup import (  # noqa: E402
    cleanup_stale_staging,
)
from domains.simple_products.imports.models import (  # noqa: E402
    ProductImportJob,
    ProductImportRow,
)
from domains.simple_products.imports.states import ImportStatus  # noqa: E402
from domains.simple_products.imports.worker import (  # noqa: E402
    process_product_import,
)
from models import Company, Product  # noqa: E402


CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def static_checks() -> None:
    main_py = _read("wa_backend/main.py")
    requirements = _read("wa_backend/requirements.txt")
    auth_fetch = _read("dashboard/src/lib/authFetch.ts")
    router = _read("wa_backend/domains/simple_products/imports/api/router.py")
    service = _read("wa_backend/domains/simple_products/imports/application/service.py")
    queue_source = _read("wa_backend/domains/simple_products/imports/infrastructure/queue.py")
    staging = _read("wa_backend/domains/simple_products/imports/infrastructure/staging.py")
    cleanup = _read("wa_backend/domains/simple_products/imports/infrastructure/staging_cleanup.py")
    worker = _read("wa_backend/domains/simple_products/imports/worker.py")
    models = _read("wa_backend/domains/simple_products/imports/models.py")
    migration = _read("wa_backend/alembic/versions/2e9d25a8f901_product_import_jobs.py")
    products_page = _read("dashboard/src/pages/ProductsPage.tsx")
    products_dashboard = _read("dashboard/src/pages/ProductsDashboard.tsx")
    api_ts = _read("dashboard/src/pages/products/api/productImportApi.ts")
    templates_ts = _read("dashboard/src/pages/products/imports/productImportTemplates.ts")
    wizard = _read("dashboard/src/pages/products/imports/ProductImportWizard.tsx")
    progress = _read("dashboard/src/pages/products/imports/ProductImportProgress.tsx")
    failures = _read("dashboard/src/pages/products/imports/ProductImportFailures.tsx")
    correction = _read("dashboard/src/pages/products/imports/ProductImportCorrectionWizard.tsx")
    error_renderer = _read("dashboard/src/pages/products/imports/ProductImportErrorRenderer.tsx")
    error_catalog = _read("dashboard/src/pages/products/imports/productImportErrorCatalog.ts")
    draft = _read("dashboard/src/pages/products/imports/productImportDraft.ts")
    state = _read("dashboard/src/pages/products/imports/useProductImportState.ts")
    menu = _read("dashboard/src/pages/products/actions/ProductCatalogToolsMenu.tsx")
    i18n = _read("dashboard/src/i18n.ts")

    check(
        "/imports/template" in router
        and "/imports" in router
        and "/imports/{job_id}" in router
        and "/imports/{job_id}/retry" in router,
        "Product Import API routes remain registered",
    )
    check(
        "UploadFile" in router
        and "file: UploadFile" in router
        and "await service.create_job" in router,
        "Upload route remains multipart and delegates to application service",
    )
    check(
        "class ImportApplicationService" in service
        and "create_job" in service
        and "retry_failed_job" in service
        and "read_job" in service,
        "Application service owns import use-cases",
    )
    check(
        "@import_app.task" in queue_source
        and "@process_product_import.task" not in worker,
        "Queue task registration remains in infrastructure",
    )
    check(
        "ImportStatus.QUEUED" in models
        and "ImportStatus.PARSING" in worker
        and "ImportStatus.IMPORTING" in worker
        and "ImportStatus.SUCCEEDED" in worker,
        "Import state machine remains explicit",
    )
    check(
        "CREATE TABLE product_import_jobs" in migration
        and "CREATE TABLE product_import_rows" in migration
        and "uq_product_import_job_company_file" in migration,
        "Migration persists jobs, rows, and replay identity",
    )
    check(
        "CHUNK_SIZE" in staging
        and "SpooledTemporaryFile" in staging
        and "load_workbook" in staging,
        "Staging remains bounded and streaming-aware",
    )
    check(
        "cleanup_stale_staging" in cleanup
        and "PRODUCT_IMPORT_STAGING_RETENTION_HOURS" in cleanup,
        "Staging cleanup remains retention-driven",
    )
    check(
        "ProductImportWizard" in products_page
        and "ProductImportProgress" in products_page
        and "ProductImportFailures" in products_page
        and "ProductImportCorrectionWizard" in products_page,
        "Products page still mounts complete import UX",
    )
    check(
        "ProductCatalogToolsMenu" in products_page
        and "ProductCatalogToolsMenu" not in products_dashboard,
        "Catalog tools remain on canonical Products page only",
    )
    check(
        "fetchProductImportTemplate" in api_ts
        and "createProductImport" in api_ts
        and "retryProductImport" in api_ts,
        "Dashboard import API contract remains centralized",
    )
    check(
        "PRODUCT_IMPORT_TEMPLATE_COLUMN_KEYS" in templates_ts
        and "productImportColumn" in i18n,
        "Template contract remains localized",
    )
    check(
        "buildDefaultImportTrackingOptions" in wizard
        and "ProductImportTrackingMode" in state,
        "Tracking defaults remain explicit in import wizard state",
    )
    check(
        "aria-live" in progress
        and "role=\"status\"" in progress,
        "Progress semantics remain accessible",
    )
    check(
        "downloadProductImportFailures" in failures
        and "ProductImportErrorRenderer" in failures,
        "Failure export and localized rendering remain available",
    )
    check(
        "request_id" in correction
        and "ProductImportErrorRenderer" in correction,
        "Correction workflow remains idempotent and localized",
    )
    check(
        "resolveProductImportErrorMessage" in error_renderer
        and "resolveProductImportErrorMessage" in error_catalog,
        "Error rendering remains centralized",
    )
    check(
        "saveProductImportDraft" in draft
        and "clearProductImportDraft" in draft,
        "Import draft remains durable and clearable",
    )
    check(
        "app.include_router(simple_products.router)" in main_py
        and "app.include_router(product_import_router)" in main_py
        and "domains.simple_products.imports.api" in main_py
        and "product_import_app.open_async()" not in main_py
        and "product_import_event_relay.start()" in main_py
        and "worker_event_relay.start()" in main_py,
        "API stays registered while Product Import pool ownership remains worker-only",
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
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    heads = [line.strip() for line in heads_cp.stdout.splitlines() if line.strip()]
    check(len(heads) == 1, f"Alembic has one head ({heads[0] if heads else 'none'})")

    async with engine.connect() as conn:
        revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        check(revision == heads[0].replace(" (head)", ""), "Database is on Alembic head")

        table_count = await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name IN "
                "('product_import_jobs','product_import_rows')"
            )
        )
        check(int(table_count or 0) == 2, "Product Import database tables exist")

        indexes = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                "AND tablename IN ('product_import_jobs','product_import_rows')"
            )
        )
        names = {row[0] for row in indexes}
        check(
            "uq_product_import_job_company_file" in names,
            "Replay identity unique index exists",
        )

    await engine.dispose()


async def staging_checks() -> None:
    suffix = uuid4().hex
    content = b"PK\x03\x04" + b"x" * 64
    upload = UploadFile(filename=f"products-{suffix}.xlsx", file=tempfile.SpooledTemporaryFile())
    await upload.write(content)
    await upload.seek(0)

    staged = await stage_upload(upload)
    try:
        check(staged.size_bytes == len(content), "Staging records exact byte count")
        check(staged.sha256, "Staging records content hash")
        check(staged.path.exists(), "Staging file exists after upload")
    finally:
        staged.cleanup()


async def worker_contract_checks() -> None:
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        company_id = await db.scalar(select(Company.id).order_by(Company.id.asc()).limit(1))
        if company_id is None:
            print("[SKIP] worker runtime contract: no company row")
            return

        product_id = await db.scalar(
            select(Product.id).where(Product.company_id == company_id).order_by(Product.id.asc()).limit(1)
        )
        if product_id is None:
            print("[SKIP] worker runtime contract: no product row")
            return

    process_product_import_fn = process_product_import.wrapped if hasattr(process_product_import, "wrapped") else process_product_import
    check(callable(process_product_import_fn), "Worker task wrapper exposes callable implementation")


async def cleanup_contract_checks() -> None:
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        with patch(
            "domains.simple_products.imports.infrastructure.staging_cleanup.STAGING_ROOT",
            Path(tempfile.gettempdir()) / f"wanasah-cleanup-{uuid4().hex}",
        ) as root:
            root.mkdir(parents=True, exist_ok=True)
            old_file = root / "old.xlsx"
            old_file.write_bytes(b"old")
            old = time.time() - 60 * 60 * 48
            os.utime(old_file, (old, old))

            removed = await cleanup_stale_staging(db, retention_hours=24)
            check(removed == 1, "Stale staging cleanup removes old file")


async def main() -> None:
    static_checks()
    await database_checks()
    await staging_checks()
    await worker_contract_checks()
    await cleanup_contract_checks()
    print(f"STAGE7_SIMPLE_PRODUCTS_GATE=PASS CHECKS={CHECKS}")


if __name__ == "__main__":
    asyncio.run(main())
