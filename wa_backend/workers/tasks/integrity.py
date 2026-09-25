# INTEGRITY_JOBS_V1
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, select

from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryMovement,
    InventoryTransferHeader,
    InventoryTransferLine,
    SystemAuditLog,
    WorkSession,
)
from workers.app import MAINTENANCE_QUEUE, app
from workers.events import emit_worker_event
from workers.scheduling import (
    defer_unique_company_job,
    iter_active_company_id_pages,
)
from workers.settings import load_integrity_monitor_settings
from workers.tenant import acquire_tenant_job_lock, tenant_session

MAX_SAMPLE_IDS = 25


@dataclass(frozen=True)
class IntegrityCategory:
    code: str
    count: int
    sample_ids: tuple[int, ...]
    description: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _count_and_sample(db, count_stmt, sample_stmt) -> tuple[int, tuple[int, ...]]:
    count = int((await db.execute(count_stmt)).scalar_one() or 0)
    if count <= 0:
        return 0, ()
    sample = tuple(
        int(value)
        for value in (
            await db.execute(sample_stmt.limit(MAX_SAMPLE_IDS))
        ).scalars().all()
    )
    return count, sample


async def _collect_integrity_categories(
    db,
    *,
    company_id: int,
) -> list[IntegrityCategory]:
    categories: list[IntegrityCategory] = []

    # 1) start_work_session always binds the committed active session to one route.
    route_exists = exists(
        select(1).where(
            DispatchRoute.company_id == int(company_id),
            DispatchRoute.work_session_id == WorkSession.id,
        )
    )
    base = (
        WorkSession.company_id == int(company_id),
        WorkSession.end_time.is_(None),
        ~route_exists,
    )
    count, sample = await _count_and_sample(
        db,
        select(func.count(WorkSession.id)).where(*base),
        select(WorkSession.id).where(*base).order_by(WorkSession.id.asc()),
    )
    if count:
        categories.append(
            IntegrityCategory(
                code="ACTIVE_SESSION_WITHOUT_ROUTE",
                count=count,
                sample_ids=sample,
                description="جلسة عمل نشطة غير مرتبطة بخط سير.",
            )
        )

    # 2) driver end endpoint explicitly refuses closing while HANDSHAKE is PENDING.
    ended_pending_join = (
        InventoryTransferHeader.company_id == WorkSession.company_id,
        InventoryTransferHeader.work_session_id == WorkSession.id,
    )
    ended_pending_filters = (
        InventoryTransferHeader.company_id == int(company_id),
        InventoryTransferHeader.workflow_type == "HANDSHAKE",
        InventoryTransferHeader.status == "PENDING",
        WorkSession.end_time.is_not(None),
    )
    count, sample = await _count_and_sample(
        db,
        select(func.count(InventoryTransferHeader.id))
        .join(WorkSession, and_(*ended_pending_join))
        .where(*ended_pending_filters),
        select(InventoryTransferHeader.id)
        .join(WorkSession, and_(*ended_pending_join))
        .where(*ended_pending_filters)
        .order_by(InventoryTransferHeader.id.asc()),
    )
    if count:
        categories.append(
            IntegrityCategory(
                code="PENDING_HANDSHAKE_ON_ENDED_SESSION",
                count=count,
                sample_ids=sample,
                description="مصافحة معلقة مرتبطة بجلسة منتهية.",
            )
        )

    # 3) Force-cancel path treats a HANDSHAKE without lines as inconsistent data.
    line_exists = exists(
        select(1).where(
            InventoryTransferLine.company_id == int(company_id),
            InventoryTransferLine.transfer_header_id == InventoryTransferHeader.id,
        )
    )
    pending_handshake_filters = (
        InventoryTransferHeader.company_id == int(company_id),
        InventoryTransferHeader.workflow_type == "HANDSHAKE",
        InventoryTransferHeader.status == "PENDING",
    )
    count, sample = await _count_and_sample(
        db,
        select(func.count(InventoryTransferHeader.id)).where(
            *pending_handshake_filters,
            ~line_exists,
        ),
        select(InventoryTransferHeader.id).where(
            *pending_handshake_filters,
            ~line_exists,
        ).order_by(InventoryTransferHeader.id.asc()),
    )
    if count:
        categories.append(
            IntegrityCategory(
                code="PENDING_HANDSHAKE_WITHOUT_LINES",
                count=count,
                sample_ids=sample,
                description="مصافحة معلقة بلا أسطر مخزون.",
            )
        )

    # 4) Dispatch creates RESERVATION/RESERVE HANDSHAKE_RESERVE for a PENDING handshake.
    reserve_exists = exists(
        select(1).where(
            InventoryMovement.company_id == int(company_id),
            InventoryMovement.transfer_header_id == InventoryTransferHeader.id,
            InventoryMovement.movement_kind == "RESERVATION",
            InventoryMovement.reservation_action == "RESERVE",
            InventoryMovement.reference_type == "HANDSHAKE_RESERVE",
        )
    )
    count, sample = await _count_and_sample(
        db,
        select(func.count(InventoryTransferHeader.id)).where(
            *pending_handshake_filters,
            ~reserve_exists,
        ),
        select(InventoryTransferHeader.id).where(
            *pending_handshake_filters,
            ~reserve_exists,
        ).order_by(InventoryTransferHeader.id.asc()),
    )
    if count:
        categories.append(
            IntegrityCategory(
                code="PENDING_HANDSHAKE_WITHOUT_RESERVE",
                count=count,
                sample_ids=sample,
                description="مصافحة معلقة بلا حركة حجز HANDSHAKE_RESERVE.",
            )
        )

    # 5) Posted HANDSHAKE must have its physical HANDSHAKE_POST movement.
    post_exists = exists(
        select(1).where(
            InventoryMovement.company_id == int(company_id),
            InventoryMovement.transfer_header_id == InventoryTransferHeader.id,
            InventoryMovement.movement_kind == "PHYSICAL",
            InventoryMovement.reference_type == "HANDSHAKE_POST",
        )
    )
    posted_filters = (
        InventoryTransferHeader.company_id == int(company_id),
        InventoryTransferHeader.workflow_type == "HANDSHAKE",
        InventoryTransferHeader.status == "POSTED",
        ~post_exists,
    )
    count, sample = await _count_and_sample(
        db,
        select(func.count(InventoryTransferHeader.id)).where(*posted_filters),
        select(InventoryTransferHeader.id)
        .where(*posted_filters)
        .order_by(InventoryTransferHeader.id.asc()),
    )
    if count:
        categories.append(
            IntegrityCategory(
                code="POSTED_HANDSHAKE_WITHOUT_PHYSICAL_POST",
                count=count,
                sample_ids=sample,
                description="مصافحة POSTED بلا حركة PHYSICAL/HANDSHAKE_POST.",
            )
        )

    # 6) Defensive verification of the InventoryBalance SSOT invariants.
    invalid_balance_filters = (
        InventoryBalance.company_id == int(company_id),
        (
            (InventoryBalance.on_hand_quantity < 0)
            | (InventoryBalance.reserved_quantity < 0)
            | (InventoryBalance.reserved_quantity > InventoryBalance.on_hand_quantity)
            | (
                (InventoryBalance.stock_status == "DAMAGED")
                & (InventoryBalance.reserved_quantity != 0)
            )
        ),
    )
    count, sample = await _count_and_sample(
        db,
        select(func.count(InventoryBalance.id)).where(*invalid_balance_filters),
        select(InventoryBalance.id)
        .where(*invalid_balance_filters)
        .order_by(InventoryBalance.id.asc()),
    )
    if count:
        categories.append(
            IntegrityCategory(
                code="INVALID_INVENTORY_BALANCE",
                count=count,
                sample_ids=sample,
                description="رصيد مخزون يخالف حدود InventoryBalance الأساسية.",
            )
        )

    return categories


