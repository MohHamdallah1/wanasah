"""Principal-wide canonical refresh-session invalidation.

This module is deliberately transaction-neutral: callers must begin and complete
an active transaction. It owns only tenant-safe principal/session invalidation;
it does not mutate auth_revision, issue tokens, log tokens, or expose HTTP.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PrincipalRefreshToken
from ..identity.channels import IdentityChannel, coerce_channel
from ..identity.repository import load_principal_by_id


class PrincipalSessionInvalidationRejected(Exception):
    """Fail-closed principal/session invalidation rejection."""


class PrincipalSessionInvalidationTransactionRequired(RuntimeError):
    """The caller must already own the transaction boundary."""


def _require_positive_id(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise PrincipalSessionInvalidationRejected
    return value


def _require_transaction(db: AsyncSession) -> None:
    if not db.in_transaction():
        raise PrincipalSessionInvalidationTransactionRequired(
            "Caller transaction required"
        )


def _coerce_optional_channel(
    channel: IdentityChannel | str | None,
) -> IdentityChannel | None:
    if channel is None:
        return None
    try:
        return coerce_channel(channel)
    except (TypeError, ValueError):
        raise PrincipalSessionInvalidationRejected from None


async def _establish_exact_tenant(db: AsyncSession, company_id: int) -> None:
    current = await db.scalar(
        text("SELECT NULLIF(current_setting('app.current_tenant', true), '')")
    )
    if current is not None:
        try:
            if int(current) != company_id:
                raise PrincipalSessionInvalidationRejected
        except (TypeError, ValueError):
            raise PrincipalSessionInvalidationRejected from None

    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(company_id)},
    )


async def revoke_principal_refresh_sessions(
    db: AsyncSession,
    *,
    company_id: int,
    principal_id: int,
    channel: IdentityChannel | str | None = None,
) -> int:
    """Revoke principal refresh sessions and disable all matching grace links.

    The principal does not need to be active. Account/security lifecycle callers
    own auth_revision changes separately and must commit/rollback this transaction.
    """
    _require_transaction(db)
    company_id = _require_positive_id(company_id)
    principal_id = _require_positive_id(principal_id)
    resolved_channel = _coerce_optional_channel(channel)

    await _establish_exact_tenant(db, company_id)

    principal = await load_principal_by_id(
        db,
        company_id=company_id,
        principal_id=principal_id,
    )
    if (
        principal is None
        or principal.id != principal_id
        or principal.company_id != company_id
    ):
        raise PrincipalSessionInvalidationRejected

    statement = select(PrincipalRefreshToken).where(
        PrincipalRefreshToken.company_id == company_id,
        PrincipalRefreshToken.principal_id == principal_id,
    )
    if resolved_channel is None:
        statement = statement.where(
            PrincipalRefreshToken.channel.in_(
                (IdentityChannel.DASHBOARD.value, IdentityChannel.FIELD.value)
            )
        )
    else:
        statement = statement.where(
            PrincipalRefreshToken.channel == resolved_channel.value
        )

    rows = list(
        (
            await db.scalars(
                statement.order_by(PrincipalRefreshToken.id).with_for_update()
            )
        ).all()
    )

    changed = 0
    for row in rows:
        if (
            row.company_id != company_id
            or row.principal_id != principal_id
            or (
                resolved_channel is not None
                and row.channel != resolved_channel.value
            )
        ):
            raise PrincipalSessionInvalidationRejected

        row_changed = False
        if not row.is_revoked:
            row.is_revoked = True
            row_changed = True
        if row.replaced_by_id is not None:
            row.replaced_by_id = None
            row_changed = True
        if row_changed:
            changed += 1

    if changed:
        await db.flush()
    return changed


__all__ = [
    "PrincipalSessionInvalidationRejected",
    "PrincipalSessionInvalidationTransactionRequired",
    "revoke_principal_refresh_sessions",
]
