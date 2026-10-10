"""Identity-neutral subject consumed by the authorization engine."""

from dataclasses import dataclass
from typing import Protocol


class LegacyDriverAuthorizationSource(Protocol):
    """Minimum legacy identity shape accepted by the compatibility adapter."""

    id: int
    company_id: int
    is_admin: bool


@dataclass(frozen=True)
class AuthorizationSubject:
    """Identity facts needed to resolve company capabilities and scope."""

    principal_id: int
    company_id: int
    legacy_full_authority: bool = False

    @property
    def actor_id(self) -> int:
        """Compatibility-neutral alias for action-attribution terminology."""
        return self.principal_id


def subject_from_legacy_driver(actor: LegacyDriverAuthorizationSource) -> AuthorizationSubject:
    """Adapt the legacy Driver-shaped principal without leaking its flag into the engine."""
    return AuthorizationSubject(
        principal_id=actor.id,
        company_id=actor.company_id,
        legacy_full_authority=bool(actor.is_admin),
    )


__all__ = [
    "AuthorizationSubject",
    "LegacyDriverAuthorizationSource",
    "subject_from_legacy_driver",
]
