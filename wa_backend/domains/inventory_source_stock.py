"""Shared read authority for eligible Warehouse stock offered to load workflows."""
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased
from domains.inventory_rules import batch_sellability_predicate
from models import InventoryBalance, InventoryLock, InventoryStockPolicy, ProductBatch, ProductLocation, ProductVariant, UOM
from product_lifecycle import ROUTE_LOAD_NEW, product_capability_predicate


def warehouse_load_stock_statement(*, company_id: int, warehouse_id: int, as_of_date):
    """Reuse ProductLocation, lifecycle, batch, free-stock and inventory-lock authority."""
    available = func.sum(InventoryBalance.on_hand_quantity - InventoryBalance.reserved_quantity)
    active_lock = (
        select(InventoryLock.id)
        .where(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == int(warehouse_id),
            InventoryLock.released_at.is_(None),
            or_(
                InventoryLock.product_variant_id.is_(None),
                and_(
                    InventoryLock.product_variant_id == InventoryBalance.product_variant_id,
                    or_(InventoryLock.batch_id.is_(None), InventoryLock.batch_id == InventoryBalance.batch_id),
                ),
            ),
        )
        .correlate(InventoryBalance)
        .exists()
    )
    sellable = batch_sellability_predicate(
        as_of_date,
        expiry_control_mode=ProductVariant.expiry_control_mode,
        minimum_remaining_shelf_life_days=InventoryStockPolicy.minimum_remaining_shelf_life_days,
    )
    stmt = (
        select(
            ProductVariant.id,
            ProductVariant.name,
            ProductVariant.sku,
            ProductVariant.base_uom_id,
            UOM.code,
            UOM.name.label("uom_name"),
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            available.label("available_quantity"),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == ProductVariant.company_id,
                InventoryBalance.product_variant_id == ProductVariant.id,
            ),
        )
        .join(
            ProductBatch,
            and_(
                ProductBatch.company_id == InventoryBalance.company_id,
                ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                ProductBatch.id == InventoryBalance.batch_id,
            ),
        )
        .join(UOM, UOM.id == ProductVariant.base_uom_id)
        .join(
            ProductLocation,
            and_(
                ProductLocation.company_id == ProductVariant.company_id,
                ProductLocation.location_id == int(warehouse_id),
                ProductLocation.product_variant_id == ProductVariant.id,
            ),
        )
        .outerjoin(
            InventoryStockPolicy,
            and_(
                InventoryStockPolicy.company_id == ProductVariant.company_id,
                InventoryStockPolicy.location_id == int(warehouse_id),
                InventoryStockPolicy.product_variant_id == ProductVariant.id,
                InventoryStockPolicy.is_active.is_(True),
            ),
        )
        .where(
            ProductVariant.company_id == company_id,
            product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW),
            ProductLocation.operational_flags["outbound_enabled"].as_boolean().is_(True),
            InventoryBalance.location_id == int(warehouse_id),
            InventoryBalance.stock_status == "AVAILABLE",
            sellable,
            ~active_lock,
        )
        .group_by(
            ProductVariant.id,
            ProductVariant.name,
            ProductVariant.sku,
            ProductVariant.base_uom_id,
            UOM.code,
            UOM.name,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
        )
        .having(available > 0)
    )
    return stmt


def with_warehouse_product_search(stmt, clean_search: str):
    if clean_search:
        escaped = clean_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                func.lower(ProductVariant.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(ProductVariant.sku, "")).like(pattern, escape="\\"),
            )
        )
    return stmt


def warehouse_load_candidate_ids_statement(*, company_id, warehouse_id, as_of_date, search, product_ids=None):
    """Seek products in name/ID order; test shared stock eligibility per candidate.

    The correlated aggregate checks one SKU, so LIMIT can stop after the requested
    matches rather than sorting/aggregating every stocked SKU in the Warehouse.
    """
    # Keep ordering BEFORE the correlated eligibility check. Without this stream
    # boundary a stale-statistics plan can evaluate the check for the entire
    # catalog before a top-level sort, even though the response has a LIMIT.
    ordered = with_warehouse_product_search(
        select(ProductVariant.id, ProductVariant.name, ProductVariant.company_id).where(ProductVariant.company_id == company_id), search,
    )
    if product_ids is not None:
        ordered = ordered.where(ProductVariant.id.in_(product_ids))
    ordered = ordered.order_by(ProductVariant.name, ProductVariant.id).offset(0).subquery("ordered_load_products")
    candidate = aliased(ProductVariant, ordered)
    eligible = warehouse_load_stock_statement(
        company_id=company_id, warehouse_id=warehouse_id, as_of_date=as_of_date,
    ).with_only_columns(ProductVariant.id, maintain_column_froms=True).where(
        ProductVariant.id == candidate.id,
    ).correlate(candidate).exists()
    stmt = select(candidate.id).where(candidate.company_id == company_id, eligible)
    return stmt.order_by(candidate.name, candidate.id)
