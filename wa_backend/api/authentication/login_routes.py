"""Unmounted canonical company-login HTTP routes for the Phase 5 cutover.

This adapter owns only request/IP extraction, HTTP error translation, dependency
wiring, and response-model declaration. Credential authentication, authorization,
token/session issuance, and transaction completion remain in orchestration.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from database import get_db
from schemas import LoginRequest

from .login_orchestration import (
    PrincipalLoginRateLimited,
    PrincipalLoginRejected,
    login_dashboard_principal,
    login_field_principal,
)
from .schemas import DashboardPrincipalLoginResponse, FieldPrincipalLoginResponse


router = APIRouter(tags=["Authentication"])

_AUTHENTICATION_FAILED = "Authentication failed."
_LOGIN_RATE_LIMITED = "Too many login attempts. Try again later."


def _request_ip(request: Request) -> str:
    """Reuse the project's hardened real-IP resolver without importing main eagerly."""
    from main import get_real_ip

    return get_real_ip(request)


@router.post("/login", response_model=DashboardPrincipalLoginResponse)
async def dashboard_principal_login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> DashboardPrincipalLoginResponse:
    try:
        return await login_dashboard_principal(
            db,
            company_code=payload.company_code,
            username=payload.username,
            password=payload.password,
            ip_address=_request_ip(request),
            secret=Config.SECRET_KEY,
        )
    except PrincipalLoginRateLimited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_LOGIN_RATE_LIMITED,
        ) from None
    except PrincipalLoginRejected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTHENTICATION_FAILED,
        ) from None


@router.post("/driver/login", response_model=FieldPrincipalLoginResponse)
async def field_principal_login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> FieldPrincipalLoginResponse:
    try:
        return await login_field_principal(
            db,
            company_code=payload.company_code,
            username=payload.username,
            password=payload.password,
            ip_address=_request_ip(request),
            secret=Config.SECRET_KEY,
        )
    except PrincipalLoginRateLimited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_LOGIN_RATE_LIMITED,
        ) from None
    except PrincipalLoginRejected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTHENTICATION_FAILED,
        ) from None


__all__ = ["router"]
