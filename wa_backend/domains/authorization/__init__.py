"""Canonical company authorization primitives."""

from .capabilities import COMPANY_ONLY, PERMISSIONS
from .guards import (
    inventory_actor,
    require_inbound_adjustment,
    require_stocktake,
    require_transfer,
    transfer_filter,
)
from .inventory_access import InventoryAccess
from .subject import AuthorizationSubject, subject_from_legacy_driver

__all__ = [
    "AuthorizationSubject",
    "COMPANY_ONLY",
    "InventoryAccess",
    "PERMISSIONS",
    "inventory_actor",
    "require_inbound_adjustment",
    "require_stocktake",
    "require_transfer",
    "subject_from_legacy_driver",
    "transfer_filter",
]
