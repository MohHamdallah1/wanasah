"""Sparse current custody and bounded Warehouse search for route Adjust Load."""
from decimal import Decimal
from sqlalchemy import select
from domains.dispatch_route_load import route_vehicle_base_totals, route_load_uom_metadata
from domains.dispatch_load_plan import pending_handshake_base_net
from domains.inventory_source_stock import warehouse_load_candidate_ids_statement
from models import ProductVariant
from services import get_company_local_date


ADJUST_LOAD_HYDRATION_BATCH_SIZE = 80


async def read_adjust_load_snapshot(db, *, company_id, vehicle_location_id, work_session_id=None, driver_id=None):
    totals = await route_vehicle_base_totals(
        db, company_id=company_id, location_id=vehicle_location_id, all_statuses=True,
    )
    legacy_totals = await route_vehicle_base_totals(
        db, company_id=company_id, location_id=vehicle_location_id,
    )
    pending = await pending_handshake_base_net(
        db, company_id=company_id, work_session_id=work_session_id,
        driver_id=driver_id, vehicle_location_id=vehicle_location_id,
    ) if work_session_id is not None else {}
    return totals, legacy_totals, pending


async def project_adjust_load_items(db, *, company_id, product_ids, snapshot):
    totals, legacy_totals, pending = snapshot
    if not product_ids:
        return []
    variants = (await db.scalars(select(ProductVariant).where(
        ProductVariant.company_id == company_id, ProductVariant.id.in_(sorted(product_ids)),
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


async def read_adjust_load_inventory(db, *, company_id, route, vehicle_location_id, product_ids=None):
    snapshot = await read_adjust_load_snapshot(db, company_id=company_id, vehicle_location_id=vehicle_location_id,
        work_session_id=route.work_session_id, driver_id=route.driver_id)
    totals, _, pending = snapshot
    loaded_ids = set(totals) | set(pending)
    selected_ids = loaded_ids
    if product_ids is not None:
        requested = set(product_ids)
        if not requested or len(product_ids) > ADJUST_LOAD_HYDRATION_BATCH_SIZE or any(type(pid) is not int or pid <= 0 for pid in requested):
            return []
        stmt = warehouse_load_candidate_ids_statement(company_id=company_id, warehouse_id=route.source_location_id,
            as_of_date=await get_company_local_date(db, company_id), search="", product_ids=requested)
        selected_ids = set((await db.scalars(stmt.limit(ADJUST_LOAD_HYDRATION_BATCH_SIZE))).all()) | (loaded_ids & requested)
    return await project_adjust_load_items(db, company_id=company_id, product_ids=selected_ids, snapshot=snapshot)
