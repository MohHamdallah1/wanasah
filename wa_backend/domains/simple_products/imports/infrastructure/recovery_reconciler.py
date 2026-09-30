"""Durable Product Import business-job / queue-delivery reconciliation."""
from __future__ import annotations

from procrastinate.exceptions import AlreadyEnqueued


async def reconcile_orphaned_import_jobs(
    task,
    *,
    connection,
    stale_seconds: float,
    limit: int = 100,
) -> dict[str, int]:
    """Requeue stale active business jobs that lost their queue delivery.

    Candidate discovery is an indexed SECURITY DEFINER boundary installed by
    migration. It returns only company/job identifiers for active Product Import
    states with no TODO/DOING process delivery. The caller already owns the
    global Product Import recovery mutex.

    A job-scoped queueing_lock makes a concurrent legitimate producer win as a
    harmless dedupe rather than creating two deliveries. The company-scoped
    execution lock remains separate and continues to serialize same-tenant
    Product/Pricing execution.
    """
    if stale_seconds <= 0:
        raise ValueError("stale_seconds must be positive")
    if limit <= 0 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    stale_seconds_int = int(stale_seconds)
    if stale_seconds_int <= 0:
        raise ValueError("stale_seconds must resolve to at least one second")
    cursor = await connection.execute(
        """
        SELECT company_id, job_id
        FROM public.product_import_claim_orphaned_jobs(%s, %s)
        """,
        (stale_seconds_int, int(limit)),
    )
    candidates = list(await cursor.fetchall())

    requeued = 0
    deduplicated = 0
    for company_id, job_id in candidates:
        try:
            async with connection.transaction():
                await task.configure(
                    connection=connection,
                    lock=f"product-import:{int(company_id)}",
                    queueing_lock=f"product-import-job:{job_id}",
                ).defer_async(
                    company_id=int(company_id),
                    job_id=str(job_id),
                )
        except AlreadyEnqueued:
            deduplicated += 1
        else:
            requeued += 1

    return {
        "orphan_candidates": len(candidates),
        "orphan_requeued": requeued,
        "orphan_deduplicated": deduplicated,
    }
