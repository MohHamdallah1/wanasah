from __future__ import annotations

from dataclasses import dataclass

import jwt
from sqlalchemy import select

from config import Config
from models import Driver, TokenBlacklist
from workers.tenant import normalize_company_id, tenant_session


class WebSocketAuthError(Exception):
    pass


@dataclass(frozen=True)
class WebSocketAdminIdentity:
    company_id: int
    driver_id: int


async def authenticate_websocket_admin(token: str) -> WebSocketAdminIdentity:
    try:
        payload = jwt.decode(
            token,
            Config.SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
        company_id = normalize_company_id(payload.get("company_id"))
        driver_id = int(payload.get("sub"))
        if driver_id <= 0:
            raise ValueError
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
            or not bool(driver.is_admin)
        ):
            raise WebSocketAuthError("websocket admin authorization failed")

    return WebSocketAdminIdentity(
        company_id=company_id,
        driver_id=driver_id,
    )
