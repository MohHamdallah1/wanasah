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
from domains.simple_products.imports.infrastructure.runtime_monitor import (
    QUEUE_AGE_ALERT_SECONDS,
    STUCK_STAGE_ALERT_SECONDS,
    read_product_import_runtime_metrics,
)
from domains.simple_products.imports.infrastructure.table_health_monitor import (
    AUTOVACUUM_LAG_ALERT_SECONDS,
    DEAD_TUPLE_ALERT_PERCENT,
    TRANSACTION_AGE_ALERT,
    read_product_import_table_health,
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

    if (
        metrics.oldest_active_job_age_seconds
        >= int(
            STUCK_STAGE_ALERT_SECONDS
        )
    ):
        logger.warning(
            "PRODUCT_IMPORT_STUCK_STAGE "
            "company_id=%s oldest_active_age_seconds=%s",
            int(
                company_id
            ),
            metrics.oldest_active_job_age_seconds,
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
    runtime_metrics = (
        await read_product_import_runtime_metrics()
    )
    table_health = (
        await read_product_import_table_health()
    )

    max_dead_tuple_percent = 0.0
    for metric in table_health:
        max_dead_tuple_percent = max(
            max_dead_tuple_percent,
            metric.dead_tuple_percent,
        )
        logger.info(
            "PRODUCT_IMPORT_TABLE_HEALTH "
            "table=%s live=%s dead=%s dead_pct=%.2f "
            "table_bytes=%s index_bytes=%s total_bytes=%s "
            "transaction_age=%s autovacuum_lag_seconds=%s "
            "autoanalyze_lag_seconds=%s active_vacuum_seconds=%s "
            "autovacuum_count=%s autoanalyze_count=%s",
            metric.table_name,
            metric.live_tuples,
            metric.dead_tuples,
            metric.dead_tuple_percent,
            metric.table_bytes,
            metric.index_bytes,
            metric.total_bytes,
            metric.transaction_age,
            metric.autovacuum_lag_seconds,
            metric.autoanalyze_lag_seconds,
            metric.active_vacuum_seconds,
            metric.autovacuum_count,
            metric.autoanalyze_count,
        )

        if (
            metric.dead_tuple_percent
            >= DEAD_TUPLE_ALERT_PERCENT
            and metric.dead_tuples
            >= 1000
        ):
            logger.warning(
                "PRODUCT_IMPORT_TABLE_BLOAT_HIGH "
                "table=%s dead=%s dead_pct=%.2f total_bytes=%s",
                metric.table_name,
                metric.dead_tuples,
                metric.dead_tuple_percent,
                metric.total_bytes,
            )

        if (
            metric.autovacuum_lag_seconds
            >= AUTOVACUUM_LAG_ALERT_SECONDS
            and metric.dead_tuples
            >= 1000
        ):
            logger.warning(
                "PRODUCT_IMPORT_AUTOVACUUM_LAG "
                "table=%s lag_seconds=%s dead=%s dead_pct=%.2f",
                metric.table_name,
                metric.autovacuum_lag_seconds,
                metric.dead_tuples,
                metric.dead_tuple_percent,
            )

        if (
            metric.transaction_age
            >= TRANSACTION_AGE_ALERT
        ):
            logger.error(
                "PRODUCT_IMPORT_TRANSACTION_AGE_HIGH "
                "table=%s transaction_age=%s",
                metric.table_name,
                metric.transaction_age,
            )

    if (
        runtime_metrics.queued_jobs
        > 0
        and not runtime_metrics.ready
    ):
        logger.error(
            "PRODUCT_IMPORT_WORKER_UNAVAILABLE "
            "queued_jobs=%s oldest_queue_age_seconds=%s",
            runtime_metrics.queued_jobs,
            runtime_metrics.oldest_queue_age_seconds,
        )
    elif (
        runtime_metrics.queued_jobs
        > 0
        and runtime_metrics.available_worker_slots
        <= 0
    ):
        logger.warning(
            "PRODUCT_IMPORT_WORKER_AT_CAPACITY "
            "worker_slots=%s running_jobs=%s queued_jobs=%s",
            runtime_metrics.configured_worker_slots,
            runtime_metrics.running_jobs,
            runtime_metrics.queued_jobs,
        )

    if (
        runtime_metrics.oldest_queue_age_seconds
        >= int(
            QUEUE_AGE_ALERT_SECONDS
        )
    ):
        logger.warning(
            "PRODUCT_IMPORT_QUEUE_AGE_HIGH "
            "oldest_queue_age_seconds=%s queued_jobs=%s",
            runtime_metrics.oldest_queue_age_seconds,
            runtime_metrics.queued_jobs,
        )

    logger.info(
        "PRODUCT_IMPORT_WORKER_CAPACITY "
        "healthy_workers=%s worker_slots=%s available_slots=%s "
        "running_jobs=%s queued_jobs=%s oldest_queue_age_seconds=%s",
        runtime_metrics.healthy_worker_processes,
        runtime_metrics.configured_worker_slots,
        runtime_metrics.available_worker_slots,
        runtime_metrics.running_jobs,
        runtime_metrics.queued_jobs,
        runtime_metrics.oldest_queue_age_seconds,
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
        "healthy_worker_processes":
            runtime_metrics.healthy_worker_processes,
        "configured_worker_slots":
            runtime_metrics.configured_worker_slots,
        "available_worker_slots":
            runtime_metrics.available_worker_slots,
        "running_jobs":
            runtime_metrics.running_jobs,
        "queued_jobs":
            runtime_metrics.queued_jobs,
        "oldest_queue_age_seconds":
            runtime_metrics.oldest_queue_age_seconds,
        "health_tables":
            len(
                table_health
            ),
        "max_dead_tuple_percent":
            int(
                round(
                    max_dead_tuple_percent
                )
            ),
    }
