from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.invalidation import (
    PrincipalSessionInvalidationRejected,
    revoke_principal_refresh_sessions,
)
from domains.identity.channels import IdentityChannel
from domains.identity.credentials import (
    CompanyCredentialValidationError,
    hash_company_password,
    sensitive_value_fingerprint,
    validate_company_password,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)

from .contracts import RepresentativeError, ResetRepresentativeCredentialsCommand
from .repository import (
    add_representative_audit,
    guard_representative_request_identity,
    load_management_row,
)


_CREATE_PASSWORD_FINGERPRINT_PURPOSE = "representative-create-password"
_RESET_PASSWORD_FINGERPRINT_PURPOSE = "representative-reset-password"
_RESET_OPERATION = "REPRESENTATIVE_CREDENTIAL_RESET"


def _map_credential_error(exc: CompanyCredentialValidationError) -> RepresentativeError:
    return RepresentativeError(
        f"REPRESENTATIVE_{exc.code}",
        exc.message,
        status_code=422,
    )


def validate_initial_password(password: str) -> str:
    """Delegate password policy to canonical Identity credential infrastructure."""
    try:
        return validate_company_password(password)
    except CompanyCredentialValidationError as exc:
        raise _map_credential_error(exc) from None


async def hash_initial_password(password: str) -> str:
    """Delegate canonical password hashing to Identity."""
    try:
        return await hash_company_password(password)
    except CompanyCredentialValidationError as exc:
        raise _map_credential_error(exc) from None


def fingerprint_initial_password(password: str) -> str:
    """Delegate secret-keyed idempotency fingerprinting fully to Identity."""
    safe_password = validate_initial_password(password)
    return sensitive_value_fingerprint(
        safe_password,
        purpose=_CREATE_PASSWORD_FINGERPRINT_PURPOSE,
    )


def fingerprint_reset_password(password: str) -> str:
    """Return a secret-safe semantic fingerprint for reset idempotency."""
    safe_password = validate_initial_password(password)
    return sensitive_value_fingerprint(
        safe_password,
        purpose=_RESET_PASSWORD_FINGERPRINT_PURPOSE,
    )


async def _hash_reset_password(password: str) -> str:
    try:
        return await hash_company_password(password)
    except CompanyCredentialValidationError as exc:
        raise _map_credential_error(exc) from None


def _reset_request_hash(
    representative_id: int,
    *,
    password_fingerprint: str,
) -> str:
    canonical = json.dumps(
        {
            "operation": _RESET_OPERATION,
            "representative_id": int(representative_id),
            "password_fingerprint": password_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def reset_representative_credentials(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    representative_id: int,
    command: ResetRepresentativeCredentialsCommand,
) -> dict:
    password_fingerprint = fingerprint_reset_password(command.new_password)
    request_hash = _reset_request_hash(
        representative_id,
        password_fingerprint=password_fingerprint,
    )
    try:
        canonical_request_id = await guard_representative_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation=_RESET_OPERATION,
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation=_RESET_OPERATION,
            request_id=canonical_request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        profile, principal, _bridge, _legacy_driver = await load_management_row(
            db,
            company_id=company_id,
            representative_id=representative_id,
            for_update=True,
        )

        password_hash = await _hash_reset_password(command.new_password)
        previous_revision = int(principal.auth_revision)
        principal.password_hash = password_hash
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
            action="REPRESENTATIVE_CREDENTIALS_RESET",
            before={"auth_revision": previous_revision},
            after={
                "auth_revision": int(principal.auth_revision),
                "refresh_sessions_revoked": int(revoked_sessions),
                "request_id": canonical_request_id,
            },
        )
        response = {
            "representative_id": int(profile.id),
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
        raise RepresentativeError(
            "REPRESENTATIVE_SESSION_INVALIDATION_REJECTED",
            "Representative sessions could not be invalidated safely.",
            status_code=409,
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise RepresentativeError(
            "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous representative command.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


__all__ = [
    "fingerprint_initial_password",
    "fingerprint_reset_password",
    "hash_initial_password",
    "reset_representative_credentials",
    "validate_initial_password",
]
