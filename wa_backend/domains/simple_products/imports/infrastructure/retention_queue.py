"""Background scheduling for Product Import retention cleanup."""
from __future__ import annotations

from procrastinate import RetryStrategy

from domains.simple_products.imports.application.retention_service import (
    run_product_import_retention,
)
from domains.simple_products.imports.infrastructure.postgres_source_store import (
    POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
)
from domains.simple_products.imports.infrastructure.queue import (
    app,
)
from domains.simple_products.imports.infrastructure.queue_topology import MAINTENANCE_QUEUE
from domains.simple_products.imports.infrastructure.scheduled_work import defer_due_candidates, reconcile_candidate


_RETENTION_LOCK_PREFIX = (
    "product-import-retention:"
)


@app.task(
    name="wanasah.cleanup_product_import_retention",
    queue=MAINTENANCE_QUEUE,
    retry=RetryStrategy(
        max_attempts=3,
        wait=10,
        exponential_wait=2,
    ),
)
async def cleanup_product_import_retention(
    company_id: int,
) -> dict[str, int | bool]:
    result = await run_product_import_retention(
        company_id=int(
            company_id
        ),
        source_store=
            POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
    )
    await reconcile_candidate(int(company_id), kind="retention")
    return result


@app.periodic(
    cron="17 * * * *"
)
@app.task(
    name="wanasah.schedule_product_import_retention",
    queue=MAINTENANCE_QUEUE,
    queueing_lock=
        "product-import-retention-scheduler",
    lock=
        "product-import-retention-scheduler",
)
async def schedule_product_import_retention(
    timestamp: int | None = None,
) -> dict[str, int]:
    return await defer_due_candidates(
        cleanup_product_import_retention, kind="retention", lock_prefix=_RETENTION_LOCK_PREFIX,
    )
