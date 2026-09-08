# STALE_HANDSHAKE_MONITOR_V1
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Company, Driver, InventoryTransferHeader, SystemAuditLog
from workers.app import MAINTENANCE_QUEUE, app
from workers.events import emit_worker_event
from workers.settings import load_handshake_monitor_settings
from workers.tenant import tenant_session

WARNING_AUDIT = "STALE_HANDSHAKE_WARNING"
CRITICAL_AUDIT = "STALE_HANDSHAKE_CRITICAL"

# AUTO_CANCEL is part of the settings contract but is deliberately not
# executed in V1. Flutter/offline transfer-expiry semantics must be frozen
# first so the server never cancels a transfer already accepted offline.


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.task(
    name="wanasah.scan_all_stale_handshakes",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="stale-handshake-global-scan",
    lock="stale-handshake-global-scan",
)
async def scan_all_stale_handshakes() -> dict[str, int]:
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
        settings = await load_handshake_monitor_settings(
            db,
            company_id=int(company_id),
        )
        warning_cutoff = now - timedelta(hours=settings.warning_hours)

        headers = (
            await db.execute(
                select(InventoryTransferHeader)
                .filter(
                    InventoryTransferHeader.company_id == int(company_id),
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                    InventoryTransferHeader.status == "PENDING",
                    InventoryTransferHeader.created_at <= warning_cutoff,
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
                    select(Driver.id, Driver.full_name).filter(
                        Driver.company_id == int(company_id),
                        Driver.id.in_(receiver_ids),
                    )
                )
            ).all()
            receiver_map = {
                int(driver_id): str(full_name)
                for driver_id, full_name in receiver_rows
            }

        target_ids = [f"Transfer_{int(header.id)}" for header in headers]
        prior_rows = (
            await db.execute(
                select(
                    SystemAuditLog.target_id,
                    SystemAuditLog.action_type,
                ).filter(
                    SystemAuditLog.company_id == int(company_id),
                    SystemAuditLog.target_id.in_(target_ids),
                    SystemAuditLog.action_type.in_(
                        [WARNING_AUDIT, CRITICAL_AUDIT]
                    ),
                )
            )
        ).all()
        prior = {
            (str(target_id), str(action_type))
            for target_id, action_type in prior_rows
        }

        warnings_created = 0
        critical_created = 0

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
                if (target_id, action_type) in prior:
                    continue
                message = (
                    f"🚨 الحوالة {header.reference_number} معلقة مع "
                    f"{receiver_name} لأكثر من "
                    f"{settings.critical_hours} ساعات."
                )
                critical_created += 1
            else:
                action_type = WARNING_AUDIT
                event = "STALE_HANDSHAKE_WARNING"
                if (target_id, action_type) in prior:
                    continue
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

            await emit_worker_event(
                db,
                company_id=int(company_id),
                event=event,
                message=message,
                data={
                    "transfer_id": int(header.id),
                    "reference_number": str(header.reference_number),
                    "expected_receiver_id": (
                        int(header.expected_receiver_id)
                        if header.expected_receiver_id is not None
                        else None
                    ),
                    "age_hours": round(age_hours, 2),
                },
            )
            prior.add((target_id, action_type))

        await db.commit()

        return {
            "company_id": int(company_id),
            "pending_stale": len(headers),
            "warnings_created": warnings_created,
            "critical_created": critical_created,
            "timeout_action": settings.timeout_action,
        }
