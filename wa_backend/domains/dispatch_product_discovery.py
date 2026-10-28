"""Paged Dispatch product discovery with distinct load and shortage eligibility."""
from sqlalchemy import func, or_, select
from domains.dispatch_adjust_load_read import read_adjust_load_snapshot, project_adjust_load_items
from domains.dispatch_product_cursor import decode_product_cursor, encode_product_cursor
from domains.inventory_source_stock import warehouse_load_candidate_ids_statement
from models import ProductVariant
from product_lifecycle import REPLENISHMENT_NEW, product_capability_predicate
from services import get_company_local_date


DISPATCH_PRODUCT_PAGE_SIZE = 80


async def dispatch_product_page(db, *, company_id, purpose, search, cursor=None, limit=80,
                                warehouse_id=None, vehicle_id=None, vehicle_location_id=None,
                                route_id=None, work_session_id=None, driver_id=None):
    query = (search or "").strip().lower()
    eligibility = "warehouse-route-load-new-v1" if purpose == "LOAD" else "replenishment-new-v1"
    scope = dict(company=company_id, purpose=purpose, eligibility=eligibility, warehouse=warehouse_id,
                 vehicle=vehicle_id, route=route_id, session=work_session_id, search=query)
    after = decode_product_cursor(cursor, scope=scope)
    empty = dict(items=[], next_cursor=None, has_more=False)
    if not 2 <= len(query) <= 100 or "\x00" in query:
        return empty
    size = min(DISPATCH_PRODUCT_PAGE_SIZE, max(1, int(limit)))
    if purpose == "LOAD":
        stmt = warehouse_load_candidate_ids_statement(company_id=company_id, warehouse_id=warehouse_id,
            as_of_date=await get_company_local_date(db, company_id), search=query, after_id=after, order_by_id=True)
    else:
        # Shortages express replenishment demand; stock in a Warehouse is NOT required.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = select(ProductVariant.id).where(ProductVariant.company_id == company_id, ProductVariant.id > after,
            product_capability_predicate(ProductVariant, REPLENISHMENT_NEW),
            or_(func.lower(ProductVariant.name).like(pattern, escape="\\"),
                func.lower(ProductVariant.sku).like(pattern, escape="\\"))).order_by(ProductVariant.id)
    ids = list((await db.scalars(stmt.limit(size + 1))).all())
    has_more = len(ids) > size
    page_ids = ids[:size]
    if not page_ids:
        return empty
    if purpose == "LOAD":
        snapshot = await read_adjust_load_snapshot(db, company_id=company_id, vehicle_location_id=vehicle_location_id,
            work_session_id=work_session_id, driver_id=driver_id)
        rows = await project_adjust_load_items(db, company_id=company_id, product_ids=page_ids, snapshot=snapshot)
        items = [dict(id=row["product_id"], name=row["product_name"], load=row) for row in rows]
    else:
        rows = (await db.execute(select(ProductVariant.id, ProductVariant.name).where(
            ProductVariant.company_id == company_id, ProductVariant.id.in_(page_ids)).order_by(ProductVariant.id))).all()
        items = [dict(id=str(pid), name=name, load=None) for pid, name in rows]
    return dict(items=items, next_cursor=encode_product_cursor(page_ids[-1], scope=scope) if has_more else None, has_more=has_more)
