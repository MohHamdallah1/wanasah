# WORKER_SCHEDULING_V1
from __future__ import annotations

from procrastinate.exceptions import AlreadyEnqueued

from workers.tenant import normalize_company_id


def _company_job_lock(namespace: str, company_id: int) -> tuple[int, str]:
    cid = normalize_company_id(company_id)
    clean_namespace = str(namespace or "").strip()
    if not clean_namespace or len(clean_namespace) > 80:
        raise ValueError("invalid company job lock namespace")
    return cid, f"{clean_namespace}:{cid}"


async def defer_unique_company_job(
    task,
    *,
    lock_namespace: str,
    company_id: int,
) -> bool:
    """Bound duplicate company jobs while preserving serialized execution."""
    cid, lock_name = _company_job_lock(lock_namespace, company_id)
    try:
        await task.configure(
            lock=lock_name,
            queueing_lock=lock_name,
        ).defer_async(company_id=cid)
    except AlreadyEnqueued:
        return False
    return True
