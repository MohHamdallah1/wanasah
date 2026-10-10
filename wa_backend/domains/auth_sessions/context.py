"""Persistence-backed validation for decoded company access-token claims."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from sqlalchemy.ext.asyncio import AsyncSession

from .claims import CompanyTokenClaims
from ..identity.channels import IdentityChannel, coerce_channel, expected_principal_type
from ..identity.repository import (
    IdentityRecordNotFound,
    load_company_owner,
    load_principal_by_id,
    require_active_company,
    require_backoffice_profile,
    require_field_representative_profile,
)
from ..identity.types import PrincipalType


class RequestContextRejected(Exception):
    """Internal fail-closed rejection with no check-specific detail."""


@dataclass(frozen=True)
class DashboardRequestContext:
    principal_id: int
    company_id: int
    backoffice_user_id: int
    auth_revision: int
    is_company_owner: bool
    channel: IdentityChannel = field(default=IdentityChannel.DASHBOARD, init=False)
    principal_type: PrincipalType = field(default=PrincipalType.BACKOFFICE, init=False)


@dataclass(frozen=True)
class FieldRequestContext:
    principal_id: int
    company_id: int
    representative_id: int
    auth_revision: int
    channel: IdentityChannel = field(default=IdentityChannel.FIELD, init=False)
    principal_type: PrincipalType = field(
        default=PrincipalType.FIELD_REPRESENTATIVE, init=False
    )


AuthenticatedRequestContext: TypeAlias = DashboardRequestContext | FieldRequestContext


def _reject() -> None:
    raise RequestContextRejected


def _validated_claim_identity(
    claims: CompanyTokenClaims,
) -> tuple[IdentityChannel, PrincipalType]:
    if claims.token_type != "access":
        _reject()

    try:
        channel = coerce_channel(claims.channel)
    except (TypeError, ValueError):
        _reject()
        raise AssertionError("unreachable")

    expected_type = expected_principal_type(channel)
    if claims.principal_type != expected_type.value:
        _reject()
    return channel, expected_type


async def _require_persisted_identity(
    db: AsyncSession,
    *,
    claims: CompanyTokenClaims,
    expected_type: PrincipalType,
) -> None:
    try:
        await require_active_company(db, claims.company_id)
    except IdentityRecordNotFound:
        _reject()

    principal = await load_principal_by_id(
        db,
        company_id=claims.company_id,
        principal_id=claims.principal_id,
    )
    if principal is None or not principal.is_active:
        _reject()
    if principal.company_id != claims.company_id or principal.id != claims.principal_id:
        _reject()
    if principal.auth_revision != claims.auth_revision:
        _reject()
    if principal.principal_type != claims.principal_type:
        _reject()
    if principal.principal_type != expected_type.value:
        _reject()


async def _dashboard_context(
    db: AsyncSession,
    *,
    claims: CompanyTokenClaims,
) -> DashboardRequestContext:
    try:
        profile = await require_backoffice_profile(
            db,
            company_id=claims.company_id,
            principal_id=claims.principal_id,
        )
    except IdentityRecordNotFound:
        _reject()

    if (
        profile.company_id != claims.company_id
        or profile.principal_id != claims.principal_id
        or profile.principal_type != PrincipalType.BACKOFFICE.value
    ):
        _reject()

    owner = await load_company_owner(db, company_id=claims.company_id)
    if owner is not None and owner.company_id != claims.company_id:
        _reject()

    return DashboardRequestContext(
        principal_id=claims.principal_id,
        company_id=claims.company_id,
        backoffice_user_id=profile.id,
        auth_revision=claims.auth_revision,
        is_company_owner=(
            owner is not None and owner.backoffice_user_id == profile.id
        ),
    )


async def _field_context(
    db: AsyncSession,
    *,
    claims: CompanyTokenClaims,
) -> FieldRequestContext:
    try:
        profile = await require_field_representative_profile(
            db,
            company_id=claims.company_id,
            principal_id=claims.principal_id,
        )
    except IdentityRecordNotFound:
        _reject()

    if (
        profile.company_id != claims.company_id
        or profile.principal_id != claims.principal_id
        or profile.principal_type != PrincipalType.FIELD_REPRESENTATIVE.value
    ):
        _reject()

    return FieldRequestContext(
        principal_id=claims.principal_id,
        company_id=claims.company_id,
        representative_id=profile.id,
        auth_revision=claims.auth_revision,
    )


async def resolve_access_context(
    db: AsyncSession,
    claims: CompanyTokenClaims,
) -> AuthenticatedRequestContext:
    """Resolve decoded access claims against current persisted identity state."""
    channel, expected_type = _validated_claim_identity(claims)
    await _require_persisted_identity(
        db,
        claims=claims,
        expected_type=expected_type,
    )

    if channel is IdentityChannel.DASHBOARD:
        return await _dashboard_context(db, claims=claims)
    if channel is IdentityChannel.FIELD:
        return await _field_context(db, claims=claims)
    _reject()
    raise AssertionError("unreachable")


__all__ = [
    "AuthenticatedRequestContext",
    "DashboardRequestContext",
    "FieldRequestContext",
    "RequestContextRejected",
    "resolve_access_context",
]
