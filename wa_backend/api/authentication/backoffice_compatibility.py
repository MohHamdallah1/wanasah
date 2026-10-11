"""Temporary operational Driver adapter for canonical Backoffice requests."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from domains.auth_sessions.context import DashboardRequestContext
from domains.identity.backoffice_legacy_actor import (
    resolve_backoffice_legacy_actor_locator,
)
from models import Driver

from .dependencies import _authentication_rejected, get_current_backoffice_context


async def get_current_backoffice_legacy_driver(
    current: DashboardRequestContext = Depends(get_current_backoffice_context),
    db: AsyncSession = Depends(get_db),
) -> Driver:
    """Return an active legacy Driver only for operational/FK compatibility.

    Canonical Dashboard context owns authentication and canonical capability
    access owns authorization. This adapter never derives authority from Driver.
    """
    try:
        locator = await resolve_backoffice_legacy_actor_locator(db, current)
        result = await db.execute(
            select(Driver).where(
                Driver.company_id == locator.company_id,
                Driver.id == locator.legacy_driver_id,
            )
        )
        driver = result.scalar_one_or_none()
        usable = (
            driver is not None
            and driver.company_id == locator.company_id
            and driver.id == locator.legacy_driver_id
            and driver.is_active is True
        )
    except Exception:
        # Mapping/persistence failures must not expose identity or storage internals.
        raise _authentication_rejected() from None

    if not usable:
        raise _authentication_rejected()
    return driver


__all__ = ["get_current_backoffice_legacy_driver"]
