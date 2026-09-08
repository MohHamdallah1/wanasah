# STALE_HANDSHAKE_MONITOR_V2
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select

from database import AsyncSessionLocal
from models import Company, Driver, InventoryTransferHeader, SystemAuditLog
from workers.app import MAINTENANCE_QUEUE, app
from workers.events import emit_worker_events
from workers.settings import load_handshake_monitor_settings
from workers.tenant import acquire_tenant_job_lock, tenant_session

WARNING_AUDIT = "STALE_HANDSHAKE_WARNING"
CRITICAL_AUDIT = "STALE_HANDSHAKE_CRITICAL"

# AUTO_CANCEL remains settings-only. Execution is deliberately NOT implemented.
# Flutter/offline transfer-expiry semantics must be explicitly approved first.


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.periodic(cron="*/5 * * * *")
@app.task(
    name="wanasah.scan_all_stale_handshakes",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="stale-handshake-global-scan",
    lock="stale-handshake-global-scan",
)
async def scan_all_stale_handshakes(
    timestamp: int | None = None,
) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        company_ids = list(
            (
                await db.execute(
                    select(Company.id).order_by(Company.id.asc())
                )
            ).scalars().all()
        )
        if db.in_transaction():
            await db.rollback()

    deferred = 0
    for company_id in company_ids:
        await scan_company_stale_handshakes.configure(
            lock=f"stale-handshake-company:{int(company_id)}",
        ).defer_async(company_id=int(company_id))
        deferred += 1

    return {
        "companies_seen": len(company_ids),
        "company_jobs_deferred": deferred,
    }


@app.task(
    name="wanasah.scan_company_stale_handshakes",
    queue=MAINTENANCE_QUEUE,
)
async def scan_company_stale_handshakes(
    company_id: int,
) -> dict[str, int | str]:
    now = _utc_now()

    async with tenant_session(company_id) as db:
        await acquire_tenant_job_lock(
            db,
            namespace="stale-handshake-monitor",
            company_id=int(company_id),
        )
        settings = await load_handshake_monitor_settings(
            db,
            company_id=int(company_id),
        )
        warning_cutoff = now - timedelta(hours=settings.warning_hours)
        critical_cutoff = now - timedelta(hours=settings.critical_hours)

        target_expr = func.concat(
            "Transfer_",
            InventoryTransferHeader.id,
        )
        warning_audit_exists = exists(
            select(1).where(
                SystemAuditLog.company_id == int(company_id),
                SystemAuditLog.target_id == target_expr,
                SystemAuditLog.action_type == WARNING_AUDIT,
            )
        )
        critical_audit_exists = exists(
            select(1).where(
                SystemAuditLog.company_id == int(company_id),
                SystemAuditLog.target_id == target_expr,
                SystemAuditLog.action_type == CRITICAL_AUDIT,
            )
        )

        # Limit remains a safety bound, but SQL excludes records whose currently
        # required alert already exists. Previously-alerted oldest rows therefore
        # cannot starve newer stale rows.
        headers = (
            await db.execute(
                select(InventoryTransferHeader)
                .where(
                    InventoryTransferHeader.company_id == int(company_id),
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                    InventoryTransferHeader.status == "PENDING",
                    InventoryTransferHeader.created_at <= warning_cutoff,
                    or_(
                        and_(
                            InventoryTransferHeader.created_at
                            <= critical_cutoff,
                            ~critical_audit_exists,
                        ),
                        and_(
                            InventoryTransferHeader.created_at
                            > critical_cutoff,
                            ~warning_audit_exists,
                        ),
                    ),
                )
                .order_by(
                    InventoryTransferHeader.created_at.asc(),
                    InventoryTransferHeader.id.asc(),
                )
                .limit(1000)
            )
        ).scalars().all()

        if not headers:
            await db.rollback()
            return {
                "company_id": int(company_id),
                "pending_stale": 0,
                "warnings_created": 0,
                "critical_created": 0,
                "timeout_action": settings.timeout_action,
            }

        receiver_ids = sorted(
            {
                int(header.expected_receiver_id)
                for header in headers
                if header.expected_receiver_id is not None
            }
        )
        receiver_map: dict[int, str] = {}
        if receiver_ids:
            receiver_rows = (
                await db.execute(
                    select(Driver.id, Driver.full_name).where(
                        Driver.company_id == int(company_id),
                        Driver.id.in_(receiver_ids),
                    )
                )
            ).all()
            receiver_map = {
                int(driver_id): str(full_name)
                for driver_id, full_name in receiver_rows
            }

        warnings_created = 0
        critical_created = 0
        events_to_emit: list[dict] = []

        for header in headers:
            created_at = header.created_at
            if created_at is None:
                continue

            age_hours = max(
                0.0,
                (now - created_at).total_seconds() / 3600.0,
            )
            target_id = f"Transfer_{int(header.id)}"
            receiver_name = receiver_map.get(
                int(header.expected_receiver_id)
                if header.expected_receiver_id is not None
                else -1,
                "مندوب غير معروف",
            )

            if age_hours >= settings.critical_hours:
                action_type = CRITICAL_AUDIT
                event = "STALE_HANDSHAKE_CRITICAL"
                message = (
                    f"🚨 الحوالة {header.reference_number} معلقة مع "
                    f"{receiver_name} لأكثر من "
                    f"{settings.critical_hours} ساعات."
                )
                critical_created += 1
            else:
                action_type = WARNING_AUDIT
                event = "STALE_HANDSHAKE_WARNING"
                message = (
                    f"⚠️ الحوالة {header.reference_number} معلقة مع "
                    f"{receiver_name} لأكثر من "
                    f"{settings.warning_hours} ساعات."
                )
                warnings_created += 1

            db.add(
                SystemAuditLog(
                    company_id=int(company_id),
                    admin_id=None,
                    target_id=target_id,
                    action_type=action_type,
                    old_value="status=PENDING",
                    new_value=(
                        f"age_hours={age_hours:.2f}|"
                        f"warning={settings.warning_hours}|"
                        f"critical={settings.critical_hours}|"
                        f"auto_cancel={settings.auto_cancel_hours}|"
                        f"timeout_action={settings.timeout_action}"
                    ),
                )
            )

            events_to_emit.append(
                {
                    "company_id": int(company_id),
                    "event": event,
                    "message": message,
                    "data": {
                        "transfer_id": int(header.id),
                        "reference_number": str(header.reference_number),
                        "expected_receiver_id": (
                            int(header.expected_receiver_id)
                            if header.expected_receiver_id is not None
                            else None
                        ),
                        "age_hours": round(age_hours, 2),
                    },
                }
            )

        await emit_worker_events(db, events=events_to_emit)
        await db.commit()

        return {
            "company_id": int(company_id),
            "pending_stale": len(headers),
            "warnings_created": warnings_created,
            "critical_created": critical_created,
            "timeout_action": settings.timeout_action,
        }
