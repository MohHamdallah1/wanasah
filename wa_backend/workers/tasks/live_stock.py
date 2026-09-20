# LIVE_STOCK_PROJECTION_MAINTENANCE_V1
from __future__ import annotations

from sqlalchemy import select

from database import AsyncSessionLocal
from domains.live_stock_projection.service import (
    mark_live_stock_projection_degraded,
    reconcile_live_stock_company,
    refresh_due_live_stock_transitions,
)
from models import Company, InventoryLiveStockCompanySummary
from workers.app import MAINTENANCE_QUEUE, app
from workers.events import emit_worker_event
from workers.tenant import acquire_tenant_job_lock, tenant_session


COMPANY_SCAN_PAGE = 1000
TRANSITION_BATCH = 5000
MAX_BATCHES_PER_RUN = 20


@app.periodic(cron="2,17,32,47 * * * *")
@app.task(
    name="wanasah.scan_all_live_stock_transitions",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="live-stock-transition-global-scan",
    lock="live-stock-transition-global-scan",
)
async def scan_all_live_stock_transitions(
    timestamp: int | None = None,
) -> dict[str, int]:
    after_company_id = 0
    companies_seen = 0
    deferred = 0

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
                        .limit(COMPANY_SCAN_PAGE)
                    )
                ).scalars().all()
            ]
            if db.in_transaction():
                await db.rollback()

        if not company_ids:
            break

        for company_id in company_ids:
            await refresh_company_live_stock_transitions.configure(
                lock=f"live-stock-transition-company:{company_id}",
            ).defer_async(company_id=company_id)
            deferred += 1

        companies_seen += len(company_ids)
        after_company_id = company_ids[-1]
        if len(company_ids) < COMPANY_SCAN_PAGE:
            break

    return {
        "companies_seen": companies_seen,
        "company_jobs_deferred": deferred,
    }


async def run_company_live_stock_transition_maintenance(
    company_id: int,
) -> dict[str, int | bool]:
    refreshed = 0
    batches = 0

    try:
        while batches < MAX_BATCHES_PER_RUN:
            async with tenant_session(company_id) as db:
                await acquire_tenant_job_lock(
                    db,
                    namespace="live-stock-due-transition",
                    company_id=int(company_id),
                )
                count = await refresh_due_live_stock_transitions(
                    db,
                    company_id=int(company_id),
                    limit=TRANSITION_BATCH,
                )
                await db.commit()

            refreshed += count
            batches += 1
            if count < TRANSITION_BATCH:
                recovered = False
                async with tenant_session(company_id) as db:
                    state = await db.scalar(
                        select(
                            InventoryLiveStockCompanySummary.projection_state
                        ).where(
                            InventoryLiveStockCompanySummary.company_id
                            == int(company_id)
                        )
                    )
                    if state == "DEGRADED":
                        await reconcile_live_stock_company(
                            db,
                            company_id=int(company_id),
                            batch_size=TRANSITION_BATCH,
                        )
                        await db.commit()
                        recovered = True
                    else:
                        await db.rollback()

                return {
                    "company_id": int(company_id),
                    "refreshed_keys": refreshed,
                    "batches": batches,
                    "saturated": False,
                    "recovered": recovered,
                }

        return {
            "company_id": int(company_id),
            "refreshed_keys": refreshed,
            "batches": batches,
            "saturated": True,
            "recovered": False,
        }
    except Exception:
        # Fail closed first. Persist DEGRADED independently from notification
        # delivery so an event failure can never roll the safety state back.
        try:
            async with tenant_session(company_id) as db:
                await mark_live_stock_projection_degraded(
                    db,
                    company_id=int(company_id),
                )
                await db.commit()
        except Exception:
            pass

        # Notification is best-effort and deliberately isolated from the
        # persisted DEGRADED state.
        try:
            async with tenant_session(company_id) as db:
                await emit_worker_event(
                    db,
                    company_id=int(company_id),
                    event="LIVE_STOCK_PROJECTION_DEGRADED",
                    message=(
                        "تعذر تحديث انتقالات المخزون الحي الزمنية؛ "
                        "تم إيقاف الاعتماد على الإسقاط حتى الإصلاح."
                    ),
                    data={"reason": "DUE_TRANSITION_REFRESH_FAILED"},
                )
                await db.commit()
        except Exception:
            pass
        raise


@app.task(
    name="wanasah.refresh_company_live_stock_transitions",
    queue=MAINTENANCE_QUEUE,
)
async def refresh_company_live_stock_transitions(
    company_id: int,
) -> dict[str, int | bool]:
    return await run_company_live_stock_transition_maintenance(
        company_id=int(company_id),
    )
