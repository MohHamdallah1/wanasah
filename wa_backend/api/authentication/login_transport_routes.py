"""Stable public login URLs with the explicitly bounded client transport fields."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from database import get_db
from schemas import LoginRequest

from .login_orchestration import (
    PrincipalLoginRateLimited, PrincipalLoginRejected,
    login_dashboard_principal, login_field_principal,
)
from .login_routes import _request_ip, _AUTHENTICATION_FAILED, _LOGIN_RATE_LIMITED
from .login_transport import (
    DashboardLoginTransportResponse, FieldLoginTransportResponse,
    prepare_dashboard_transport, prepare_field_transport,
)


router = APIRouter(tags=["Authentication"])


@router.post("/login", response_model=DashboardLoginTransportResponse)
async def dashboard_login(
    request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db),
) -> DashboardLoginTransportResponse:
    try:
        return await login_dashboard_principal(
            db, company_code=payload.company_code, username=payload.username,
            password=payload.password, ip_address=_request_ip(request),
            secret=Config.SECRET_KEY, prepare_response=prepare_dashboard_transport,
        )
    except PrincipalLoginRateLimited:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=_LOGIN_RATE_LIMITED) from None
    except PrincipalLoginRejected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_AUTHENTICATION_FAILED) from None


@router.post("/driver/login", response_model=FieldLoginTransportResponse)
async def field_login(
    request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db),
) -> FieldLoginTransportResponse:
    try:
        return await login_field_principal(
            db, company_code=payload.company_code, username=payload.username,
            password=payload.password, ip_address=_request_ip(request),
            secret=Config.SECRET_KEY, prepare_response=prepare_field_transport,
        )
    except PrincipalLoginRateLimited:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=_LOGIN_RATE_LIMITED) from None
    except PrincipalLoginRejected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_AUTHENTICATION_FAILED) from None
