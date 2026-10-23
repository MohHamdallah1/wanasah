"""FIELD capability HTTP dependencies. Business endpoint wiring is Phase 3."""
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.capabilities import FIELD_ASSIGNABLE_PERMISSIONS
from domains.authorization.field_access import FieldCapabilityAccess, FieldCapabilityAccessRejected
from .dependencies import get_current_field_context

FieldCapabilityDependency = Callable[..., Awaitable[FieldCapabilityAccess]]


def _denied():
    return HTTPException(403, detail={"code":"FIELD_CAPABILITY_DENIED",
        "message":"The FIELD capability is not granted.", "context":{}})


async def get_current_field_capability_access(
    current: FieldRequestContext = Depends(get_current_field_context),
    db: AsyncSession = Depends(get_db),
) -> FieldCapabilityAccess:
    try:
        return FieldCapabilityAccess(db, current)
    except FieldCapabilityAccessRejected:
        raise _denied() from None


def require_field_capabilities(codes: tuple[str, ...]) -> FieldCapabilityDependency:
    if type(codes) is not tuple or not codes or any(type(c) is not str for c in codes) or not set(codes) <= FIELD_ASSIGNABLE_PERMISSIONS:
        raise ValueError("Unknown FIELD capability")

    async def dependency(access: FieldCapabilityAccess = Depends(get_current_field_capability_access)):
        try:
            await access.require_all(codes)
        except FieldCapabilityAccessRejected:
            raise _denied() from None
        return access
    return dependency


def require_field_capability(code: str) -> FieldCapabilityDependency:
    return require_field_capabilities((code,))
