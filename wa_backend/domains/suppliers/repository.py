"""Bounded tenant-scoped queries; no live supplier data leaks into Inventory."""
import base64
import hashlib
import json
from datetime import timezone
from sqlalchemy import select
from .models import Supplier
from .errors import fail


def supplier_view(row):
    def iso(value):
        return value.replace(tzinfo=timezone.utc).isoformat()
    return {"id": row.id, **{field: getattr(row, field) for field in (
        "name", "code", "contact_person", "phone", "email", "address", "notes",
        "is_active", "version")}, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


async def load_supplier(db, company_id, supplier_id, *, lock=False):
    stmt = select(Supplier).where(Supplier.company_id == company_id, Supplier.id == supplier_id)
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt.execution_options(populate_existing=True))
    if row is None:
        fail(404, "SUPPLIER_NOT_FOUND", "Supplier is unavailable in this company.")
    return row


async def list_suppliers(db, company_id, *, search, active, cursor, limit):
    search = (search or "").strip().lower()
    scope = hashlib.sha256(json.dumps([company_id, search, active]).encode()).hexdigest()
    stmt = select(Supplier).where(Supplier.company_id == company_id)
    if active is not None:
        stmt = stmt.where(Supplier.is_active.is_(active))
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Supplier.search_text.like(f"%{escaped}%", escape="\\"))
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if data["scope"] != scope or type(data["id"]) is not int or data["id"] <= 0:
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            fail(400, "SUPPLIER_CURSOR_INVALID", "Search cursor does not match this query.")
        stmt = stmt.where(Supplier.id < data["id"])
    rows = list((await db.scalars(stmt.order_by(Supplier.id.desc()).limit(limit + 1))).all())
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if more:
        next_cursor = base64.urlsafe_b64encode(json.dumps({"scope": scope, "id": rows[-1].id}).encode()).decode().rstrip("=")
    return {"items": [supplier_view(row) for row in rows], "next_cursor": next_cursor, "has_more": more}
