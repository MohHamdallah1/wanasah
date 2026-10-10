"""Compatibility façade for the canonical authorization domain.

Existing imports remain stable during the identity/authorization expand phase.
New authorization internals live under ``domains.authorization``.
"""

from domains.authorization import (
    COMPANY_ONLY,
    PERMISSIONS,
    InventoryAccess,
    inventory_actor,
    require_inbound_adjustment,
    require_stocktake,
    require_transfer,
    transfer_filter,
)

__all__ = [
    "COMPANY_ONLY",
    "PERMISSIONS",
    "InventoryAccess",
    "inventory_actor",
    "require_inbound_adjustment",
    "require_stocktake",
    "require_transfer",
    "transfer_filter",
]