@app.periodic(cron="7 * * * *")
@app.task(
    name="wanasah.scan_all_integrity",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="integrity-global-scan",
    lock="integrity-global-scan",
)
async def scan_all_integrity(timestamp: int | None = None) -> dict[str, int]:
    companies_seen = 0
    deferred = 0
    skipped_duplicate = 0

    async for company_ids in iter_active_company_id_pages():
        companies_seen += len(company_ids)
        for company_id in company_ids:
            accepted = await defer_unique_company_job(
                scan_company_integrity,
                lock_namespace="integrity-company",
                company_id=company_id,
            )
            if accepted:
                deferred += 1
            else:
                skipped_duplicate += 1

    return {
        "companies_seen": companies_seen,
        "company_jobs_deferred": deferred,
        "company_jobs_skipped_duplicate": skipped_duplicate,
    }


@app.task(
    name="wanasah.scan_company_integrity",
    queue=MAINTENANCE_QUEUE,
)
async def scan_company_integrity(company_id: int) -> dict[str, int]:
    now = _utc_now()

    async with tenant_session(company_id) as db:
        await acquire_tenant_job_lock(
            db,
            namespace="integrity-monitor",
            company_id=int(company_id),
        )
        settings = await load_integrity_monitor_settings(
            db,
            company_id=int(company_id),
        )
        categories = await _collect_integrity_categories(
            db,
            company_id=int(company_id),
        )

        if not categories:
            await db.rollback()
            return {
                "company_id": int(company_id),
                "categories": 0,
                "findings": 0,
                "new_alerts": 0,
            }

        repeat_cutoff = now - timedelta(hours=settings.repeat_hours)
        action_types = [f"INTEGRITY_{category.code}" for category in categories]
        recent_rows = (
            await db.execute(
                select(SystemAuditLog.action_type).where(
                    SystemAuditLog.company_id == int(company_id),
                    SystemAuditLog.action_type.in_(action_types),
                    SystemAuditLog.timestamp >= repeat_cutoff,
                )
            )
        ).scalars().all()
        recent = {str(value) for value in recent_rows}

        new_categories: list[IntegrityCategory] = []
        for category in categories:
            action_type = f"INTEGRITY_{category.code}"
            if action_type in recent:
                continue

            db.add(
                SystemAuditLog(
                    company_id=int(company_id),
                    admin_id=None,
                    target_id=f"Integrity:{category.code}",
                    action_type=action_type,
                    old_value=None,
                    new_value=json.dumps(
                        {
                            "count": category.count,
                            "sample_ids": list(category.sample_ids),
                            "description": category.description,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
            new_categories.append(category)

        if new_categories:
            total_new = sum(category.count for category in new_categories)
            await emit_worker_event(
                db,
                company_id=int(company_id),
                event="INTEGRITY_ALERT",
                message=(
                    f"🚨 فحص سلامة البيانات اكتشف {total_new} حالة "
                    f"ضمن {len(new_categories)} فئة تحتاج مراجعة."
                ),
                data={
                    "category_count": len(new_categories),
                    "finding_count": total_new,
                    "categories": [
                        category.code for category in new_categories
                    ],
                },
            )

        await db.commit()

        return {
            "company_id": int(company_id),
            "categories": len(categories),
            "findings": sum(category.count for category in categories),
            "new_alerts": len(new_categories),
        }
