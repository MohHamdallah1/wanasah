"""Canonical company authorization primitives."""

from .capabilities import COMPANY_ONLY, PERMISSIONS
from .guards import (
    require_inbound_adjustment,
    require_stocktake,
    require_transfer,
    transfer_filter,
)

__all__ = [
    "COMPANY_ONLY",
    "PERMISSIONS",
    "require_inbound_adjustment",
    "require_stocktake",
    "require_transfer",
    "transfer_filter",
]
