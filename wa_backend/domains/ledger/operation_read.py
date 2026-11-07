"""Read-only operation view over immutable warehouse Ledger movements.

A group is established ONLY by a persisted authority:
  transfer_header_id, stocktake_session_id, or supplier receipt evidence.request_id.
All other movements are single-movement groups. Display reference text is NEVER
a document identifier. The old /warehouse/ledger/cursor remains unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, case, cast, distinct, func, literal, or_, select, false
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.warehouse._shared import _escape_like
from config import Config
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.inventory_supplier_evidence import InventorySupplierEvidence
from domains.ledger.read import LedgerReadError, _render_ledger_entries
from models import Driver, InventoryLocation, InventoryMovement, ProductVariant, UOM

_MAX_ID = 2**63 - 1
_KINDS = {"TRANSFER", "STOCKTAKE", "RECEIPT", "MOVEMENT"}


def _visible(m, *, access: BackofficeCapabilityAccess, company_id: int,
             location_id: int, watermark: int | None = None):
    predicates = [
        m.company_id == company_id,
        or_(m.source_location_id == location_id, m.destination_location_id == location_id),
        or_(access.allows("ledger.read", m.source_location_id),
            access.allows("ledger.read", m.destination_location_id)),
    ]
    if watermark is not None:
        predicates.append(m.id <= watermark)
    return and_(*predicates)


def _evidence_join(m, evidence):
    return and_(evidence.company_id == m.company_id,
                evidence.movement_id == m.id)


def _identity(m, evidence):
    receipt = and_(
        m.transfer_header_id.is_(None),
        m.stocktake_session_id.is_(None),
        m.reference_type == "INBOUND_SUPPLIER",
        evidence.request_id.is_not(None),
    )
    kind = case(
        (m.transfer_header_id.is_not(None), literal("TRANSFER")),
        (m.stocktake_session_id.is_not(None), literal("STOCKTAKE")),
        (receipt, literal("RECEIPT")),
        else_=literal("MOVEMENT"),
    )
    identity = case(
        (m.transfer_header_id.is_not(None), cast(m.transfer_header_id, String)),
        (m.stocktake_session_id.is_not(None), cast(m.stocktake_session_id, String)),
        (receipt, cast(evidence.request_id, String)),
        else_=cast(m.id, String),
    )
    return kind, identity


def _same_document(m, evidence, other, other_evidence):
    """Index-narrowable comparisons; never combine equal human references."""
    return or_(
        and_(m.transfer_header_id.is_not(None),
             other.transfer_header_id == m.transfer_header_id),
        and_(m.transfer_header_id.is_(None),
             m.stocktake_session_id.is_not(None),
             other.transfer_header_id.is_(None),
             other.stocktake_session_id == m.stocktake_session_id),
        and_(m.transfer_header_id.is_(None),
             m.stocktake_session_id.is_(None),
             m.reference_type == "INBOUND_SUPPLIER",
             evidence.request_id.is_not(None),
             other.transfer_header_id.is_(None),
             other.stocktake_session_id.is_(None),
             other.reference_type == "INBOUND_SUPPLIER",
             # Indexed reference narrows candidates, but the persisted UUID
             # (not this reference) is the authoritative identity.
             other.reference_id == m.reference_id,
             other_evidence.request_id == evidence.request_id),
    )


def _document_filter(m, evidence, *, kind: str, document_id: str,
                     reference: str | None = None):
    if kind == "TRANSFER":
        return m.transfer_header_id == int(document_id)
    if kind == "STOCKTAKE":
        return and_(m.transfer_header_id.is_(None),
                    m.stocktake_session_id == int(document_id))
    if kind == "RECEIPT":
        return and_(
            m.transfer_header_id.is_(None),
            m.stocktake_session_id.is_(None),
            m.reference_type == "INBOUND_SUPPLIER",
            m.reference_id == reference,  # indexed accelerator only
            evidence.request_id == UUID(document_id),
        )
    if kind == "MOVEMENT":
        return and_(m.id == int(document_id),
                    m.transfer_header_id.is_(None),
                    m.stocktake_session_id.is_(None),
                    or_(m.reference_type != "INBOUND_SUPPLIER",
                        evidence.request_id.is_(None)))
    raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid operation identity.")


def _matching(m, variant, actor, *, search: str, movement_type: str,
              reference_id: str):
    match = []
    if movement_type:
        match.append(m.reference_type == movement_type)
    if reference_id:
        match.append(m.reference_id == reference_id)
    if search:
        pattern = "%" + _escape_like(search) + "%"
        match.append(or_(
            func.lower(variant.name).like(pattern, escape="\\"),
            func.lower(func.coalesce(variant.sku, "")).like(pattern, escape="\\"),
            func.lower(m.reference_id).like(pattern, escape="\\"),
            func.lower(func.coalesce(actor.full_name, "")).like(pattern, escape="\\"),
            func.lower(func.coalesce(m.notes, "")).like(pattern, escape="\\"),
        ))
    return and_(*match) if match else literal(True)


def _utc_stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _scope(*, company_id: int, location_id: int, search: str,
           movement_type: str, reference_id: str, limit: int | None = None) -> str:
    data = {"company": company_id, "warehouse": location_id, "search": search,
            "movement_type": movement_type, "reference_id": reference_id}
    if limit is not None:
        data["limit"] = limit
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sign(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    mac = hmac.new(Config.SECRET_KEY.encode(), payload, hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return body + "." + signature


def _verify(token: str, *, kind: str, scope: str) -> dict[str, Any]:
    try:
        if len(token) > 512 or token.count(".") != 1:
            raise ValueError("length")
        body, signature = token.split(".")
        if not body or "=" in body or "=" in signature:
            raise ValueError("bad base64url")
        payload = base64.b64decode(body + "=" * (-len(body) % 4),
                                   altchars=b"-_", validate=True)
        mac = base64.b64decode(signature + "=" * (-len(signature) % 4),
                               altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(payload).decode().rstrip("=") != body:
            raise ValueError("noncanonical payload")
        if base64.urlsafe_b64encode(mac).decode().rstrip("=") != signature:
            raise ValueError("noncanonical MAC")
        expected = hmac.new(Config.SECRET_KEY.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("signature")
        doc = json.loads(payload.decode())
        if (not isinstance(doc, dict) or doc.get("v") != 1
                or doc.get("k") != kind or doc.get("s") != scope):
            raise ValueError("scope")
        return doc
    except Exception as exc:
        raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID",
                              "Invalid or cross-scope operation token.") from exc


def _int_from_token(value: Any) -> int:
    if type(value) is not int or not 0 < value <= _MAX_ID:
        raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid operation cursor ID.")
    return value


def _position(doc: dict[str, Any]):
    movement_id = _int_from_token(doc.get("i"))
    try:
        ts = datetime.fromisoformat(doc["t"])
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception as exc:
        raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID",
                              "Invalid operation cursor timestamp.") from exc
    return ts, movement_id


def _earlier(m, ts: datetime, movement_id: int):
    return or_(m.created_at < ts,
               and_(m.created_at == ts, m.id < movement_id))


def _later(m, other):
    return or_(other.created_at > m.created_at,
               and_(other.created_at == m.created_at, other.id > m.id))


def _clean(search: str | None, movement_type: str | None, reference_id: str | None):
    clean_search = (search or "").strip().lower()
    if clean_search and len(clean_search) < 2:
        raise LedgerReadError(400, "LEDGER_SEARCH_TOO_SHORT",
                              "Ledger search requires at least two characters.")
    return clean_search, (movement_type or "").strip(), (reference_id or "").strip()


async def read_operation_groups(
    db: AsyncSession, *, access: BackofficeCapabilityAccess, company_id: int,
    location_id: int, cursor: str | None, limit: int,
    search: str | None, movement_type: str | None, reference_id: str | None,
) -> dict[str, Any]:
    search, movement_type, reference_id = _clean(search, movement_type, reference_id)
    page_scope = _scope(company_id=company_id, location_id=location_id,
                        search=search, movement_type=movement_type,
                        reference_id=reference_id, limit=limit)
    token_scope = _scope(company_id=company_id, location_id=location_id,
                         search=search, movement_type=movement_type,
                         reference_id=reference_id)
    position = None
    if cursor:
        data = _verify(cursor, kind="op-page", scope=page_scope)
        if set(data) != {"v", "k", "s", "h", "t", "i"}:
            raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid group cursor fields.")
        watermark = _int_from_token(data["h"])
        position = _position(data)
    else:
        watermark = await db.scalar(select(func.max(InventoryMovement.id)).where(
            _visible(InventoryMovement, access=access, company_id=company_id,
                     location_id=location_id)))
        if watermark is None:
            return {"items": [], "next_cursor": None, "has_more": False,
                    "snapshot_max_movement_id": None, "type_filter_semantics": "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED"}
        watermark = int(watermark)

    m, e = InventoryMovement, aliased(InventorySupplierEvidence)
    newer, newer_e = aliased(InventoryMovement), aliased(InventorySupplierEvidence)
    # Indexed high-watermarked anti-existence checks: only the newest authorized
    # movement for an operation qualifies as a parent row. A group spanning
    # previous raw pages therefore cannot reappear as a second parent.
    newer_exists = select(literal(1)).select_from(newer).outerjoin(
        newer_e, _evidence_join(newer, newer_e)
    ).where(
        _visible(newer, access=access, company_id=company_id,
                 location_id=location_id, watermark=watermark),
        _same_document(m, e, newer, newer_e),
        _later(m, newer),
    ).correlate(m, e).exists()

    stmt = select(m, e.request_id).select_from(m).outerjoin(
        e, _evidence_join(m, e)
    ).where(
        _visible(m, access=access, company_id=company_id,
                 location_id=location_id, watermark=watermark),
        ~newer_exists,
    )
    if search or movement_type or reference_id:
        child, child_e = aliased(InventoryMovement), aliased(InventorySupplierEvidence)
        variant, actor = aliased(ProductVariant), aliased(Driver)
        match_exists = select(literal(1)).select_from(child).outerjoin(
            child_e, _evidence_join(child, child_e)
        ).join(variant, and_(variant.company_id == child.company_id,
                             variant.id == child.product_variant_id)).outerjoin(
            actor, and_(actor.company_id == child.company_id,
                        actor.id == child.performed_by)
        ).where(
            _visible(child, access=access, company_id=company_id,
                     location_id=location_id, watermark=watermark),
            or_(child.id == m.id, _same_document(m, e, child, child_e)),
            _matching(child, variant, actor, search=search,
                      movement_type=movement_type, reference_id=reference_id),
        ).correlate(m, e).exists()
        stmt = stmt.where(match_exists)
    if position is not None:
        stmt = stmt.where(_earlier(m, *position))
    rows = (await db.execute(
        stmt.order_by(m.created_at.desc(), m.id.desc()).limit(limit + 1)
    )).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return {"items": [], "next_cursor": None, "has_more": False,
                "snapshot_max_movement_id": watermark,
                "type_filter_semantics": "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED"}

    # All counts are computed in ONE bounded group aggregation, never one SQL
    # query per group. Receipt references are indexed accelerators only.
    keys = []
    for movement, request_uuid in rows:
        if movement.transfer_header_id is not None:
            kind, doc_id = "TRANSFER", str(movement.transfer_header_id)
        elif movement.stocktake_session_id is not None:
            kind, doc_id = "STOCKTAKE", str(movement.stocktake_session_id)
        elif movement.reference_type == "INBOUND_SUPPLIER" and request_uuid is not None:
            kind, doc_id = "RECEIPT", str(request_uuid)
        else:
            kind, doc_id = "MOVEMENT", str(movement.id)
        keys.append((kind, doc_id, movement))

    transfer_ids = [int(k[1]) for k in keys if k[0] == "TRANSFER"]
    stocktake_ids = [int(k[1]) for k in keys if k[0] == "STOCKTAKE"]
    receipt_ids = [UUID(k[1]) for k in keys if k[0] == "RECEIPT"]
    receipt_refs = [k[2].reference_id for k in keys if k[0] == "RECEIPT"]
    fallback_ids = [int(k[1]) for k in keys if k[0] == "MOVEMENT"]
    conditions = []
    if transfer_ids:
        conditions.append(m.transfer_header_id.in_(transfer_ids))
    if stocktake_ids:
        conditions.append(and_(m.transfer_header_id.is_(None),
                               m.stocktake_session_id.in_(stocktake_ids)))
    if receipt_ids:
        conditions.append(and_(m.transfer_header_id.is_(None),
                               m.stocktake_session_id.is_(None),
                               m.reference_type == "INBOUND_SUPPLIER",
                               m.reference_id.in_(receipt_refs),
                               e.request_id.in_(receipt_ids)))
    if fallback_ids:
        conditions.append(m.id.in_(fallback_ids))
    group_kind, group_doc = _identity(m, e)
    stat = select(
        group_kind.label("kind"), group_doc.label("document_id"),
        func.count(m.id).label("movement_count"),
        func.count(distinct(m.product_variant_id)).label("variant_count"),
        func.count(distinct(m.batch_id)).label("batch_count"),
        func.array_agg(distinct(m.reference_type)).label("stages"),
        func.array_agg(distinct(m.movement_kind)).label("movement_kinds"),
    ).select_from(m).outerjoin(
        e, _evidence_join(m, e)
    ).where(
        _visible(m, access=access, company_id=company_id,
                 location_id=location_id, watermark=watermark),
        or_(*conditions),
    ).group_by(group_kind, group_doc)
    stats = {(r.kind, r.document_id): r for r in (await db.execute(stat)).all()}

    actors = [int(row[2].performed_by) for row in keys]
    actor_names = dict((await db.execute(
        select(Driver.id, Driver.full_name).where(
            Driver.company_id == company_id, Driver.id.in_(actors))
    )).all())
    locations = sorted({int(v) for _, _, row in keys
                        for v in (row.source_location_id, row.destination_location_id)
                        if v is not None})
    # The source/target location name is shown only with ledger.read permission.
    permitted_locations = dict((await db.execute(select(
        InventoryLocation.id, InventoryLocation.name
    ).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id.in_(locations),
        access.allows("ledger.read", InventoryLocation.id),
    ))).all()) if locations else {}

    result = []
    for kind, doc_id, movement in keys:
        stat_row = stats.get((kind, doc_id))
        if stat_row is None:
            raise RuntimeError("Ledger operation lost an authorized summary.")
        token_data = {"v": 1, "k": "op-key", "s": token_scope, "g": kind,
                      "d": doc_id, "h": watermark}
        if kind == "RECEIPT":
            token_data["r"] = movement.reference_id
        token = _sign(token_data)
        if len(token) > 512:
            raise RuntimeError("Operation token exceeded bounded contract.")
        result.append({
            "group_key": token, "group_kind": kind,
            "operation_type": ("INBOUND_SUPPLIER" if kind == "RECEIPT"
                               else "AUDIT_ADJUSTMENT" if kind == "STOCKTAKE"
                               else "WAREHOUSE_TRANSFER" if kind == "TRANSFER"
                               else movement.reference_type),
            # Latest authorized stage/reference, NOT an asserted completion.
            "reference": movement.reference_id,
            "latest_at": _utc_stamp(movement.created_at),
            "latest_movement_id": int(movement.id),
            "source_location_name": permitted_locations.get(movement.source_location_id),
            "destination_location_name": permitted_locations.get(movement.destination_location_id),
            "latest_actor_name": actor_names.get(movement.performed_by),
            "stage_types": sorted(stat_row.stages),
            "movement_kinds": sorted(stat_row.movement_kinds),
            "movement_count": int(stat_row.movement_count),
            "product_variant_count": int(stat_row.variant_count),
            "batch_count": int(stat_row.batch_count),
            "expandable": True,
            "count_meaning": "POSTED_VARIANCE_MOVEMENTS" if kind == "STOCKTAKE"
                             else "AUTHORIZED_IMMUTABLE_MOVEMENTS",
            "stocktake_history": (
                {"session_id": int(doc_id), "warehouse_location_id": location_id,
                 "reference": movement.reference_id}
                if kind == "STOCKTAKE" else None
            ),
        })
    next_cursor = None
    if has_more:
        last = rows[-1][0]
        next_cursor = _sign({"v": 1, "k": "op-page", "s": page_scope,
                             "h": watermark, "t": _utc_stamp(last.created_at),
                             "i": int(last.id)})
    return {"items": result, "next_cursor": next_cursor, "has_more": has_more,
            "snapshot_max_movement_id": watermark,
            "type_filter_semantics": "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED"}


async def read_operation_movements(
    db: AsyncSession, *, access: BackofficeCapabilityAccess, company_id: int,
    location_id: int, group_token: str, cursor: str | None, limit: int,
    search: str | None, movement_type: str | None, reference_id: str | None,
) -> dict[str, Any]:
    search, movement_type, reference_id = _clean(search, movement_type, reference_id)
    token_scope = _scope(company_id=company_id, location_id=location_id,
                         search=search, movement_type=movement_type,
                         reference_id=reference_id)
    data = _verify(group_token, kind="op-key", scope=token_scope)
    if (set(data) not in ({"v", "k", "s", "g", "d", "h"},
                          {"v", "k", "s", "g", "d", "h", "r"})
            or data.get("g") not in _KINDS or type(data.get("d")) is not str):
        raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid operation key.")
    kind, document_id, watermark = data["g"], data["d"], _int_from_token(data["h"])
    reference = data.get("r")
    if kind == "RECEIPT":
        try:
            UUID(document_id)
        except Exception as exc:
            raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID",
                                  "Invalid supplier receipt token.") from exc
        if not isinstance(reference, str) or not reference or len(reference) > 100:
            raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid receipt reference.")
    else:
        if reference is not None:
            raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid document fields.")
        try:
            if not 0 < int(document_id) <= _MAX_ID or str(int(document_id)) != document_id:
                raise ValueError
        except Exception as exc:
            raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid document identifier.") from exc

    child_scope = hashlib.sha256(
        (group_token + "|" + str(limit)).encode()
    ).hexdigest()
    position = None
    if cursor:
        item = _verify(cursor, kind="op-child", scope=child_scope)
        if set(item) != {"v", "k", "s", "t", "i"}:
            raise LedgerReadError(400, "LEDGER_OPERATION_TOKEN_INVALID", "Invalid detail cursor.")
        position = _position(item)
    m, e = InventoryMovement, aliased(InventorySupplierEvidence)
    variant, actor = ProductVariant, aliased(Driver)
    from sqlalchemy import and_ as sql_and
    query = select(
        m, variant.name, UOM, variant.quantity_scale, variant.quantity_step,
        actor.full_name,
        _matching(m, variant, actor, search=search,
                  movement_type=movement_type, reference_id=reference_id).label("matches_filter"),
    ).select_from(m).outerjoin(
        e, _evidence_join(m, e)
    ).join(
        variant, sql_and(variant.company_id == m.company_id,
                         variant.id == m.product_variant_id)
    ).join(UOM, UOM.id == variant.base_uom_id).outerjoin(
        actor, sql_and(actor.company_id == m.company_id,
                       actor.id == m.performed_by)
    ).where(
        _visible(m, access=access, company_id=company_id,
                 location_id=location_id, watermark=watermark),
        _document_filter(m, e, kind=kind, document_id=document_id,
                         reference=reference),
    )
    if position is not None:
        query = query.where(_earlier(m, *position))
    rows = (await db.execute(
        query.order_by(m.created_at.desc(), m.id.desc()).limit(limit + 1)
    )).all()
    if not rows and cursor is None:
        # A once-admitted token is not a bypass of current RLS/warehouse grants.
        raise LedgerReadError(404, "LEDGER_OPERATION_NOT_FOUND",
                              "Operation is not visible in the selected warehouse.")
    has_more = len(rows) > limit
    rows = rows[:limit]
    entries = await _render_ledger_entries(
        db, access=access, company_id=company_id, location_id=location_id,
        rows=[tuple(row)[:6] for row in rows],
    ) if rows else []
    for entry, raw in zip(entries, rows):
        entry["matches_filter"] = bool(raw[6])
    next_cursor = None
    if has_more:
        last = rows[-1][0]
        next_cursor = _sign({"v": 1, "k": "op-child", "s": child_scope,
                             "t": _utc_stamp(last.created_at), "i": int(last.id)})
    return {"items": entries, "next_cursor": next_cursor, "has_more": has_more,
            "group_key": group_token}
