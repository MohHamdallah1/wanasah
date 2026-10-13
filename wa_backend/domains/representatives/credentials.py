from __future__ import annotations

import asyncio
import bcrypt

from .contracts import RepresentativeError


MIN_PASSWORD_LENGTH = 8
MAX_BCRYPT_PASSWORD_BYTES = 72


def validate_initial_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise RepresentativeError(
            "REPRESENTATIVE_PASSWORD_TOO_SHORT",
            "Password must contain at least 8 characters.",
            status_code=422,
        )
    if len(password.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
        raise RepresentativeError(
            "REPRESENTATIVE_PASSWORD_TOO_LONG",
            "Password exceeds the supported bcrypt byte limit.",
            status_code=422,
        )
    return password


async def hash_initial_password(password: str) -> str:
    safe_password = validate_initial_password(password)
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(
            safe_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
    )


class RepresentativeCredentialResetDecisionRequired(RuntimeError):
    pass


async def reset_representative_credentials(*args, **kwargs):
    raise RepresentativeCredentialResetDecisionRequired(
        "Credential reset is blocked until auth_revision/session-revocation semantics are frozen."
    )


__all__ = [
    "RepresentativeCredentialResetDecisionRequired",
    "hash_initial_password",
    "reset_representative_credentials",
    "validate_initial_password",
]
