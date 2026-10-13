from __future__ import annotations

from domains.identity.credentials import (
    CompanyCredentialValidationError,
    hash_company_password,
    sensitive_value_fingerprint,
    validate_company_password,
)

from .contracts import RepresentativeError


_CREATE_PASSWORD_FINGERPRINT_PURPOSE = "representative-create-password"


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


class RepresentativeCredentialResetDecisionRequired(RuntimeError):
    pass


async def reset_representative_credentials(*args, **kwargs):
    raise RepresentativeCredentialResetDecisionRequired(
        "Credential reset remains blocked until the lifecycle/integration worker freezes reset semantics."
    )


__all__ = [
    "RepresentativeCredentialResetDecisionRequired",
    "fingerprint_initial_password",
    "hash_initial_password",
    "reset_representative_credentials",
    "validate_initial_password",
]
