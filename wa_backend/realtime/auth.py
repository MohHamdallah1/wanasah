from __future__ import annotations

from dataclasses import dataclass

import jwt
from sqlalchemy import select

from config import Config
from models import Driver, TokenBlacklist
from workers.tenant import tenant_session
from token_identity import access_token_identity


class WebSocketAuthError(Exception):
    pass


@dataclass(frozen=True)
class WebSocketAdminIdentity:
    company_id: int
    driver_id: int


async def _authenticate_websocket_identity(
    token: str,
    *,
    require_admin: bool,
) -> WebSocketAdminIdentity:
    try:
        payload = jwt.decode(
            token,
            Config.SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
        driver_id, company_id = access_token_identity(payload)
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise WebSocketAuthError("invalid websocket token") from exc

    async with tenant_session(company_id) as db:
        blacklisted = (
            await db.execute(
                select(TokenBlacklist.id).where(TokenBlacklist.token == token)
            )
        ).scalar_one_or_none()
        if blacklisted is not None:
            raise WebSocketAuthError("revoked websocket token")

        driver = (
            await db.execute(
                select(Driver).where(
                    Driver.company_id == company_id,
                    Driver.id == driver_id,
                )
            )
        ).scalar_one_or_none()

        if (
            driver is None
            or not bool(driver.is_active)
            or (
                require_admin
                and not bool(driver.is_admin)
            )
        ):
            raise WebSocketAuthError(
                "websocket authorization failed"
            )

    return WebSocketAdminIdentity(
        company_id=company_id,
        driver_id=driver_id,
    )


async def authenticate_websocket_admin(
    token: str,
) -> WebSocketAdminIdentity:
    return await _authenticate_websocket_identity(
        token,
        require_admin=True,
    )


async def authenticate_websocket_user(
    token: str,
) -> WebSocketAdminIdentity:
    """Authenticate an active dashboard user; endpoint scopes permissions."""
    return await _authenticate_websocket_identity(
        token,
        require_admin=False,
    )
