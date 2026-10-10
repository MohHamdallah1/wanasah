"""Unmounted canonical HTTP route adapter for principal refresh rotation.

The refresh boundary owns transaction completion and token-pair construction.
This adapter owns only HTTP request wiring; runtime behavior is unchanged until
its router is explicitly mounted during the Phase 5 cutover.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from database import get_db

from .refresh import refresh_principal_session
from .schemas import PrincipalTokenPairResponse


router = APIRouter(tags=["Authentication"])


class PrincipalRefreshRequest(BaseModel):
    refresh_token: str


@router.post(
    "/refresh",
    status_code=200,
    response_model=PrincipalTokenPairResponse,
)
async def refresh_principal_access(
    payload: PrincipalRefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> PrincipalTokenPairResponse:
    """Delegate canonical refresh rotation without duplicating auth logic."""
    return await refresh_principal_session(
        db,
        refresh_token=payload.refresh_token,
        secret=Config.SECRET_KEY,
    )


__all__ = ["PrincipalRefreshRequest", "refresh_principal_access", "router"]
