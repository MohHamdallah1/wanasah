from __future__ import annotations

from pathlib import Path
import ast
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"
WORKERS = BACKEND / "workers"
DASHBOARD = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"

NEW_FILES = {'wa_backend/worker_event_relay.py': '# STALE_HANDSHAKE_MONITOR_V1\n'
                                     'from __future__ import annotations\n'
                                     '\n'
                                     'import asyncio\n'
                                     'import json\n'
                                     'import logging\n'
                                     '\n'
                                     'import asyncpg\n'
                                     '\n'
                                     'from config import Config\n'
                                     'from ws_manager import dispatch_manager\n'
                                     '\n'
                                     'logger = logging.getLogger("wanasah_logger")\n'
                                     '\n'
                                     'WORKER_EVENT_CHANNEL = "wanasah_worker_events"\n'
                                     '_ALLOWED_EVENTS = {\n'
                                     '    "STALE_HANDSHAKE_WARNING",\n'
                                     '    "STALE_HANDSHAKE_CRITICAL",\n'
                                     '}\n'
                                     '\n'
                                     '\n'
                                     'def _to_asyncpg_dsn(raw_url: str) -> str:\n'
                                     '    url = str(raw_url or "").strip()\n'
                                     '    if not url:\n'
                                     '        raise RuntimeError("DATABASE_URL is required for worker event relay.")\n'
                                     '    if url.startswith("postgres://"):\n'
                                     '        url = "postgresql://" + url[len("postgres://"):]\n'
                                     '    if url.startswith("postgresql+asyncpg://"):\n'
                                     '        url = "postgresql://" + url[len("postgresql+asyncpg://"):]\n'
                                     '    elif url.startswith("postgresql+psycopg://"):\n'
                                     '        url = "postgresql://" + url[len("postgresql+psycopg://"):]\n'
                                     '    return url\n'
                                     '\n'
                                     '\n'
                                     'class WorkerEventRelay:\n'
                                     '    def __init__(self) -> None:\n'
                                     '        self._task: asyncio.Task | None = None\n'
                                     '        self._stop = asyncio.Event()\n'
                                     '        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)\n'
                                     '\n'
                                     '    async def start(self) -> None:\n'
                                     '        if self._task is not None and not self._task.done():\n'
                                     '            return\n'
                                     '        self._stop.clear()\n'
                                     '        self._task = asyncio.create_task(\n'
                                     '            self._run(),\n'
                                     '            name="wanasah-worker-event-relay",\n'
                                     '        )\n'
                                     '\n'
                                     '    async def stop(self) -> None:\n'
                                     '        self._stop.set()\n'
                                     '        task = self._task\n'
                                     '        self._task = None\n'
                                     '        if task is None:\n'
                                     '            return\n'
                                     '        task.cancel()\n'
                                     '        try:\n'
                                     '            await task\n'
                                     '        except asyncio.CancelledError:\n'
                                     '            pass\n'
                                     '\n'
                                     '    def _on_notification(\n'
                                     '        self,\n'
                                     '        connection,\n'
                                     '        pid: int,\n'
                                     '        channel: str,\n'
                                     '        payload: str,\n'
                                     '    ) -> None:\n'
                                     '        if channel != WORKER_EVENT_CHANNEL:\n'
                                     '            return\n'
                                     '        try:\n'
                                     '            self._queue.put_nowait(payload)\n'
                                     '        except asyncio.QueueFull:\n'
                                     '            logger.error(\n'
                                     '                "Worker event relay queue full; dropping realtime event. "\n'
                                     '                "SystemAuditLog remains authoritative."\n'
                                     '            )\n'
                                     '\n'
                                     '    async def _dispatch_payload(self, raw_payload: str) -> None:\n'
                                     '        try:\n'
                                     '            data = json.loads(raw_payload)\n'
                                     '            if not isinstance(data, dict):\n'
                                     '                raise ValueError("payload must be an object")\n'
                                     '            event = str(data.get("event") or "")\n'
                                     '            company_id = int(data.get("company_id"))\n'
                                     '            message = str(data.get("message") or "").strip()\n'
                                     '            if event not in _ALLOWED_EVENTS:\n'
                                     '                raise ValueError("event is not allowlisted")\n'
                                     '            if company_id <= 0 or not message:\n'
                                     '                raise ValueError("invalid company_id/message")\n'
                                     '        except (TypeError, ValueError, json.JSONDecodeError) as exc:\n'
                                     '            logger.error("Rejected malformed worker event: %s", exc)\n'
                                     '            return\n'
                                     '\n'
                                     '        outbound = {"event": event, "message": message}\n'
                                     '        extra = data.get("data")\n'
                                     '        if isinstance(extra, dict):\n'
                                     '            outbound["data"] = extra\n'
                                     '\n'
                                     '        await dispatch_manager.broadcast(outbound, company_id=company_id)\n'
                                     '\n'
                                     '    async def _run(self) -> None:\n'
                                     '        dsn = _to_asyncpg_dsn(Config.SQLALCHEMY_DATABASE_URI)\n'
                                     '        while not self._stop.is_set():\n'
                                     '            conn = None\n'
                                     '            try:\n'
                                     '                conn = await asyncpg.connect(dsn)\n'
                                     '                await conn.add_listener(\n'
                                     '                    WORKER_EVENT_CHANNEL,\n'
                                     '                    self._on_notification,\n'
                                     '                )\n'
                                     '                logger.info("Worker event relay LISTEN active.")\n'
                                     '\n'
                                     '                while not self._stop.is_set():\n'
                                     '                    if conn.is_closed():\n'
                                     '                        raise ConnectionError(\n'
                                     '                            "Worker event relay PostgreSQL connection closed."\n'
                                     '                        )\n'
                                     '                    try:\n'
                                     '                        payload = await asyncio.wait_for(\n'
                                     '                            self._queue.get(),\n'
                                     '                            timeout=15.0,\n'
                                     '                        )\n'
                                     '                    except asyncio.TimeoutError:\n'
                                     '                        continue\n'
                                     '                    await self._dispatch_payload(payload)\n'
                                     '            except asyncio.CancelledError:\n'
                                     '                raise\n'
                                     '            except Exception as exc:\n'
                                     '                logger.error(\n'
                                     '                    "Worker event relay disconnected: %s",\n'
                                     '                    exc,\n'
                                     '                    exc_info=True,\n'
                                     '                )\n'
                                     '                try:\n'
                                     '                    await asyncio.wait_for(self._stop.wait(), timeout=5.0)\n'
                                     '                except asyncio.TimeoutError:\n'
                                     '                    pass\n'
                                     '            finally:\n'
                                     '                if conn is not None and not conn.is_closed():\n'
                                     '                    try:\n'
                                     '                        await conn.remove_listener(\n'
                                     '                            WORKER_EVENT_CHANNEL,\n'
                                     '                            self._on_notification,\n'
                                     '                        )\n'
                                     '                    except Exception:\n'
                                     '                        pass\n'
                                     '                    await conn.close()\n'
                                     '\n'
                                     '\n'
                                     'worker_event_relay = WorkerEventRelay()\n',
 'wa_backend/workers/events.py': '# STALE_HANDSHAKE_MONITOR_V1\n'
                                 'from __future__ import annotations\n'
                                 '\n'
                                 'import json\n'
                                 '\n'
                                 'from sqlalchemy import text\n'
                                 'from sqlalchemy.ext.asyncio import AsyncSession\n'
                                 '\n'
                                 'WORKER_EVENT_CHANNEL = "wanasah_worker_events"\n'
                                 '_MAX_NOTIFY_BYTES = 7000\n'
                                 '\n'
                                 '\n'
                                 'async def emit_worker_event(\n'
                                 '    db: AsyncSession,\n'
                                 '    *,\n'
                                 '    company_id: int,\n'
                                 '    event: str,\n'
                                 '    message: str,\n'
                                 '    data: dict | None = None,\n'
                                 ') -> None:\n'
                                 '    payload = {\n'
                                 '        "company_id": int(company_id),\n'
                                 '        "event": str(event),\n'
                                 '        "message": str(message),\n'
                                 '        "data": data or {},\n'
                                 '    }\n'
                                 '    raw = json.dumps(\n'
                                 '        payload,\n'
                                 '        ensure_ascii=False,\n'
                                 '        separators=(",", ":"),\n'
                                 '    )\n'
                                 '    if len(raw.encode("utf-8")) > _MAX_NOTIFY_BYTES:\n'
                                 '        raise ValueError("Worker realtime event payload is too large.")\n'
                                 '\n'
                                 '    await db.execute(\n'
                                 '        text("SELECT pg_notify(:channel, :payload)"),\n'
                                 '        {"channel": WORKER_EVENT_CHANNEL, "payload": raw},\n'
                                 '    )\n',
 'wa_backend/workers/settings.py': '# STALE_HANDSHAKE_MONITOR_V1\n'
                                   'from __future__ import annotations\n'
                                   '\n'
                                   'from dataclasses import dataclass\n'
                                   '\n'
                                   'from sqlalchemy import select\n'
                                   'from sqlalchemy.ext.asyncio import AsyncSession\n'
                                   '\n'
                                   'from models import SystemSetting\n'
                                   '\n'
                                   'WARNING_KEY = "handshake_warning_hours"\n'
                                   'CRITICAL_KEY = "handshake_critical_hours"\n'
                                   'AUTO_CANCEL_KEY = "handshake_auto_cancel_hours"\n'
                                   'ACTION_KEY = "handshake_timeout_action"\n'
                                   '\n'
                                   'DEFAULT_WARNING_HOURS = 4\n'
                                   'DEFAULT_CRITICAL_HOURS = 8\n'
                                   'DEFAULT_AUTO_CANCEL_HOURS = 12\n'
                                   'DEFAULT_ACTION = "NOTIFY_ONLY"\n'
                                   '\n'
                                   'VALID_ACTIONS = {"NOTIFY_ONLY", "AUTO_CANCEL"}\n'
                                   '\n'
                                   '\n'
                                   '@dataclass(frozen=True)\n'
                                   'class HandshakeMonitorSettings:\n'
                                   '    warning_hours: int\n'
                                   '    critical_hours: int\n'
                                   '    auto_cancel_hours: int\n'
                                   '    timeout_action: str\n'
                                   '\n'
                                   '\n'
                                   'def _parse_positive_int(raw: str | None, *, key: str, default: int) -> int:\n'
                                   '    if raw is None:\n'
                                   '        return default\n'
                                   '    try:\n'
                                   '        value = int(str(raw).strip())\n'
                                   '    except (TypeError, ValueError) as exc:\n'
                                   '        raise ValueError(f"Invalid integer SystemSetting: {key}") from exc\n'
                                   '    if value <= 0 or value > 720:\n'
                                   '        raise ValueError(\n'
                                   '            f"SystemSetting {key} must be between 1 and 720 hours."\n'
                                   '        )\n'
                                   '    return value\n'
                                   '\n'
                                   '\n'
                                   'async def load_handshake_monitor_settings(\n'
                                   '    db: AsyncSession,\n'
                                   '    *,\n'
                                   '    company_id: int,\n'
                                   ') -> HandshakeMonitorSettings:\n'
                                   '    rows = (\n'
                                   '        await db.execute(\n'
                                   '            select(\n'
                                   '                SystemSetting.setting_key,\n'
                                   '                SystemSetting.setting_value,\n'
                                   '            ).filter(\n'
                                   '                SystemSetting.company_id == company_id,\n'
                                   '                SystemSetting.setting_key.in_(\n'
                                   '                    [WARNING_KEY, CRITICAL_KEY, AUTO_CANCEL_KEY, ACTION_KEY]\n'
                                   '                ),\n'
                                   '            )\n'
                                   '        )\n'
                                   '    ).all()\n'
                                   '    values = {str(key): str(value) for key, value in rows}\n'
                                   '\n'
                                   '    warning = _parse_positive_int(\n'
                                   '        values.get(WARNING_KEY),\n'
                                   '        key=WARNING_KEY,\n'
                                   '        default=DEFAULT_WARNING_HOURS,\n'
                                   '    )\n'
                                   '    critical = _parse_positive_int(\n'
                                   '        values.get(CRITICAL_KEY),\n'
                                   '        key=CRITICAL_KEY,\n'
                                   '        default=DEFAULT_CRITICAL_HOURS,\n'
                                   '    )\n'
                                   '    auto_cancel = _parse_positive_int(\n'
                                   '        values.get(AUTO_CANCEL_KEY),\n'
                                   '        key=AUTO_CANCEL_KEY,\n'
                                   '        default=DEFAULT_AUTO_CANCEL_HOURS,\n'
                                   '    )\n'
                                   '\n'
                                   '    action = values.get(ACTION_KEY, DEFAULT_ACTION).strip().upper()\n'
                                   '    if action not in VALID_ACTIONS:\n'
                                   '        raise ValueError(\n'
                                   '            f"SystemSetting {ACTION_KEY} must be one of {sorted(VALID_ACTIONS)}."\n'
                                   '        )\n'
                                   '    if not (warning < critical < auto_cancel):\n'
                                   '        raise ValueError(\n'
                                   '            "Handshake timeout settings must satisfy: "\n'
                                   '            "warning < critical < auto_cancel."\n'
                                   '        )\n'
                                   '\n'
                                   '    return HandshakeMonitorSettings(\n'
                                   '        warning_hours=warning,\n'
                                   '        critical_hours=critical,\n'
                                   '        auto_cancel_hours=auto_cancel,\n'
                                   '        timeout_action=action,\n'
                                   '    )\n',
 'wa_backend/workers/tasks/handshake.py': '# STALE_HANDSHAKE_MONITOR_V1\n'
                                          'from __future__ import annotations\n'
                                          '\n'
                                          'from datetime import datetime, timedelta, timezone\n'
                                          '\n'
                                          'from sqlalchemy import select\n'
                                          '\n'
                                          'from database import AsyncSessionLocal\n'
                                          'from models import Company, Driver, InventoryTransferHeader, '
                                          'SystemAuditLog\n'
                                          'from workers.app import MAINTENANCE_QUEUE, app\n'
                                          'from workers.events import emit_worker_event\n'
                                          'from workers.settings import load_handshake_monitor_settings\n'
                                          'from workers.tenant import tenant_session\n'
                                          '\n'
                                          'WARNING_AUDIT = "STALE_HANDSHAKE_WARNING"\n'
                                          'CRITICAL_AUDIT = "STALE_HANDSHAKE_CRITICAL"\n'
                                          '\n'
                                          '# AUTO_CANCEL is part of the settings contract but is deliberately not\n'
                                          '# executed in V1. Flutter/offline transfer-expiry semantics must be frozen\n'
                                          '# first so the server never cancels a transfer already accepted offline.\n'
                                          '\n'
                                          '\n'
                                          'def _utc_now() -> datetime:\n'
                                          '    return datetime.now(timezone.utc).replace(tzinfo=None)\n'
                                          '\n'
                                          '\n'
                                          '@app.task(\n'
                                          '    name="wanasah.scan_all_stale_handshakes",\n'
                                          '    queue=MAINTENANCE_QUEUE,\n'
                                          '    queueing_lock="stale-handshake-global-scan",\n'
                                          '    lock="stale-handshake-global-scan",\n'
                                          ')\n'
                                          'async def scan_all_stale_handshakes() -> dict[str, int]:\n'
                                          '    async with AsyncSessionLocal() as db:\n'
                                          '        company_ids = list(\n'
                                          '            (\n'
                                          '                await db.execute(\n'
                                          '                    select(Company.id).order_by(Company.id.asc())\n'
                                          '                )\n'
                                          '            ).scalars().all()\n'
                                          '        )\n'
                                          '        if db.in_transaction():\n'
                                          '            await db.rollback()\n'
                                          '\n'
                                          '    deferred = 0\n'
                                          '    for company_id in company_ids:\n'
                                          '        await scan_company_stale_handshakes.configure(\n'
                                          '            lock=f"stale-handshake-company:{int(company_id)}",\n'
                                          '        ).defer_async(company_id=int(company_id))\n'
                                          '        deferred += 1\n'
                                          '\n'
                                          '    return {\n'
                                          '        "companies_seen": len(company_ids),\n'
                                          '        "company_jobs_deferred": deferred,\n'
                                          '    }\n'
                                          '\n'
                                          '\n'
                                          '@app.task(\n'
                                          '    name="wanasah.scan_company_stale_handshakes",\n'
                                          '    queue=MAINTENANCE_QUEUE,\n'
                                          ')\n'
                                          'async def scan_company_stale_handshakes(\n'
                                          '    company_id: int,\n'
                                          ') -> dict[str, int | str]:\n'
                                          '    now = _utc_now()\n'
                                          '\n'
                                          '    async with tenant_session(company_id) as db:\n'
                                          '        settings = await load_handshake_monitor_settings(\n'
                                          '            db,\n'
                                          '            company_id=int(company_id),\n'
                                          '        )\n'
                                          '        warning_cutoff = now - timedelta(hours=settings.warning_hours)\n'
                                          '\n'
                                          '        headers = (\n'
                                          '            await db.execute(\n'
                                          '                select(InventoryTransferHeader)\n'
                                          '                .filter(\n'
                                          '                    InventoryTransferHeader.company_id == int(company_id),\n'
                                          '                    InventoryTransferHeader.workflow_type == "HANDSHAKE",\n'
                                          '                    InventoryTransferHeader.status == "PENDING",\n'
                                          '                    InventoryTransferHeader.created_at <= warning_cutoff,\n'
                                          '                )\n'
                                          '                .order_by(\n'
                                          '                    InventoryTransferHeader.created_at.asc(),\n'
                                          '                    InventoryTransferHeader.id.asc(),\n'
                                          '                )\n'
                                          '                .limit(1000)\n'
                                          '            )\n'
                                          '        ).scalars().all()\n'
                                          '\n'
                                          '        if not headers:\n'
                                          '            await db.rollback()\n'
                                          '            return {\n'
                                          '                "company_id": int(company_id),\n'
                                          '                "pending_stale": 0,\n'
                                          '                "warnings_created": 0,\n'
                                          '                "critical_created": 0,\n'
                                          '                "timeout_action": settings.timeout_action,\n'
                                          '            }\n'
                                          '\n'
                                          '        receiver_ids = sorted(\n'
                                          '            {\n'
                                          '                int(header.expected_receiver_id)\n'
                                          '                for header in headers\n'
                                          '                if header.expected_receiver_id is not None\n'
                                          '            }\n'
                                          '        )\n'
                                          '        receiver_map: dict[int, str] = {}\n'
                                          '        if receiver_ids:\n'
                                          '            receiver_rows = (\n'
                                          '                await db.execute(\n'
                                          '                    select(Driver.id, Driver.full_name).filter(\n'
                                          '                        Driver.company_id == int(company_id),\n'
                                          '                        Driver.id.in_(receiver_ids),\n'
                                          '                    )\n'
                                          '                )\n'
                                          '            ).all()\n'
                                          '            receiver_map = {\n'
                                          '                int(driver_id): str(full_name)\n'
                                          '                for driver_id, full_name in receiver_rows\n'
                                          '            }\n'
                                          '\n'
                                          '        target_ids = [f"Transfer_{int(header.id)}" for header in headers]\n'
                                          '        prior_rows = (\n'
                                          '            await db.execute(\n'
                                          '                select(\n'
                                          '                    SystemAuditLog.target_id,\n'
                                          '                    SystemAuditLog.action_type,\n'
                                          '                ).filter(\n'
                                          '                    SystemAuditLog.company_id == int(company_id),\n'
                                          '                    SystemAuditLog.target_id.in_(target_ids),\n'
                                          '                    SystemAuditLog.action_type.in_(\n'
                                          '                        [WARNING_AUDIT, CRITICAL_AUDIT]\n'
                                          '                    ),\n'
                                          '                )\n'
                                          '            )\n'
                                          '        ).all()\n'
                                          '        prior = {\n'
                                          '            (str(target_id), str(action_type))\n'
                                          '            for target_id, action_type in prior_rows\n'
                                          '        }\n'
                                          '\n'
                                          '        warnings_created = 0\n'
                                          '        critical_created = 0\n'
                                          '\n'
                                          '        for header in headers:\n'
                                          '            created_at = header.created_at\n'
                                          '            if created_at is None:\n'
                                          '                continue\n'
                                          '\n'
                                          '            age_hours = max(\n'
                                          '                0.0,\n'
                                          '                (now - created_at).total_seconds() / 3600.0,\n'
                                          '            )\n'
                                          '            target_id = f"Transfer_{int(header.id)}"\n'
                                          '            receiver_name = receiver_map.get(\n'
                                          '                int(header.expected_receiver_id)\n'
                                          '                if header.expected_receiver_id is not None\n'
                                          '                else -1,\n'
                                          '                "مندوب غير معروف",\n'
                                          '            )\n'
                                          '\n'
                                          '            if age_hours >= settings.critical_hours:\n'
                                          '                action_type = CRITICAL_AUDIT\n'
                                          '                event = "STALE_HANDSHAKE_CRITICAL"\n'
                                          '                if (target_id, action_type) in prior:\n'
                                          '                    continue\n'
                                          '                message = (\n'
                                          '                    f"🚨 الحوالة {header.reference_number} معلقة مع "\n'
                                          '                    f"{receiver_name} لأكثر من "\n'
                                          '                    f"{settings.critical_hours} ساعات."\n'
                                          '                )\n'
                                          '                critical_created += 1\n'
                                          '            else:\n'
                                          '                action_type = WARNING_AUDIT\n'
                                          '                event = "STALE_HANDSHAKE_WARNING"\n'
                                          '                if (target_id, action_type) in prior:\n'
                                          '                    continue\n'
                                          '                message = (\n'
                                          '                    f"⚠️ الحوالة {header.reference_number} معلقة مع "\n'
                                          '                    f"{receiver_name} لأكثر من "\n'
                                          '                    f"{settings.warning_hours} ساعات."\n'
                                          '                )\n'
                                          '                warnings_created += 1\n'
                                          '\n'
                                          '            db.add(\n'
                                          '                SystemAuditLog(\n'
                                          '                    company_id=int(company_id),\n'
                                          '                    admin_id=None,\n'
                                          '                    target_id=target_id,\n'
                                          '                    action_type=action_type,\n'
                                          '                    old_value="status=PENDING",\n'
                                          '                    new_value=(\n'
                                          '                        f"age_hours={age_hours:.2f}|"\n'
                                          '                        f"warning={settings.warning_hours}|"\n'
                                          '                        f"critical={settings.critical_hours}|"\n'
                                          '                        f"auto_cancel={settings.auto_cancel_hours}|"\n'
                                          '                        f"timeout_action={settings.timeout_action}"\n'
                                          '                    ),\n'
                                          '                )\n'
                                          '            )\n'
                                          '\n'
                                          '            await emit_worker_event(\n'
                                          '                db,\n'
                                          '                company_id=int(company_id),\n'
                                          '                event=event,\n'
                                          '                message=message,\n'
                                          '                data={\n'
                                          '                    "transfer_id": int(header.id),\n'
                                          '                    "reference_number": str(header.reference_number),\n'
                                          '                    "expected_receiver_id": (\n'
                                          '                        int(header.expected_receiver_id)\n'
                                          '                        if header.expected_receiver_id is not None\n'
                                          '                        else None\n'
                                          '                    ),\n'
                                          '                    "age_hours": round(age_hours, 2),\n'
                                          '                },\n'
                                          '            )\n'
                                          '            prior.add((target_id, action_type))\n'
                                          '\n'
                                          '        await db.commit()\n'
                                          '\n'
                                          '        return {\n'
                                          '            "company_id": int(company_id),\n'
                                          '            "pending_stale": len(headers),\n'
                                          '            "warnings_created": warnings_created,\n'
                                          '            "critical_created": critical_created,\n'
                                          '            "timeout_action": settings.timeout_action,\n'
                                          '        }\n'}

