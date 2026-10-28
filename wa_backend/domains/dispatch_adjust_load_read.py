"""Sparse current custody and bounded Warehouse search for route Adjust Load."""
from decimal import Decimal
from sqlalchemy import select
from domains.dispatch_route_load import route_vehicle_base_totals, route_load_uom_metadata
from domains.dispatch_load_plan import pending_handshake_base_net
from domains.inventory_source_stock import warehouse_load_candidate_ids_statement
from models import ProductVariant
from services import get_company_local_date


ADJUST_LOAD_SEARCH_LIMIT = 80


async def read_adjust_load_inventory(db, *, company_id, route, vehicle_location_id, search=None, product_ids=None, limit=80):
    totals = await route_vehicle_base_totals(
        db, company_id=company_id, location_id=vehicle_location_id, all_statuses=True,
    )
    legacy_totals = await route_vehicle_base_totals(
        db, company_id=company_id, location_id=vehicle_location_id,
    )
    pending = await pending_handshake_base_net(
        db, company_id=company_id, work_session_id=route.work_session_id,
        driver_id=route.driver_id, vehicle_location_id=vehicle_location_id,
    ) if route.work_session_id is not None else {}
    loaded_ids = set(totals) | set(pending)
    if search is None and product_ids is None:
        selected_ids = loaded_ids
    else:
        clean_search = (search or "").strip().lower()
        if search is not None and (not 2 <= len(clean_search) <= 100 or "\x00" in clean_search):
            return []
        requested = set(product_ids or [])
        if product_ids is not None and (not requested or len(product_ids) > ADJUST_LOAD_SEARCH_LIMIT or any(type(pid) is not int or pid <= 0 for pid in requested)):
            return []
        stmt = warehouse_load_candidate_ids_statement(
            company_id=company_id, warehouse_id=route.source_location_id,
            as_of_date=await get_company_local_date(db, company_id),
            search=clean_search, product_ids=requested if product_ids is not None else None,
        )
        # Limit in SQL, BEFORE materializing Products or their UOM conversion graphs.
        cap = min(ADJUST_LOAD_SEARCH_LIMIT, max(1, int(limit)))
        candidates = (await db.scalars(stmt.limit(cap))).all()
        selected_ids = set(candidates)
        if product_ids is not None:
            selected_ids |= loaded_ids & requested
    if not selected_ids:
        return []
    variants = (await db.scalars(select(ProductVariant).where(
        ProductVariant.company_id == company_id, ProductVariant.id.in_(sorted(selected_ids)),
    ).order_by(ProductVariant.id))).all()
    metadata = await route_load_uom_metadata(db, company_id=company_id, variant_ids=[variant.id for variant in variants])
    result = []
    for variant in variants:
        ppc = int(variant.packs_per_carton or 0)
        on_hand, reserved = totals.get(int(variant.id), (Decimal(0), Decimal(0)))
        # Compatibility display only; neither field drives the canonical path.
        legacy_on_hand, legacy_reserved = legacy_totals.get(int(variant.id), (Decimal(0), Decimal(0)))
        free = max(Decimal(0), legacy_on_hand - legacy_reserved)
        cartons, loose = (int(free // ppc), int(free % ppc)) if ppc > 0 else (0, 0)
        result.append({
            "product_id": str(variant.id),
            "product_name": variant.variant_name,
            "current_cartons": cartons,
            "current_packs": loose,
            "current_base_quantity": on_hand,
            "reserved_base_quantity": reserved,
            "pending_base_quantity": pending.get(int(variant.id), Decimal(0)),
            **metadata[int(variant.id)],
        })
    return result
