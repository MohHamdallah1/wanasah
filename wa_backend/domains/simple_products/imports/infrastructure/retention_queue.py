"""Background scheduling for Product Import retention cleanup."""
from __future__ import annotations

from procrastinate import RetryStrategy

from domains.simple_products.imports.application.retention_service import (
    iter_retention_company_id_pages,
    run_product_import_retention,
)
from domains.simple_products.imports.infrastructure.queue import (
    app,
)


_RETENTION_LOCK_PREFIX = (
    "product-import-retention:"
)


@app.task(
    name="wanasah.cleanup_product_import_retention",
    queue="product-import",
    retry=RetryStrategy(
        max_attempts=3,
        wait=10,
        exponential_wait=2,
    ),
)
async def cleanup_product_import_retention(
    company_id: int,
) -> dict[str, int | bool]:
    return await run_product_import_retention(
        company_id=int(
            company_id
        )
    )


async def _defer_retention_page(
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
                _RETENTION_LOCK_PREFIX
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

        await cleanup_product_import_retention.configure(
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
    cron="17 * * * *"
)
@app.task(
    name="wanasah.schedule_product_import_retention",
    queue="product-import",
    queueing_lock=
        "product-import-retention-scheduler",
    lock=
        "product-import-retention-scheduler",
)
async def schedule_product_import_retention(
    timestamp: int | None = None,
) -> dict[str, int]:
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
        ) = await _defer_retention_page(
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
    }
