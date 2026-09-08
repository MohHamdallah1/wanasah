# WORKER_SETTINGS_V2
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SystemSetting

logger = logging.getLogger("wanasah_logger")

WARNING_KEY = "handshake_warning_hours"
CRITICAL_KEY = "handshake_critical_hours"
AUTO_CANCEL_KEY = "handshake_auto_cancel_hours"
ACTION_KEY = "handshake_timeout_action"

DEFAULT_WARNING_HOURS = 4
DEFAULT_CRITICAL_HOURS = 8
DEFAULT_AUTO_CANCEL_HOURS = 12
DEFAULT_ACTION = "NOTIFY_ONLY"

VALID_ACTIONS = {"NOTIFY_ONLY", "AUTO_CANCEL"}


@dataclass(frozen=True)
class HandshakeMonitorSettings:
    warning_hours: int
    critical_hours: int
    auto_cancel_hours: int
    timeout_action: str


def _parse_positive_int(raw: str | None, *, key: str, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer SystemSetting: {key}") from exc
    if value <= 0 or value > 720:
        raise ValueError(
            f"SystemSetting {key} must be between 1 and 720 hours."
        )
    return value


def _default_handshake_settings() -> HandshakeMonitorSettings:
    return HandshakeMonitorSettings(
        warning_hours=DEFAULT_WARNING_HOURS,
        critical_hours=DEFAULT_CRITICAL_HOURS,
        auto_cancel_hours=DEFAULT_AUTO_CANCEL_HOURS,
        timeout_action=DEFAULT_ACTION,
    )


async def load_handshake_monitor_settings(
    db: AsyncSession,
    *,
    company_id: int,
) -> HandshakeMonitorSettings:
    rows = (
        await db.execute(
            select(
                SystemSetting.setting_key,
                SystemSetting.setting_value,
            ).filter(
                SystemSetting.company_id == company_id,
                SystemSetting.setting_key.in_(
                    [WARNING_KEY, CRITICAL_KEY, AUTO_CANCEL_KEY, ACTION_KEY]
                ),
            )
        )
    ).all()
    values = {str(key): str(value) for key, value in rows}

    try:
        warning = _parse_positive_int(
            values.get(WARNING_KEY),
            key=WARNING_KEY,
            default=DEFAULT_WARNING_HOURS,
        )
        critical = _parse_positive_int(
            values.get(CRITICAL_KEY),
            key=CRITICAL_KEY,
            default=DEFAULT_CRITICAL_HOURS,
        )
        auto_cancel = _parse_positive_int(
            values.get(AUTO_CANCEL_KEY),
            key=AUTO_CANCEL_KEY,
            default=DEFAULT_AUTO_CANCEL_HOURS,
        )
        action = values.get(ACTION_KEY, DEFAULT_ACTION).strip().upper()
        if action not in VALID_ACTIONS:
            raise ValueError(
                f"SystemSetting {ACTION_KEY} must be one of "
                f"{sorted(VALID_ACTIONS)}."
            )
        if not (warning < critical < auto_cancel):
            raise ValueError(
                "Handshake timeout settings must satisfy: "
                "warning < critical < auto_cancel."
            )
    except ValueError as exc:
        defaults = _default_handshake_settings()
        logger.critical(
            "Invalid handshake monitor settings for company %s; "
            "using full safe defaults warning=%s critical=%s "
            "auto_cancel=%s action=%s. Error: %s",
            company_id,
            defaults.warning_hours,
            defaults.critical_hours,
            defaults.auto_cancel_hours,
            defaults.timeout_action,
            exc,
        )
        return defaults

    return HandshakeMonitorSettings(
        warning_hours=warning,
        critical_hours=critical,
        auto_cancel_hours=auto_cancel,
        timeout_action=action,
    )


# SESSION_MONITOR_V2
SESSION_WARNING_KEY = "session_warning_hours"
SESSION_CRITICAL_KEY = "session_critical_hours"

DEFAULT_SESSION_WARNING_HOURS = 12
DEFAULT_SESSION_CRITICAL_HOURS = 16


@dataclass(frozen=True)
class SessionMonitorSettings:
    warning_hours: int
    critical_hours: int


def _default_session_settings() -> SessionMonitorSettings:
    return SessionMonitorSettings(
        warning_hours=DEFAULT_SESSION_WARNING_HOURS,
        critical_hours=DEFAULT_SESSION_CRITICAL_HOURS,
    )


async def load_session_monitor_settings(
    db: AsyncSession,
    *,
    company_id: int,
) -> SessionMonitorSettings:
    rows = (
        await db.execute(
            select(
                SystemSetting.setting_key,
                SystemSetting.setting_value,
            ).filter(
                SystemSetting.company_id == company_id,
                SystemSetting.setting_key.in_(
                    [SESSION_WARNING_KEY, SESSION_CRITICAL_KEY]
                ),
            )
        )
    ).all()
    values = {str(key): str(value) for key, value in rows}

    try:
        warning = _parse_positive_int(
            values.get(SESSION_WARNING_KEY),
            key=SESSION_WARNING_KEY,
            default=DEFAULT_SESSION_WARNING_HOURS,
        )
        critical = _parse_positive_int(
            values.get(SESSION_CRITICAL_KEY),
            key=SESSION_CRITICAL_KEY,
            default=DEFAULT_SESSION_CRITICAL_HOURS,
        )
        if warning >= critical:
            raise ValueError(
                "Session monitor settings must satisfy: warning < critical."
            )
    except ValueError as exc:
        defaults = _default_session_settings()
        logger.critical(
            "Invalid session monitor settings for company %s; "
            "using full safe defaults warning=%s critical=%s. Error: %s",
            company_id,
            defaults.warning_hours,
            defaults.critical_hours,
            exc,
        )
        return defaults

    return SessionMonitorSettings(
        warning_hours=warning,
        critical_hours=critical,
    )


# INTEGRITY_JOBS_V2
INTEGRITY_REPEAT_KEY = "integrity_alert_repeat_hours"
DEFAULT_INTEGRITY_REPEAT_HOURS = 24


@dataclass(frozen=True)
class IntegrityMonitorSettings:
    repeat_hours: int


async def load_integrity_monitor_settings(
    db: AsyncSession,
    *,
    company_id: int,
) -> IntegrityMonitorSettings:
    row = (
        await db.execute(
            select(SystemSetting.setting_value).where(
                SystemSetting.company_id == company_id,
                SystemSetting.setting_key == INTEGRITY_REPEAT_KEY,
            )
        )
    ).scalar_one_or_none()

    try:
        repeat_hours = _parse_positive_int(
            str(row) if row is not None else None,
            key=INTEGRITY_REPEAT_KEY,
            default=DEFAULT_INTEGRITY_REPEAT_HOURS,
        )
    except ValueError as exc:
        logger.critical(
            "Invalid integrity monitor settings for company %s; "
            "using safe default repeat_hours=%s. Error: %s",
            company_id,
            DEFAULT_INTEGRITY_REPEAT_HOURS,
            exc,
        )
        repeat_hours = DEFAULT_INTEGRITY_REPEAT_HOURS

    return IntegrityMonitorSettings(repeat_hours=repeat_hours)
