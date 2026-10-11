"""Temporary operational Driver adapter for canonically authenticated field requests."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.field_subject import resolve_field_authorization_subject
from models import Driver

from .dependencies import _authentication_rejected, get_current_field_context


async def get_current_field_legacy_driver(
    current: FieldRequestContext = Depends(get_current_field_context),
    db: AsyncSession = Depends(get_db),
) -> Driver:
    """Return an active legacy workflow/FK object, never an identity authority.

    The canonical context owns authentication and the field subject owns the
    exact legacy locator. The request retains tenant and transaction ownership.
    Remove this seam when field workflows no longer require a Driver object.
    """
    try:
        subject = await resolve_field_authorization_subject(db, current)
        result = await db.execute(
            select(Driver).where(
                Driver.company_id == subject.company_id,
                Driver.id == subject.legacy_driver_id,
            )
        )
        driver = result.scalar_one_or_none()
        usable = (
            driver is not None
            and driver.company_id == subject.company_id
            and driver.id == subject.legacy_driver_id
            and driver.is_active is True
        )
    except Exception:
        # Mapping/persistence failures must not expose database or identity data.
        raise _authentication_rejected() from None

    if not usable:
        raise _authentication_rejected()
    return driver


__all__ = ["get_current_field_legacy_driver"]
