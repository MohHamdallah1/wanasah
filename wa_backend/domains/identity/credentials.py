"""Canonical company credential policy and secret-safe primitives.

This module owns password validation, hashing, and keyed fingerprints used when a
sensitive credential must participate in durable semantic identity without being
stored or logged in plaintext. It does not own login/session orchestration.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac

import bcrypt


MIN_COMPANY_PASSWORD_LENGTH = 8
MAX_COMPANY_PASSWORD_LENGTH = 72
MAX_BCRYPT_PASSWORD_BYTES = 72
_FINGERPRINT_DOMAIN = b"wanasah:identity-sensitive-fingerprint:v1\x00"
_FINGERPRINT_KEY_DOMAIN = b"wanasah:identity-sensitive-fingerprint:key:v1"


class CompanyCredentialValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_company_password(password: str) -> str:
    """Validate the canonical company password policy without mutating the secret."""
    if not isinstance(password, str):
        raise CompanyCredentialValidationError(
            "COMPANY_PASSWORD_INVALID",
            "Password must be a string.",
        )
    if len(password) < MIN_COMPANY_PASSWORD_LENGTH:
        raise CompanyCredentialValidationError(
            "COMPANY_PASSWORD_TOO_SHORT",
            "Password must contain at least 8 characters.",
        )
    if len(password) > MAX_COMPANY_PASSWORD_LENGTH:
        raise CompanyCredentialValidationError(
            "COMPANY_PASSWORD_TOO_LONG",
            "Password must contain at most 72 characters.",
        )
    if len(password.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
        raise CompanyCredentialValidationError(
            "COMPANY_PASSWORD_TOO_LONG",
            "Password exceeds the supported bcrypt byte limit.",
        )
    return password


async def hash_company_password(password: str) -> str:
    """Hash a validated company password using the established bcrypt mechanism."""
    safe_password = validate_company_password(password)
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(
            safe_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
    )


def _sensitive_fingerprint_key() -> bytes:
    """Derive a purpose-specific HMAC key from the canonical application secret."""
    from config import Config

    return hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        _FINGERPRINT_KEY_DOMAIN,
        hashlib.sha256,
    ).digest()


def sensitive_value_fingerprint(value: str, *, purpose: str) -> str:
    """Return a domain-separated keyed fingerprint for sensitive semantic identity.

    Identity owns both key derivation and HMAC construction. Callers receive only
    the opaque fingerprint; the raw value and key never leave this service.
    """
    if not isinstance(value, str):
        raise TypeError("Sensitive fingerprint value must be a string")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("Sensitive fingerprint purpose is required")

    message = (
        _FINGERPRINT_DOMAIN
        + purpose.strip().encode("utf-8")
        + b"\x00"
        + value.encode("utf-8")
    )
    return hmac.new(
        _sensitive_fingerprint_key(),
        message,
        hashlib.sha256,
    ).hexdigest()


__all__ = [
    "CompanyCredentialValidationError",
    "MAX_COMPANY_PASSWORD_LENGTH",
    "MIN_COMPANY_PASSWORD_LENGTH",
    "hash_company_password",
    "sensitive_value_fingerprint",
    "validate_company_password",
]
