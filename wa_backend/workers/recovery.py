# WORKER_RECOVERY_V1
from __future__ import annotations

from procrastinate import jobs


async def recover_safe_stalled_jobs(
    app,
    *,
    allowlist: set[str] | frozenset[str],
    seconds_since_heartbeat: float,
) -> dict[str, int]:
    if seconds_since_heartbeat <= 0:
        raise ValueError("seconds_since_heartbeat must be positive")

    pruned_workers = await app.job_manager.prune_stalled_workers(
        seconds_since_heartbeat
    )
    stalled_jobs = list(
        await app.job_manager.get_stalled_jobs(
            seconds_since_heartbeat=seconds_since_heartbeat,
        )
    )

    retried = 0
    superseded = 0
    skipped = 0
    skipped_lock_conflict = 0

    for job in stalled_jobs:
        if job.task_name not in allowlist:
            skipped += 1
            continue

        if job.queueing_lock:
            waiting = list(
                await app.job_manager.list_jobs_async(
                    status="todo",
                    queueing_lock=job.queueing_lock,
                )
            )
            if waiting:
                if any(item.task_name != job.task_name for item in waiting):
                    skipped_lock_conflict += 1
                    continue
                await app.job_manager.finish_job_by_id_async(
                    job_id=int(job.id),
                    status=jobs.Status.FAILED,
                    delete_job=False,
                )
                superseded += 1
                continue

        await app.job_manager.retry_job(job)
        retried += 1

    return {
        "pruned_workers": len(pruned_workers),
        "stalled_seen": len(stalled_jobs),
        "retried": retried,
        "superseded_by_queued": superseded,
        "skipped_not_allowlisted": skipped,
        "skipped_lock_conflict": skipped_lock_conflict,
    }
