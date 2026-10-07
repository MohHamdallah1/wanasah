from fastapi import APIRouter

from . import (
    locations,
    inbound,
    live_stock,
    ledger,
    status,
    inbound_adjustments,
    transfer_policy,
    transfers,
    whole_product_quality_preview,
    whole_product_quality,
    stocktake,
)


router = APIRouter()

# Keep the exact runtime route registration order locked by
# scripts/warehouse_route_manifest_baseline.json plus extensions.
router.include_router(locations.router)
router.include_router(inbound.router)
router.include_router(live_stock.router)
router.include_router(ledger.router)
router.include_router(status.router)
router.include_router(inbound_adjustments.router)
router.include_router(transfer_policy.router)
router.include_router(transfers.router)
router.include_router(whole_product_quality_preview.router)
router.include_router(whole_product_quality.router)
router.include_router(stocktake.router)
