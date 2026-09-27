"""Periodic Product Import source-capacity metrics and alerts."""
from __future__ import annotations

import logging

from domains.simple_products.imports.application.retention_service import (
    iter_retention_company_id_pages,
)
from domains.simple_products.imports.domain.admission import (
    DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY,
)
from domains.simple_products.imports.infrastructure.capacity_monitor import (
    read_global_source_capacity_metrics,
    read_tenant_source_capacity_metrics,
)
from domains.simple_products.imports.infrastructure.queue import (
    app,
)


logger = logging.getLogger(
    __name__
)
_CAPACITY_LOCK_PREFIX = (
    "product-import-capacity:"
)


@app.task(
    name="wanasah.monitor_product_import_capacity",
    queue="product-import",
)
async def monitor_product_import_capacity(
    company_id: int,
) -> dict[str, int]:
    policy = (
        DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY
    )
    metrics = (
        await read_tenant_source_capacity_metrics(
            company_id=int(
                company_id
            )
        )
    )
    payload = metrics.as_dict()

    tenant_alert_bytes = (
        int(
            policy.max_live_source_bytes_per_tenant
        )
        * int(
            policy.storage_alert_percent
        )
        // 100
    )
    if (
        metrics.live_source_bytes
        >= tenant_alert_bytes
    ):
        logger.warning(
            "PRODUCT_IMPORT_TENANT_SOURCE_STORAGE_HIGH "
            "company_id=%s live_bytes=%s limit=%s",
            int(
                company_id
            ),
            metrics.live_source_bytes,
            policy.max_live_source_bytes_per_tenant,
        )

    if (
        metrics.oldest_live_source_age_seconds
        >= int(
            policy.oldest_source_alert_seconds
        )
    ):
        logger.warning(
            "PRODUCT_IMPORT_SOURCE_AGE_HIGH "
            "company_id=%s oldest_age_seconds=%s",
            int(
                company_id
            ),
            metrics.oldest_live_source_age_seconds,
        )

    if (
        metrics.quota_rejections_last_hour
        > 0
    ):
        logger.warning(
            "PRODUCT_IMPORT_ADMISSION_REJECTIONS "
            "company_id=%s last_hour=%s",
            int(
                company_id
            ),
            metrics.quota_rejections_last_hour,
        )

    return payload


async def _defer_capacity_page(
    company_ids: list[int],
) -> tuple[int, int]:
    if not company_ids:
        return (
            0,
            0,
        )

    locks = [
        (
            int(
                company_id
            ),
            (
                _CAPACITY_LOCK_PREFIX
                + str(
                    int(
                        company_id
                    )
                )
            ),
        )
        for company_id in company_ids
    ]
    active_rows = (
        await app.connector.execute_query_all_async(
            query=(
                "SELECT lock "
                "FROM procrastinate_jobs "
                "WHERE lock = ANY(%(locks)s::text[]) "
                "AND status = ANY("
                "%(statuses)s::procrastinate_job_status[]"
                ")"
            ),
            locks=[
                lock
                for _company_id, lock
                in locks
            ],
            statuses=[
                "todo",
                "doing",
            ],
        )
    )
    active_locks = {
        str(
            row[
                "lock"
            ]
        )
        for row in active_rows
    }

    deferred = 0
    skipped = 0
    for (
        company_id,
        lock,
    ) in locks:
        if lock in active_locks:
            skipped += 1
            continue

        await monitor_product_import_capacity.configure(
            lock=lock
        ).defer_async(
            company_id=
                company_id
        )
        deferred += 1

    return (
        deferred,
        skipped,
    )


@app.periodic(
    cron="*/5 * * * *"
)
@app.task(
    name="wanasah.schedule_product_import_capacity_monitor",
    queue="product-import",
    queueing_lock=
        "product-import-capacity-scheduler",
    lock=
        "product-import-capacity-scheduler",
)
async def schedule_product_import_capacity_monitor(
    timestamp: int | None = None,
) -> dict[str, int]:
    policy = (
        DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY
    )
    global_metrics = (
        await read_global_source_capacity_metrics()
    )

    global_alert_bytes = (
        int(
            policy.global_live_source_bytes
        )
        * int(
            policy.storage_alert_percent
        )
        // 100
    )
    if (
        int(
            global_metrics[
                "live_source_bytes"
            ]
        )
        >= global_alert_bytes
    ):
        logger.warning(
            "PRODUCT_IMPORT_GLOBAL_SOURCE_STORAGE_HIGH "
            "live_bytes=%s high_water_bytes=%s limit=%s",
            global_metrics[
                "live_source_bytes"
            ],
            global_metrics[
                "high_water_source_bytes"
            ],
            policy.global_live_source_bytes,
        )

    deferred = 0
    skipped = 0
    companies_seen = 0
    async for company_ids in (
        iter_retention_company_id_pages()
    ):
        companies_seen += len(
            company_ids
        )
        (
            page_deferred,
            page_skipped,
        ) = await _defer_capacity_page(
            company_ids
        )
        deferred += (
            page_deferred
        )
        skipped += (
            page_skipped
        )

    return {
        "companies_seen":
            companies_seen,
        "deferred":
            deferred,
        "skipped_active":
            skipped,
        "global_live_source_bytes":
            int(
                global_metrics[
                    "live_source_bytes"
                ]
            ),
        "global_high_water_source_bytes":
            int(
                global_metrics[
                    "high_water_source_bytes"
                ]
            ),
    }
