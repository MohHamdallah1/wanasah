"""Canonical company JWT claim contract for identity cutover."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

TokenType = Literal["access", "refresh"]
Channel = Literal["DASHBOARD", "FIELD"]
PrincipalType = Literal["BACKOFFICE", "FIELD_REPRESENTATIVE"]

_CHANNEL_PRINCIPAL_TYPE: dict[str, str] = {
    "DASHBOARD": "BACKOFFICE",
    "FIELD": "FIELD_REPRESENTATIVE",
}


class TokenContractError(ValueError):
    """Raised when a signed company token violates the canonical claim contract."""


def validate_channel_principal_pair(channel: str, principal_type: str) -> None:
    expected = _CHANNEL_PRINCIPAL_TYPE.get(channel)
    if expected is None or principal_type != expected:
        raise TokenContractError("Invalid company token channel/principal_type pairing")


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise TokenContractError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise TokenContractError(f"{field} must be a positive integer") from None
    if parsed <= 0:
        raise TokenContractError(f"{field} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class CompanyTokenClaims:
    """Trusted structure only; authorization is always resolved from persisted state."""

    token_type: TokenType
    principal_id: int
    company_id: int
    channel: Channel
    principal_type: PrincipalType
    auth_revision: int
    jti: str
    exp: int

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_type: TokenType | None = None,
    ) -> "CompanyTokenClaims":
        token_type = payload.get("type")
        if token_type not in {"access", "refresh"}:
            raise TokenContractError("Invalid company token type")
        if expected_type is not None and token_type != expected_type:
            raise TokenContractError("Unexpected company token type")

        channel = payload.get("channel")
        principal_type = payload.get("principal_type")
        if not isinstance(channel, str) or not isinstance(principal_type, str):
            raise TokenContractError("Missing company token channel/principal type")
        validate_channel_principal_pair(channel, principal_type)

        jti = payload.get("jti")
        if not isinstance(jti, str) or not jti.strip():
            raise TokenContractError("Missing company token jti")

        return cls(
            token_type=token_type,
            principal_id=_positive_int(payload.get("sub"), field="sub"),
            company_id=_positive_int(payload.get("company_id"), field="company_id"),
            channel=channel,
            principal_type=principal_type,
            auth_revision=_positive_int(
                payload.get("auth_revision"), field="auth_revision"
            ),
            jti=jti,
            exp=_positive_int(payload.get("exp"), field="exp"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.token_type,
            "sub": str(self.principal_id),
            "company_id": self.company_id,
            "channel": self.channel,
            "principal_type": self.principal_type,
            "auth_revision": self.auth_revision,
            "jti": self.jti,
            "exp": self.exp,
        }


__all__ = [
    "Channel",
    "CompanyTokenClaims",
    "PrincipalType",
    "TokenContractError",
    "TokenType",
    "validate_channel_principal_pair",
]
