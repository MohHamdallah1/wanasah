"""Canonical capability catalog for company authorization."""

PERMISSIONS = frozenset({
    'supplier.read', 'supplier.manage',
    'location.read', 'location.create', 'location.update', 'location.state',
    'inventory.read', 'inbound.create', 'ledger.read', 'ledger.adjust',
    'batch.disposition', 'inventory.status_change',
    'inventory.transfer_policy.manage', 'inventory.costing.manage',
    'catalog.read', 'catalog.manage', 'catalog.publish', 'catalog.retire',
    'catalog.restore', 'catalog.archive', 'catalog.hold',
    'product_location.read', 'product_location.manage',
    'transfer.read', 'transfer.send', 'transfer.receive', 'transfer.cancel',
    'transfer.reject', 'transfer.destination', 'inventory.fefo_override',
    'transfer.special.quarantine', 'transfer.special.recall_return',
    'transfer.special.return_to_vendor', 'transfer.special.disposal',
    'inventory.disposal.confirm',
    'inventory.vendor_return.confirm',
    'transfer.warehouse_balancing_override',
    'pricing.view', 'pricing.manage', 'pricing.approve',
    'offers.view', 'offers.manage', 'offers.approve',
    'tax.view', 'tax.manage', 'tax.approve',
    'stocktake.read', 'stocktake.start', 'stocktake.count', 'stocktake.review',
    'stocktake.approve', 'stocktake.recount', 'stocktake.cancel',
    'dispatch.read', 'dispatch.execute',
})

COMPANY_ONLY = frozenset({
    'supplier.read', 'supplier.manage',
    'location.create', 'catalog.manage', 'catalog.publish', 'catalog.retire',
    'catalog.restore', 'catalog.archive', 'catalog.hold',
    'batch.disposition', 'inventory.transfer_policy.manage', 'inventory.costing.manage',
    'transfer.special.quarantine', 'transfer.special.recall_return',
    'transfer.special.return_to_vendor', 'transfer.special.disposal',
    'transfer.warehouse_balancing_override',
    'pricing.view', 'pricing.manage', 'pricing.approve',
    'offers.view', 'offers.manage', 'offers.approve',
    'tax.view', 'tax.manage', 'tax.approve',
})

__all__ = ["COMPANY_ONLY", "PERMISSIONS"]
