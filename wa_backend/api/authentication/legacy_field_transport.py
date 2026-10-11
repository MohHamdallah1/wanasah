"""Temporary bridge from authenticated legacy transport to canonical Field identity."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.auth_sessions.context import FieldRequestContext
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.types import PrincipalType
from models import Driver

from .dependencies import _authentication_rejected


class _LegacyFieldIdentityRejected(Exception):
    """Internal mapping rejection with no identity or storage detail."""


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


async def _resolve_legacy_field_context(
    db: AsyncSession, current_driver: Driver,
) -> FieldRequestContext:
    company_id, legacy_driver_id = current_driver.company_id, current_driver.id
    if not all(_positive_id(value) for value in (company_id, legacy_driver_id)):
        raise _LegacyFieldIdentityRejected

    result = await db.execute(
        select(
            IdentityLegacyDriverMap.company_id,
            IdentityLegacyDriverMap.legacy_driver_id,
            IdentityLegacyDriverMap.field_principal_id,
            IdentityLegacyDriverMap.field_representative_id,
        ).where(
            IdentityLegacyDriverMap.company_id == company_id,
            IdentityLegacyDriverMap.legacy_driver_id == legacy_driver_id,
        )
    )
    bridge = result.one_or_none()
    if bridge is None:
        raise _LegacyFieldIdentityRejected
    bridge_ids = (
        bridge.company_id, bridge.legacy_driver_id,
        bridge.field_principal_id, bridge.field_representative_id,
    )
    if (
        not all(_positive_id(value) for value in bridge_ids)
        or bridge_ids[:2] != (company_id, legacy_driver_id)
    ):
        raise _LegacyFieldIdentityRejected

    field_type = PrincipalType.FIELD_REPRESENTATIVE.value
    result = await db.execute(
        select(
            FieldRepresentative.company_id.label("representative_company_id"),
            FieldRepresentative.id.label("representative_id"),
            FieldRepresentative.principal_id.label("representative_principal_id"),
            FieldRepresentative.principal_type.label("representative_type"),
            CompanyPrincipal.company_id.label("principal_company_id"),
            CompanyPrincipal.id.label("principal_id"),
            CompanyPrincipal.principal_type.label("principal_type"),
            CompanyPrincipal.is_active.label("principal_active"),
            CompanyPrincipal.auth_revision.label("auth_revision"),
        )
        .select_from(FieldRepresentative)
        .join(CompanyPrincipal, and_(
            CompanyPrincipal.company_id == FieldRepresentative.company_id,
            CompanyPrincipal.id == FieldRepresentative.principal_id,
        ))
        .where(
            FieldRepresentative.company_id == company_id,
            FieldRepresentative.id == bridge.field_representative_id,
            FieldRepresentative.principal_id == bridge.field_principal_id,
            FieldRepresentative.principal_type == field_type,
            CompanyPrincipal.company_id == company_id,
            CompanyPrincipal.id == bridge.field_principal_id,
            CompanyPrincipal.principal_type == field_type,
            CompanyPrincipal.is_active.is_(True),
        )
    )
    identity = result.one_or_none()
    if identity is None:
        raise _LegacyFieldIdentityRejected
    profile_ids = (
        identity.representative_company_id, identity.representative_id,
        identity.representative_principal_id,
    )
    principal_ids = (identity.principal_company_id, identity.principal_id)
    if (
        not all(_positive_id(value) for value in (*profile_ids, *principal_ids, identity.auth_revision))
        or profile_ids != (company_id, bridge.field_representative_id, bridge.field_principal_id)
        or principal_ids != (company_id, bridge.field_principal_id)
        or identity.representative_type != field_type
        or identity.principal_type != field_type
        or identity.principal_active is not True
    ):
        raise _LegacyFieldIdentityRejected

    return FieldRequestContext(
        principal_id=identity.principal_id,
        representative_id=identity.representative_id,
        company_id=identity.principal_company_id,
        auth_revision=identity.auth_revision,
    )


async def get_legacy_transport_field_context(
    current_driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> FieldRequestContext:
    """Map the cached upstream transport actor without authenticating it again.

    Exact canonical linkage owns Field identity semantics. The upstream
    dependency retains transport authentication and tenant establishment;
    the caller retains transaction ownership. Remove at final transport cutover.
    """
    try:
        return await _resolve_legacy_field_context(db, current_driver)
    except Exception:
        raise _authentication_rejected() from None


__all__ = ["get_legacy_transport_field_context"]
