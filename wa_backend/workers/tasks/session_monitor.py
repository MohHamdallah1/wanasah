# SESSION_MONITOR_V2
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select

from database import AsyncSessionLocal
from models import Company, Driver, SystemAuditLog, WorkSession
from workers.app import MAINTENANCE_QUEUE, app
from workers.events import emit_worker_events
from workers.scheduling import defer_unique_company_job
from workers.settings import load_session_monitor_settings
from workers.tenant import acquire_tenant_job_lock, tenant_session

WARNING_AUDIT = "STALE_SESSION_WARNING"
CRITICAL_AUDIT = "STALE_SESSION_CRITICAL"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.periodic(cron="*/15 * * * *")
@app.task(
    name="wanasah.scan_all_stale_sessions",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="stale-session-global-scan",
    lock="stale-session-global-scan",
)
async def scan_all_stale_sessions(
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
    skipped_duplicate = 0
    for company_id in company_ids:
        accepted = await defer_unique_company_job(
            scan_company_stale_sessions,
            lock_namespace="stale-session-company",
            company_id=int(company_id),
        )
        if accepted:
            deferred += 1
        else:
            skipped_duplicate += 1

    return {
        "companies_seen": len(company_ids),
        "company_jobs_deferred": deferred,
        "company_jobs_skipped_duplicate": skipped_duplicate,
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
        await acquire_tenant_job_lock(
            db,
            namespace="stale-session-monitor",
            company_id=int(company_id),
        )
        settings = await load_session_monitor_settings(
            db,
            company_id=int(company_id),
        )
        warning_cutoff = now - timedelta(
            hours=settings.warning_hours
        )
        critical_cutoff = now - timedelta(
            hours=settings.critical_hours
        )

        target_expr = func.concat(
            "WorkSession_",
            WorkSession.id,
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

        sessions = (
            await db.execute(
                select(WorkSession)
                .where(
                    WorkSession.company_id == int(company_id),
                    WorkSession.end_time.is_(None),
                    WorkSession.start_time <= warning_cutoff,
                    or_(
                        and_(
                            WorkSession.start_time <= critical_cutoff,
                            ~critical_audit_exists,
                        ),
                        and_(
                            WorkSession.start_time > critical_cutoff,
                            ~warning_audit_exists,
                        ),
                    ),
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
                select(Driver.id, Driver.full_name).where(
                    Driver.company_id == int(company_id),
                    Driver.id.in_(driver_ids),
                )
            )
        ).all()
        driver_map = {
            int(driver_id): str(full_name)
            for driver_id, full_name in driver_rows
        }

        warnings_created = 0
        critical_created = 0
        events_to_emit: list[dict] = []

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
                message = (
                    f"🚨 جلسة {driver_name} ما زالت مفتوحة لأكثر من "
                    f"{settings.critical_hours} ساعة."
                )
                critical_created += 1
            else:
                action_type = WARNING_AUDIT
                event = "STALE_SESSION_WARNING"
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

            events_to_emit.append(
                {
                    "company_id": int(company_id),
                    "event": event,
                    "message": message,
                    "data": {
                        "work_session_id": int(session.id),
                        "driver_id": int(session.driver_id),
                        "age_hours": round(age_hours, 2),
                    },
                }
            )

        await emit_worker_events(db, events=events_to_emit)
        await db.commit()

        return {
            "company_id": int(company_id),
            "active_stale": len(sessions),
            "warnings_created": warnings_created,
            "critical_created": critical_created,
        }
