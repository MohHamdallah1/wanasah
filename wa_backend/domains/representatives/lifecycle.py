from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.invalidation import (
    PrincipalSessionInvalidationRejected,
    revoke_principal_refresh_sessions,
)
from domains.identity.channels import IdentityChannel
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)

from .contracts import RepresentativeError, RepresentativeLifecycleCommand
from .lifecycle_guards import assert_representative_deactivation_safe
from .repository import (
    add_representative_audit,
    guard_representative_request_identity,
    require_operational_compatibility,
)


_DEACTIVATE_OPERATION = "REPRESENTATIVE_DEACTIVATE"
_REACTIVATE_OPERATION = "REPRESENTATIVE_REACTIVATE"


def _request_hash(operation: str, representative_id: int) -> str:
    canonical = json.dumps(
        {"operation": operation, "representative_id": int(representative_id)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_conflict(exc: InventoryMutationError) -> RepresentativeError:
    return RepresentativeError(
        "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
        "The request identity conflicts with a previous representative command.",
        status_code=409,
    )


def _session_invalidation_conflict() -> RepresentativeError:
    return RepresentativeError(
        "REPRESENTATIVE_SESSION_INVALIDATION_REJECTED",
        "Representative sessions could not be invalidated safely.",
        status_code=409,
    )


async def deactivate_representative(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    representative_id: int,
    command: RepresentativeLifecycleCommand,
) -> dict:
    request_hash = _request_hash(_DEACTIVATE_OPERATION, representative_id)
    try:
        canonical_request_id = await guard_representative_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation=_DEACTIVATE_OPERATION,
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation=_DEACTIVATE_OPERATION,
            request_id=canonical_request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        profile, principal, _bridge, legacy_driver = (
            await require_operational_compatibility(
                db,
                company_id=company_id,
                representative_id=representative_id,
            )
        )
        if not principal.is_active:
            raise RepresentativeError(
                "REPRESENTATIVE_ALREADY_INACTIVE",
                "Representative is already inactive.",
                status_code=409,
            )

        await assert_representative_deactivation_safe(
            db,
            company_id=company_id,
            legacy_driver_id=int(legacy_driver.id),
        )

        previous_revision = int(principal.auth_revision)
        principal.is_active = False
        principal.auth_revision = previous_revision + 1
        revoked_sessions = await revoke_principal_refresh_sessions(
            db,
            company_id=company_id,
            principal_id=int(principal.id),
            channel=IdentityChannel.FIELD,
        )
        await db.flush()

        add_representative_audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            representative_id=int(profile.id),
            action="REPRESENTATIVE_DEACTIVATED",
            before={
                "is_active": True,
                "auth_revision": previous_revision,
            },
            after={
                "is_active": False,
                "auth_revision": int(principal.auth_revision),
                "refresh_sessions_revoked": int(revoked_sessions),
                "request_id": canonical_request_id,
            },
        )
        response = {
            "representative_id": int(profile.id),
            "state": "INACTIVE",
            "auth_revision": int(principal.auth_revision),
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except RepresentativeError:
        await db.rollback()
        raise
    except PrincipalSessionInvalidationRejected as exc:
        await db.rollback()
        raise _session_invalidation_conflict() from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise _idempotency_conflict(exc) from exc
    except Exception:
        await db.rollback()
        raise


async def reactivate_representative(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    representative_id: int,
    command: RepresentativeLifecycleCommand,
) -> dict:
    request_hash = _request_hash(_REACTIVATE_OPERATION, representative_id)
    try:
        canonical_request_id = await guard_representative_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation=_REACTIVATE_OPERATION,
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation=_REACTIVATE_OPERATION,
            request_id=canonical_request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        profile, principal, _bridge, _legacy_driver = (
            await require_operational_compatibility(
                db,
                company_id=company_id,
                representative_id=representative_id,
            )
        )
        if principal.is_active:
            raise RepresentativeError(
                "REPRESENTATIVE_ALREADY_ACTIVE",
                "Representative is already active.",
                status_code=409,
            )

        current_revision = int(principal.auth_revision)
        principal.is_active = True
        await db.flush()
        add_representative_audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            representative_id=int(profile.id),
            action="REPRESENTATIVE_REACTIVATED",
            before={
                "is_active": False,
                "auth_revision": current_revision,
            },
            after={
                "is_active": True,
                "auth_revision": current_revision,
                "request_id": canonical_request_id,
            },
        )
        response = {
            "representative_id": int(profile.id),
            "state": "ACTIVE",
            "auth_revision": current_revision,
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except RepresentativeError:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise _idempotency_conflict(exc) from exc
    except Exception:
        await db.rollback()
        raise


__all__ = ["deactivate_representative", "reactivate_representative"]
