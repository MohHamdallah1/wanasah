# WORKER_SCHEDULING_V1
from __future__ import annotations

from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import select

from database import AsyncSessionLocal
from models import Company
from workers.tenant import normalize_company_id


COMPANY_SCAN_PAGE = 1000


async def iter_active_company_id_pages(
    *,
    page_size: int = COMPANY_SCAN_PAGE,
):
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        raise ValueError("page_size must be an integer.")
    if page_size <= 0 or page_size > 5000:
        raise ValueError("page_size must be between 1 and 5000.")

    after_company_id = 0
    while True:
        async with AsyncSessionLocal() as db:
            company_ids = [
                int(value)
                for value in (
                    await db.execute(
                        select(Company.id)
                        .where(
                            Company.id > after_company_id,
                            Company.is_active.is_(True),
                        )
                        .order_by(Company.id.asc())
                        .limit(page_size)
                    )
                ).scalars().all()
            ]
            if db.in_transaction():
                await db.rollback()

        if not company_ids:
            break
        yield company_ids
        after_company_id = company_ids[-1]
        if len(company_ids) < page_size:
            break


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