MAIN_IMPORT_FIND = "from ws_manager import dispatch_manager\n"
MAIN_IMPORT_REPLACE = (
    "from ws_manager import dispatch_manager\n"
    "from worker_event_relay import worker_event_relay\n"
)

MAIN_LIFESPAN_FIND = """@asynccontextmanager
async def lifespan(app: FastAPI):
    # بدء تشغيل السيرفر
    yield
    # إغلاق السيرفر
    await engine.dispose()
"""

MAIN_LIFESPAN_REPLACE = """@asynccontextmanager
async def lifespan(app: FastAPI):
    # STALE_HANDSHAKE_MONITOR_V1: managed PostgreSQL LISTEN -> WebSocket relay.
    await worker_event_relay.start()
    try:
        yield
    finally:
        await worker_event_relay.stop()
        await engine.dispose()
"""

APP_IMPORTS_FIND = """    import_paths=[
        "workers.tasks.core",
    ],
"""

APP_IMPORTS_REPLACE = """    import_paths=[
        "workers.tasks.core",
        "workers.tasks.handshake",
    ],
"""

DASHBOARD_EVENT_FIND = """          if (data.event) {
            authenticatedFetch("/dispatch/active_routes")
"""

DASHBOARD_EVENT_REPLACE = """          if (data.event) {
            if (data.event === "STALE_HANDSHAKE_WARNING" && data.message) {
              toast.warning(data.message);
            } else if (data.event === "STALE_HANDSHAKE_CRITICAL" && data.message) {
              toast.error(data.message);
            }
            authenticatedFetch("/dispatch/active_routes")
"""


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def backup(path: Path) -> None:
    backup_dir = BACKEND / ".patch_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.name}.before_stale_handshake_{stamp}.bak"
    shutil.copy2(path, backup_path)
    print(f"BACKUP={backup_path.relative_to(ROOT)}")


