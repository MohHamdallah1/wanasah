"""Canonical field identity with a temporary locator for legacy workflow rows."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.context import FieldRequestContext
from domains.identity.migration.models import IdentityLegacyDriverMap


class FieldAuthorizationSubjectRejected(Exception):
    """Fail-closed subject resolution error with no transport semantics."""


@dataclass(frozen=True)
class FieldAuthorizationSubject:
    principal_id: int
    representative_id: int
    company_id: int
    legacy_driver_id: int


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


async def resolve_field_authorization_subject(
    db: AsyncSession,
    context: FieldRequestContext,
) -> FieldAuthorizationSubject:
    """Resolve one exact bridge for an already trusted field request context.

    All identity IDs are independent. The legacy ID is only a temporary locator
    for workflows/FKs awaiting migration; it grants no authority. The caller
    retains tenant establishment, authentication and transaction ownership.
    """
    if not isinstance(context, FieldRequestContext):
        raise FieldAuthorizationSubjectRejected
    expected = (context.company_id, context.principal_id, context.representative_id)
    if not all(_positive_id(value) for value in expected):
        raise FieldAuthorizationSubjectRejected

    result = await db.execute(
        select(
            IdentityLegacyDriverMap.company_id,
            IdentityLegacyDriverMap.field_principal_id,
            IdentityLegacyDriverMap.field_representative_id,
            IdentityLegacyDriverMap.legacy_driver_id,
        ).where(
            IdentityLegacyDriverMap.company_id == context.company_id,
            IdentityLegacyDriverMap.field_principal_id == context.principal_id,
            IdentityLegacyDriverMap.field_representative_id == context.representative_id,
        )
    )
    try:
        bridge = result.one_or_none()
    except MultipleResultsFound:
        raise FieldAuthorizationSubjectRejected from None
    if bridge is None:
        raise FieldAuthorizationSubjectRejected

    actual = (
        bridge.company_id,
        bridge.field_principal_id,
        bridge.field_representative_id,
    )
    if not all(_positive_id(value) for value in actual) or actual != expected:
        raise FieldAuthorizationSubjectRejected
    if not _positive_id(bridge.legacy_driver_id):
        raise FieldAuthorizationSubjectRejected

    return FieldAuthorizationSubject(
        principal_id=context.principal_id,
        representative_id=context.representative_id,
        company_id=context.company_id,
        legacy_driver_id=bridge.legacy_driver_id,
    )


__all__ = [
    "FieldAuthorizationSubject",
    "FieldAuthorizationSubjectRejected",
    "resolve_field_authorization_subject",
]
