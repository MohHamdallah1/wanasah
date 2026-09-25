# WORKER_SCHEDULING_V1
from __future__ import annotations

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Company
from workers.app import app
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


async def defer_unique_company_jobs(
    task,
    *,
    lock_namespace: str,
    company_ids: list[int],
) -> tuple[int, int]:
    """Defer only companies with no TODO/DOING job for this lock namespace.

    The periodic parent task is globally locked, so one bounded queue lookup per
    company page is sufficient. Child jobs keep the execution lock only; this
    preserves safe stalled-job retry without a queueing-lock collision.
    """
    locks: list[tuple[int, str]] = []
    seen: set[int] = set()
    for raw_company_id in company_ids:
        cid, lock_name = _company_job_lock(lock_namespace, raw_company_id)
        if cid in seen:
            raise ValueError("company_ids contains duplicates")
        seen.add(cid)
        locks.append((cid, lock_name))

    if not locks:
        return 0, 0

    active_rows = await app.connector.execute_query_all_async(
        query=(
            "SELECT lock FROM procrastinate_jobs "
            "WHERE lock = ANY(%(locks)s::text[]) "
            "AND status = ANY(%(statuses)s::procrastinate_job_status[])"
        ),
        locks=[lock_name for _, lock_name in locks],
        statuses=["todo", "doing"],
    )
    active_locks = {str(row["lock"]) for row in active_rows}

    deferred = 0
    skipped = 0
    for cid, lock_name in locks:
        if lock_name in active_locks:
            skipped += 1
            continue
        await task.configure(lock=lock_name).defer_async(company_id=cid)
        deferred += 1

    return deferred, skipped
