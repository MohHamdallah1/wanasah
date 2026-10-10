"""Explicit company application channels for the new identity model."""
from enum import Enum

from .types import PrincipalType


class IdentityChannel(str, Enum):
    DASHBOARD = "DASHBOARD"
    FIELD = "FIELD"


_CHANNEL_PRINCIPAL_TYPE = {
    IdentityChannel.DASHBOARD: PrincipalType.BACKOFFICE,
    IdentityChannel.FIELD: PrincipalType.FIELD_REPRESENTATIVE,
}


def coerce_channel(channel: IdentityChannel | str) -> IdentityChannel:
    """Normalize only the frozen channel values; role names are never channels."""
    if isinstance(channel, IdentityChannel):
        return channel
    return IdentityChannel(channel)


def expected_principal_type(channel: IdentityChannel | str) -> PrincipalType:
    return _CHANNEL_PRINCIPAL_TYPE[coerce_channel(channel)]
