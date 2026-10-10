"""Canonical logout HTTP adapter, deliberately not mounted on the runtime app."""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from database import get_db
from .dependencies import AuthenticatedAccessSession, get_authenticated_access_session
from .logout import logout_authenticated_principal
from .schemas import PrincipalLogoutResponse

router = APIRouter()
_LOGOUT_FAILURE = "Unable to log out."


@router.post("/logout", response_model=PrincipalLogoutResponse, status_code=status.HTTP_200_OK)
async def logout_principal(
    session: AuthenticatedAccessSession = Depends(get_authenticated_access_session),
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Header(default=None, alias="X-Refresh-Token"),
) -> PrincipalLogoutResponse:
    """Complete one request transaction; the orchestration owns identity validation."""
    try:
        # Authentication reads can already have autobegun this same request session.
        # Retain that transaction; never end it or start a nested unit before logout.
        if not db.in_transaction():
            await db.begin()
        await logout_authenticated_principal(
            db, access_token=session.token, claims=session.claims,
            secret=Config.SECRET_KEY, refresh_token=refresh_token,
        )
        await db.commit()
    except Exception as error:
        try:
            await db.rollback()
        except Exception:
            # Connection/rollback exceptions can contain sensitive DB parameters.
            raise HTTPException(status_code=500, detail=_LOGOUT_FAILURE) from None
        if isinstance(error, HTTPException):
            raise error from None
        raise HTTPException(status_code=500, detail=_LOGOUT_FAILURE) from None

    return PrincipalLogoutResponse(message="Logged out successfully.")


__all__ = ["router", "logout_principal"]