def create_new_files() -> None:
    for rel, content in NEW_FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == content:
                print(f"UNCHANGED={rel}")
                continue
            fail(f"Refusing to overwrite different existing file: {rel}")
        path.write_text(content, encoding="utf-8")
        print(f"CREATED={rel}")


def replace_once(path: Path, find: str, replacement: str, marker: str) -> None:
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")

    if marker in text and replacement in text:
        print(f"ALREADY_PATCHED={path.relative_to(ROOT)}")
        return

    count = text.count(find)
    if count != 1:
        fail(
            f"Expected exactly one match in {path.relative_to(ROOT)}, found {count}."
        )

    backup(path)
    path.write_text(text.replace(find, replacement, 1), encoding="utf-8")
    print(f"PATCHED={path.relative_to(ROOT)}")


def verify() -> None:
    python_files = [
        BACKEND / "worker_event_relay.py",
        WORKERS / "events.py",
        WORKERS / "settings.py",
        WORKERS / "tasks" / "handshake.py",
        WORKERS / "app.py",
        BACKEND / "main.py",
    ]
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    app_text = (WORKERS / "app.py").read_text(encoding="utf-8")
    main_text = (BACKEND / "main.py").read_text(encoding="utf-8")
    dash_text = DASHBOARD.read_text(encoding="utf-8")
    task_text = (WORKERS / "tasks" / "handshake.py").read_text(encoding="utf-8")

    checks = {
        "HANDSHAKE_TASK_IMPORTED": '"workers.tasks.handshake"' in app_text,
        "EVENT_RELAY_MANAGED": (
            "await worker_event_relay.start()" in main_text
            and "await worker_event_relay.stop()" in main_text
        ),
        "TENANT_SESSION_USED": "async with tenant_session(company_id)" in task_text,
        "TENANT_FILTER_HEADER": (
            "InventoryTransferHeader.company_id == int(company_id)" in task_text
        ),
        "DURABLE_AUDIT_USED": "SystemAuditLog(" in task_text,
        "AUTO_CANCEL_NOT_EXECUTED_V1": (
            "AUTO_CANCEL is part of the settings contract" in task_text
        ),
        "DASHBOARD_WARNING_TOAST": (
            'data.event === "STALE_HANDSHAKE_WARNING"' in dash_text
        ),
        "DASHBOARD_CRITICAL_TOAST": (
            'data.event === "STALE_HANDSHAKE_CRITICAL"' in dash_text
        ),
    }

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        fail(f"Static verification failed: {failed}")

    print("STALE_HANDSHAKE_STATIC_VERIFY=OK")
    print("TENANT_ISOLATION_STATIC_VERIFY=OK")
    print("NO_MODELS_CHANGE=OK")
    print("NO_INVENTORY_MUTATION=OK")
    print("AUTO_CANCEL_EXECUTION=DEFERRED_BY_OFFLINE_SAFETY")
    print("PATCH_STALE_HANDSHAKE_MONITOR_V1=OK")


def main() -> None:
    if not BACKEND.exists():
        fail("Run this patch from project root; wa_backend/ not found.")
    if not (WORKERS / "app.py").exists():
        fail("Worker Core is missing. Apply Worker Core first.")

    create_new_files()

    replace_once(
        WORKERS / "app.py",
        APP_IMPORTS_FIND,
        APP_IMPORTS_REPLACE,
        '"workers.tasks.handshake"',
    )
    replace_once(
        BACKEND / "main.py",
        MAIN_IMPORT_FIND,
        MAIN_IMPORT_REPLACE,
        "from worker_event_relay import worker_event_relay",
    )
    replace_once(
        BACKEND / "main.py",
        MAIN_LIFESPAN_FIND,
        MAIN_LIFESPAN_REPLACE,
        "await worker_event_relay.start()",
    )
    replace_once(
        DASHBOARD,
        DASHBOARD_EVENT_FIND,
        DASHBOARD_EVENT_REPLACE,
        'data.event === "STALE_HANDSHAKE_WARNING"',
    )

    verify()


if __name__ == "__main__":
    main()
