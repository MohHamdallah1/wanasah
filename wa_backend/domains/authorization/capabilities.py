"""Canonical capability catalog for company authorization."""

PERMISSIONS = frozenset({
    'supplier.read', 'supplier.manage',
    'representative.read', 'representative.manage', 'representative.credentials.reset',
    'vehicle.read', 'vehicle.manage',
    'location.read', 'location.create', 'location.update', 'location.state',
    'branch.read', 'branch.create', 'branch.update', 'branch.state',
    'work_session.read', 'work_session.authorize_sale', 'work_session.reopen',
    'settlement.read', 'settlement.execute',
    'shortage.read', 'shortage.create', 'shortage.cancel',
    'visit.read', 'reconciliation.execute',
    'work_session.execute', 'visit.execute', 'shop.create',
    'inventory.read', 'inbound.create', 'ledger.read', 'ledger.adjust',
    'batch.disposition', 'inventory.status_change',
    'inventory.transfer_policy.manage', 'inventory.costing.manage',
    'inventory.purchase_cost_reference.read', 'inventory.purchase_cost_reference.manage',
    'inventory.minimum_stock.manage',
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
    'sales_return.create',
})

COMPANY_ONLY = frozenset({
    'supplier.read', 'supplier.manage',
    'representative.read', 'representative.manage', 'representative.credentials.reset',
    'vehicle.read', 'vehicle.manage',
    'location.create', 'branch.read', 'branch.create', 'branch.update', 'branch.state',
    'work_session.read', 'work_session.authorize_sale', 'work_session.reopen',
    'settlement.read', 'settlement.execute',
    'shortage.read', 'shortage.create', 'shortage.cancel', 'visit.read',
    'work_session.execute', 'visit.execute', 'shop.create',
    'catalog.manage', 'catalog.publish', 'catalog.retire',
    'catalog.restore', 'catalog.archive', 'catalog.hold',
    'batch.disposition', 'inventory.transfer_policy.manage', 'inventory.costing.manage',
    'inventory.purchase_cost_reference.read', 'inventory.purchase_cost_reference.manage',
    'inventory.minimum_stock.manage',
    'transfer.special.quarantine', 'transfer.special.recall_return',
    'transfer.special.return_to_vendor', 'transfer.special.disposal',
    'transfer.warehouse_balancing_override',
    'pricing.view', 'pricing.manage', 'pricing.approve',
    'offers.view', 'offers.manage', 'offers.approve',
    'tax.view', 'tax.manage', 'tax.approve',
})

# FIELD operation grants remain separate from dynamic operational assignment scope.
FIELD_ASSIGNABLE_PERMISSIONS = frozenset({
    'work_session.read', 'work_session.execute', 'visit.read', 'visit.execute',
    'inventory.read', 'transfer.read', 'transfer.receive', 'transfer.reject',
    'catalog.read', 'pricing.view', 'reconciliation.execute', 'shop.create',
})

__all__ = ["COMPANY_ONLY", "PERMISSIONS", "FIELD_ASSIGNABLE_PERMISSIONS"]
