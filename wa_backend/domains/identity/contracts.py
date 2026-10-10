"""Typed authentication results that never expose credential material."""
from dataclasses import dataclass, field
from typing import TypeAlias

from .channels import IdentityChannel
from .types import PrincipalType


class AuthenticationRejected(Exception):
    """Fail-closed company identity authentication rejection.

    Deliberately carries no user-facing detail. Runtime adapters decide their own
    compatibility response without learning whether company, account, password,
    channel, or profile caused the rejection.
    """


@dataclass(frozen=True)
class DashboardAuthenticationResult:
    principal_id: int
    company_id: int
    backoffice_user_id: int
    username: str
    full_name: str
    auth_revision: int
    is_company_owner: bool
    channel: IdentityChannel = field(default=IdentityChannel.DASHBOARD, init=False)
    principal_type: PrincipalType = field(default=PrincipalType.BACKOFFICE, init=False)


@dataclass(frozen=True)
class FieldAuthenticationResult:
    principal_id: int
    company_id: int
    representative_id: int
    username: str
    full_name: str
    auth_revision: int
    channel: IdentityChannel = field(default=IdentityChannel.FIELD, init=False)
    principal_type: PrincipalType = field(default=PrincipalType.FIELD_REPRESENTATIVE, init=False)


AuthenticationResult: TypeAlias = DashboardAuthenticationResult | FieldAuthenticationResult
