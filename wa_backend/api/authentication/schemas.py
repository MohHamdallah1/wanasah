"""Explicit HTTP response contracts for canonical company-principal auth flows."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


PositiveId = Annotated[int, Field(gt=0)]
NonEmptyToken = Annotated[str, Field(min_length=1)]
CompanyCode = Annotated[str, Field(min_length=2, max_length=50)]
NonEmptyText = Annotated[str, Field(min_length=1)]


class _StrictPrincipalResponse(BaseModel):
    """Local auth response base; unexpected transport fields fail closed."""

    model_config = ConfigDict(extra="forbid")


class DashboardPrincipalLoginResponse(_StrictPrincipalResponse):
    token: NonEmptyToken
    refresh_token: NonEmptyToken
    principal_id: PositiveId
    backoffice_user_id: PositiveId
    channel: Literal["DASHBOARD"]
    is_company_owner: bool
    company_id: PositiveId
    company_code: CompanyCode
    dashboard_access: Literal[True]


class FieldPrincipalLoginResponse(_StrictPrincipalResponse):
    token: NonEmptyToken
    refresh_token: NonEmptyToken
    principal_id: PositiveId
    representative_id: PositiveId
    channel: Literal["FIELD"]
    company_id: PositiveId
    company_code: CompanyCode


class PrincipalTokenPairResponse(_StrictPrincipalResponse):
    token: NonEmptyToken
    refresh_token: NonEmptyToken


class PrincipalLogoutResponse(_StrictPrincipalResponse):
    message: NonEmptyText


__all__ = [
    "DashboardPrincipalLoginResponse",
    "FieldPrincipalLoginResponse",
    "PrincipalLogoutResponse",
    "PrincipalTokenPairResponse",
]
