# SESSION_MONITOR_V1
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Company, Driver, SystemAuditLog, WorkSession
from workers.app import MAINTENANCE_QUEUE, app
from workers.events import emit_worker_event
from workers.settings import load_session_monitor_settings
from workers.tenant import tenant_session

WARNING_AUDIT = "STALE_SESSION_WARNING"
CRITICAL_AUDIT = "STALE_SESSION_CRITICAL"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.task(
    name="wanasah.scan_all_stale_sessions",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="stale-session-global-scan",
    lock="stale-session-global-scan",
)
async def scan_all_stale_sessions() -> dict[str, int]:
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
        await scan_company_stale_sessions.configure(
            lock=f"stale-session-company:{int(company_id)}",
        ).defer_async(company_id=int(company_id))
        deferred += 1

    return {
        "companies_seen": len(company_ids),
        "company_jobs_deferred": deferred,
    }


@app.task(
    name="wanasah.scan_company_stale_sessions",
    queue=MAINTENANCE_QUEUE,
)
async def scan_company_stale_sessions(
    company_id: int,
) -> dict[str, int]:
    now = _utc_now()

    async with tenant_session(company_id) as db:
        settings = await load_session_monitor_settings(
            db,
            company_id=int(company_id),
        )
        warning_cutoff = now - timedelta(
            hours=settings.warning_hours
        )

        sessions = (
            await db.execute(
                select(WorkSession)
                .filter(
                    WorkSession.company_id == int(company_id),
                    WorkSession.end_time.is_(None),
                    WorkSession.start_time <= warning_cutoff,
                )
                .order_by(
                    WorkSession.start_time.asc(),
                    WorkSession.id.asc(),
                )
                .limit(1000)
            )
        ).scalars().all()

        if not sessions:
            await db.rollback()
            return {
                "company_id": int(company_id),
                "active_stale": 0,
                "warnings_created": 0,
                "critical_created": 0,
            }

        driver_ids = sorted(
            {int(session.driver_id) for session in sessions}
        )
        driver_rows = (
            await db.execute(
                select(Driver.id, Driver.full_name).filter(
                    Driver.company_id == int(company_id),
                    Driver.id.in_(driver_ids),
                )
            )
        ).all()
        driver_map = {
            int(driver_id): str(full_name)
            for driver_id, full_name in driver_rows
        }

        target_ids = [
            f"WorkSession_{int(session.id)}"
            for session in sessions
        ]
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

        for session in sessions:
            if session.start_time is None:
                continue

            age_hours = max(
                0.0,
                (now - session.start_time).total_seconds() / 3600.0,
            )
            target_id = f"WorkSession_{int(session.id)}"
            driver_name = driver_map.get(
                int(session.driver_id),
                "مندوب غير معروف",
            )

            if age_hours >= settings.critical_hours:
                action_type = CRITICAL_AUDIT
                event = "STALE_SESSION_CRITICAL"
                if (target_id, action_type) in prior:
                    continue
                message = (
                    f"🚨 جلسة {driver_name} ما زالت مفتوحة لأكثر من "
                    f"{settings.critical_hours} ساعة."
                )
                critical_created += 1
            else:
                action_type = WARNING_AUDIT
                event = "STALE_SESSION_WARNING"
                if (target_id, action_type) in prior:
                    continue
                message = (
                    f"⚠️ جلسة {driver_name} ما زالت مفتوحة لأكثر من "
                    f"{settings.warning_hours} ساعة."
                )
                warnings_created += 1

            db.add(
                SystemAuditLog(
                    company_id=int(company_id),
                    admin_id=None,
                    target_id=target_id,
                    action_type=action_type,
                    old_value="end_time=NULL",
                    new_value=(
                        f"age_hours={age_hours:.2f}|"
                        f"warning={settings.warning_hours}|"
                        f"critical={settings.critical_hours}|"
                        "action=NOTIFY_ONLY"
                    ),
                )
            )

            await emit_worker_event(
                db,
                company_id=int(company_id),
                event=event,
                message=message,
                data={
                    "work_session_id": int(session.id),
                    "driver_id": int(session.driver_id),
                    "age_hours": round(age_hours, 2),
                },
            )

            prior.add((target_id, action_type))

        await db.commit()

        return {
            "company_id": int(company_id),
            "active_stale": len(sessions),
            "warnings_created": warnings_created,
            "critical_created": critical_created,
        }
