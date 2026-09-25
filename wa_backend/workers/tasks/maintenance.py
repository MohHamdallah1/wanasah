# WORKER_PRODUCTION_HARDENING_V2
from __future__ import annotations

from procrastinate import builtin_tasks

from workers.app import (
    MAINTENANCE_QUEUE,
    STALLED_WORKER_TIMEOUT_SECONDS,
    app,
)


STALLED_RETRY_ALLOWLIST = {
    "wanasah.worker_healthcheck",
    "wanasah.scan_all_stale_handshakes",
    "wanasah.scan_company_stale_handshakes",
    "wanasah.scan_all_stale_sessions",
    "wanasah.scan_company_stale_sessions",
    "wanasah.scan_all_integrity",
    "wanasah.scan_company_integrity",
    "wanasah.report_foundation_probe",
    "wanasah.retry_safe_stalled_jobs",
    "wanasah.cleanup_old_worker_jobs",
    "wanasah.scan_all_live_stock_transitions",
    "wanasah.refresh_company_live_stock_transitions",
}


@app.periodic(cron="*/10 * * * *")
@app.task(
    name="wanasah.retry_safe_stalled_jobs",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="retry-safe-stalled-jobs",
    lock="retry-safe-stalled-jobs",
)
async def retry_safe_stalled_jobs(timestamp: int) -> dict[str, int]:
    stalled_jobs = await app.job_manager.get_stalled_jobs(
        seconds_since_heartbeat=STALLED_WORKER_TIMEOUT_SECONDS,
    )
    retried = 0
    skipped = 0

    for job in stalled_jobs:
        if job.task_name not in STALLED_RETRY_ALLOWLIST:
            skipped += 1
            continue
        await app.job_manager.retry_job(job)
        retried += 1

    return {
        "stalled_seen": len(stalled_jobs),
        "retried": retried,
        "skipped_not_allowlisted": skipped,
    }


@app.periodic(cron="13 4 * * *")
@app.task(
    name="wanasah.cleanup_old_worker_jobs",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="cleanup-old-worker-jobs",
    lock="cleanup-old-worker-jobs",
    pass_context=True,
)
async def cleanup_old_worker_jobs(context, timestamp: int):
    return await builtin_tasks.remove_old_jobs(
        context,
        max_hours=720,
        remove_failed=True,
        remove_cancelled=True,
        remove_aborted=True,
    )
