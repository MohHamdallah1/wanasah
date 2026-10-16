from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.inventory_supplier_evidence import InventorySupplierEvidence
from domains.product_tracking import public_batch_number
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryCostEvent,
    InventoryLocation,
    InventoryMovement,
    InventoryMovementImpact,
    ProductBatch,
    ProductUomConversion,
    ProductVariant,
    UOM,
)
from quantity import canonical_quantity

from api.warehouse._shared import _escape_like, _warehouse_array_membership


class LedgerReadError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.context = context or {}

    @property
    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


def _scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    if not value or "=" in value:
        raise ValueError("non-canonical base64url")
    encoded = value.encode("ascii")
    decoded = base64.b64decode(
        encoded + b"=" * (-len(encoded) % 4),
        altchars=b"-_",
        validate=True,
    )
    if not hmac.compare_digest(_b64url_encode(decoded), value):
        raise ValueError("non-canonical base64url")
    return decoded


def _cursor_signature(payload: bytes) -> bytes:
    return hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()


def encode_ledger_cursor(
    created_at: datetime,
    movement_id: int,
    *,
    scope: str,
) -> str:
    payload = json.dumps(
        {
            "v": 3,
            "kind": "warehouse-ledger",
            "scope": _scope_hash(scope),
            "created_at": created_at.isoformat(),
            "id": int(movement_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{_b64url_encode(payload)}.{_b64url_encode(_cursor_signature(payload))}"


def decode_ledger_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> tuple[datetime, int]:
    try:
        payload_part, signature_part = cursor.split(".", 1)
        payload = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
        if not hmac.compare_digest(signature, _cursor_signature(payload)):
            raise ValueError("signature mismatch")
        data = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"v", "kind", "scope", "created_at", "id"}
            or data.get("v") != 3
            or data.get("kind") != "warehouse-ledger"
            or data.get("scope") != _scope_hash(expected_scope)
            or type(data.get("id")) is not int
            or data["id"] <= 0
        ):
            raise ValueError("cursor payload mismatch")
        created_at = datetime.fromisoformat(str(data["created_at"]))
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        return created_at, int(data["id"])
    except Exception as exc:
        raise LedgerReadError(
            400,
            "LEDGER_CURSOR_INVALID",
            "Invalid or mismatched Ledger cursor.",
        ) from exc


def _ledger_scope(
    *,
    company_id: int,
    location_id: int,
    search: str,
    reference_type: str,
    reference_id: str,
    limit: int,
) -> str:
    return json.dumps(
        {
            "company_id": int(company_id),
            "location_id": int(location_id),
            "search": search,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "limit": int(limit),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _apply_filters(
    stmt,
    *,
    company_id: int,
    location_id: int,
    search: str,
    reference_type: str,
    reference_id: str,
    access: BackofficeCapabilityAccess,
):
    stmt = stmt.filter(
        InventoryMovement.company_id == company_id,
        or_(
            access.allows("ledger.read", InventoryMovement.source_location_id),
            access.allows("ledger.read", InventoryMovement.destination_location_id),
        ),
        or_(
            InventoryMovement.source_location_id == location_id,
            InventoryMovement.destination_location_id == location_id,
        ),
    )
    if reference_type:
        stmt = stmt.filter(InventoryMovement.reference_type == reference_type)
    if reference_id:
        stmt = stmt.filter(InventoryMovement.reference_id == reference_id)
    if search:
        pattern = f"%{_escape_like(search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(ProductVariant.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(ProductVariant.sku, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(InventoryMovement.reference_id, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(Driver.full_name, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(InventoryMovement.notes, "")).like(pattern, escape="\\"),
            )
        )
    return stmt


async def _load_display_uoms(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: set[int],
) -> dict[int, dict[str, Any]]:
    ids = sorted(variant_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ProductUomConversion, UOM)
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == ProductUomConversion.company_id,
                    ProductVariant.id == ProductUomConversion.product_variant_id,
                ),
            )
            .join(UOM, UOM.id == ProductUomConversion.from_uom_id)
            .filter(
                ProductUomConversion.company_id == company_id,
                _warehouse_array_membership(
                    ProductUomConversion.product_variant_id,
                    ids,
                    "ledger_display_uom_variant_ids",
                ),
                ProductUomConversion.to_uom_id == ProductVariant.base_uom_id,
            )
            .order_by(ProductUomConversion.product_variant_id, ProductUomConversion.id)
        )
    ).all()
    candidates: dict[int, list[dict[str, Any]]] = {}
    for conversion, uom in rows:
        numerator = Decimal(conversion.numerator)
        denominator = Decimal(conversion.denominator)
        if numerator <= 0 or denominator <= 0:
            raise RuntimeError("Invalid product UOM conversion.")
        factor = numerator / denominator
        if factor <= 1:
            continue
        candidates.setdefault(int(conversion.product_variant_id), []).append(
            {
                "uom_id": int(uom.id),
                "uom_code": str(uom.code),
                "uom_name": str(uom.name),
                "factor_to_base": factor,
            }
        )
    return {variant_id: values[0] for variant_id, values in candidates.items() if len(values) == 1}


async def _load_snapshots(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    variant_ids: set[int],
    movement_ids: list[int],
) -> dict[int, tuple[Decimal, Decimal]]:
    if not variant_ids or not movement_ids:
        return {}
    movement_delta = (
        select(
            InventoryMovement.id.label("movement_id"),
            InventoryMovement.product_variant_id.label("product_variant_id"),
            InventoryMovement.created_at.label("created_at"),
            func.sum(
                InventoryMovementImpact.on_hand_after - InventoryMovementImpact.on_hand_before
            ).label("location_delta"),
        )
        .join(
            InventoryMovementImpact,
            and_(
                InventoryMovementImpact.company_id == InventoryMovement.company_id,
                InventoryMovementImpact.movement_id == InventoryMovement.id,
            ),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == InventoryMovementImpact.company_id,
                InventoryBalance.id == InventoryMovementImpact.inventory_balance_id,
            ),
        )
        .filter(
            InventoryMovement.company_id == company_id,
            InventoryMovement.product_variant_id.in_(sorted(variant_ids)),
            InventoryMovementImpact.company_id == company_id,
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
        )
        .group_by(
            InventoryMovement.id,
            InventoryMovement.product_variant_id,
            InventoryMovement.created_at,
        )
        .subquery("ledger_location_delta")
    )
    history = (
        select(
            movement_delta.c.movement_id,
            movement_delta.c.product_variant_id,
            movement_delta.c.location_delta,
            func.sum(movement_delta.c.location_delta)
            .over(
                partition_by=movement_delta.c.product_variant_id,
                order_by=(movement_delta.c.created_at.asc(), movement_delta.c.movement_id.asc()),
                rows=(None, 0),
            )
            .label("cumulative_delta"),
            func.sum(movement_delta.c.location_delta)
            .over(partition_by=movement_delta.c.product_variant_id)
            .label("total_delta"),
        )
        .subquery("ledger_location_history")
    )
    current = (
        select(
            InventoryBalance.product_variant_id.label("product_variant_id"),
            func.sum(InventoryBalance.on_hand_quantity).label("current_total"),
        )
        .filter(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.product_variant_id.in_(sorted(variant_ids)),
        )
        .group_by(InventoryBalance.product_variant_id)
        .subquery("ledger_current_balance")
    )
    rows = (
        await db.execute(
            select(
                history.c.movement_id,
                history.c.location_delta,
                history.c.cumulative_delta,
                history.c.total_delta,
                func.coalesce(current.c.current_total, 0).label("current_total"),
            )
            .outerjoin(current, current.c.product_variant_id == history.c.product_variant_id)
            .filter(history.c.movement_id.in_(movement_ids))
        )
    ).all()
    result: dict[int, tuple[Decimal, Decimal]] = {}
    for row in rows:
        delta = Decimal(row.location_delta or 0)
        opening = Decimal(row.current_total or 0) - Decimal(row.total_delta or 0)
        after = opening + Decimal(row.cumulative_delta or 0)
        before = after - delta
        if before < 0 or after < 0:
            raise RuntimeError("Ledger balance reconstruction became negative.")
        result[int(row.movement_id)] = (before, after)
    return result


async def read_warehouse_ledger_page(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess,
    company_id: int,
    location_id: int,
    cursor: str | None,
    limit: int,
    search: str | None,
    reference_type: str | None,
    reference_id: str | None,
) -> dict[str, Any]:
    clean_search = (search or "").strip().lower()
    clean_type = (reference_type or "").strip()
    clean_reference = (reference_id or "").strip()
    if clean_search and len(clean_search) < 2:
        raise LedgerReadError(400, "LEDGER_SEARCH_TOO_SHORT", "Ledger search requires at least two characters.")

    scope = _ledger_scope(
        company_id=company_id,
        location_id=location_id,
        search=clean_search,
        reference_type=clean_type,
        reference_id=clean_reference,
        limit=limit,
    )

    stmt = (
        select(
            InventoryMovement,
            ProductVariant.name,
            UOM,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            Driver.full_name,
        )
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id == InventoryMovement.company_id,
                ProductVariant.id == InventoryMovement.product_variant_id,
            ),
        )
        .join(UOM, UOM.id == ProductVariant.base_uom_id)
        .outerjoin(
            Driver,
            and_(
                Driver.company_id == InventoryMovement.company_id,
                Driver.id == InventoryMovement.performed_by,
            ),
        )
    )
    stmt = _apply_filters(
        stmt,
        company_id=company_id,
        location_id=location_id,
        search=clean_search,
        reference_type=clean_type,
        reference_id=clean_reference,
        access=access,
    )

    total: int | None = None
    if cursor is None:
        count_stmt = select(func.count()).select_from(
            stmt.with_only_columns(InventoryMovement.id, maintain_column_froms=True)
            .order_by(None)
            .subquery()
        )
        total = int((await db.execute(count_stmt)).scalar_one())
    else:
        cursor_created_at, cursor_id = decode_ledger_cursor(cursor, expected_scope=scope)
        stmt = stmt.filter(
            or_(
                InventoryMovement.created_at < cursor_created_at,
                and_(
                    InventoryMovement.created_at == cursor_created_at,
                    InventoryMovement.id < cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                InventoryMovement.created_at.desc(),
                InventoryMovement.id.desc(),
            ).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    available_types: list[str] = []
    if cursor is None and not clean_reference:
        type_stmt = select(InventoryMovement.reference_type).filter(
            InventoryMovement.company_id == company_id,
            or_(
                access.allows("ledger.read", InventoryMovement.source_location_id),
                access.allows("ledger.read", InventoryMovement.destination_location_id),
            ),
            or_(
                InventoryMovement.source_location_id == location_id,
                InventoryMovement.destination_location_id == location_id,
            ),
        )
        available_types = list(
            (
                await db.execute(
                    type_stmt.distinct().order_by(InventoryMovement.reference_type.asc())
                )
            ).scalars().all()
        )

    if not rows:
        return {
            "items": [],
            "next_cursor": None,
            "has_more": False,
            "total": total,
            "available_types": available_types,
        }

    movement_ids = [int(row[0].id) for row in rows]
    variant_ids = {int(row[0].product_variant_id) for row in rows}

    supplier_evidence = {
        int(item.movement_id): item
        for item in (
            await db.scalars(
                select(InventorySupplierEvidence).where(
                    InventorySupplierEvidence.company_id == company_id,
                    InventorySupplierEvidence.movement_id.in_(movement_ids),
                )
            )
        ).all()
    }
    snapshots = await _load_snapshots(
        db,
        company_id=company_id,
        location_id=location_id,
        variant_ids=variant_ids,
        movement_ids=movement_ids,
    )
    display_uoms = await _load_display_uoms(
        db,
        company_id=company_id,
        variant_ids=variant_ids,
    )

    batch_ids = sorted({int(row[0].batch_id) for row in rows if row[0].batch_id is not None})
    batch_number_by_id: dict[int, str | None] = {}
    if batch_ids:
        batch_number_by_id = {
            int(batch_id): public_batch_number(batch_number)
            for batch_id, batch_number in (
                await db.execute(
                    select(ProductBatch.id, ProductBatch.batch_number).where(
                        ProductBatch.company_id == company_id,
                        ProductBatch.id.in_(batch_ids),
                    )
                )
            ).all()
        }

    location_ids = sorted({
        int(value)
        for row in rows
        for value in (row[0].source_location_id, row[0].destination_location_id)
        if value is not None
    })
    location_name_by_id: dict[int, str] = {}
    if location_ids:
        location_name_by_id = {
            int(location_id_value): str(location_name)
            for location_id_value, location_name in (
                await db.execute(
                    select(InventoryLocation.id, InventoryLocation.name).where(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.id.in_(location_ids),
                    )
                )
            ).all()
        }

    cost_events = list(
        (
            await db.scalars(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == company_id,
                    InventoryCostEvent.inventory_movement_id.in_(movement_ids),
                )
            )
        ).all()
    )
    cost_event_by_movement = {int(event.inventory_movement_id): event for event in cost_events}
    cost_uom_ids = sorted({int(event.input_uom_id) for event in cost_events if event.input_uom_id is not None})
    cost_uom_by_id: dict[int, UOM] = {}
    if cost_uom_ids:
        cost_uom_by_id = {
            int(row.id): row
            for row in (await db.scalars(select(UOM).where(UOM.id.in_(cost_uom_ids)))).all()
        }
    currency_code = await db.scalar(select(Company.currency_code).where(Company.id == company_id))
    if not currency_code:
        raise RuntimeError("Company currency is unavailable.")

    impact_stmt = (
        select(InventoryMovementImpact, InventoryBalance)
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == InventoryMovementImpact.company_id,
                InventoryBalance.id == InventoryMovementImpact.inventory_balance_id,
            ),
        )
        .filter(
            InventoryMovementImpact.company_id == company_id,
            InventoryMovementImpact.movement_id.in_(movement_ids),
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            access.allows("ledger.read", InventoryBalance.location_id),
        )
    )
    impacts_by_movement: dict[int, list[tuple[InventoryMovementImpact, InventoryBalance]]] = {}
    for impact, balance in (await db.execute(impact_stmt)).all():
        impacts_by_movement.setdefault(int(impact.movement_id), []).append((impact, balance))

    result: list[dict[str, Any]] = []
    for movement, product_name, base_uom, quantity_scale, quantity_step, admin_name in rows:
        candidates = impacts_by_movement.get(int(movement.id), [])

        def find_impact(target_status: str | None):
            if target_status is None:
                return None
            for impact_row, balance_row in candidates:
                if balance_row.location_id == location_id and balance_row.stock_status == target_status:
                    return impact_row
            return None

        chosen = None
        if movement.movement_kind == "STATUS_CHANGE":
            chosen = find_impact("AVAILABLE")
        elif movement.source_location_id == location_id:
            chosen = find_impact(movement.source_stock_status)
        elif movement.destination_location_id == location_id:
            chosen = find_impact(movement.destination_stock_status)

        quantity_delta: Decimal | None = None
        if chosen is not None:
            if movement.movement_kind == "RESERVATION":
                before = Decimal(chosen.on_hand_before) - Decimal(chosen.reserved_before)
                after = Decimal(chosen.on_hand_after) - Decimal(chosen.reserved_after)
            else:
                before = Decimal(chosen.on_hand_before)
                after = Decimal(chosen.on_hand_after)
            quantity_delta = after - before

        if quantity_delta is None:
            quantity = Decimal(movement.quantity)
            if movement.movement_kind == "RESERVATION":
                quantity_delta = -quantity if movement.reservation_action == "RESERVE" else quantity
            elif movement.movement_kind == "STATUS_CHANGE":
                quantity_delta = -quantity if movement.source_stock_status == "AVAILABLE" else quantity
            else:
                quantity_delta = -quantity if movement.source_location_id == location_id else quantity

        created_at = movement.created_at
        if created_at is None:
            raise RuntimeError("Ledger movement is missing created_at.")
        response_created_at = (
            created_at.replace(tzinfo=timezone.utc)
            if created_at.tzinfo is None
            else created_at.astimezone(timezone.utc)
        )

        display = display_uoms.get(int(movement.product_variant_id))
        if display is None:
            display_uom_id = int(base_uom.id)
            display_uom_code = str(base_uom.code)
            display_uom_name = str(base_uom.name)
            display_factor = Decimal("1")
        else:
            display_uom_id = int(display["uom_id"])
            display_uom_code = str(display["uom_code"])
            display_uom_name = str(display["uom_name"])
            display_factor = Decimal(display["factor_to_base"])

        cost_event = cost_event_by_movement.get(int(movement.id))
        input_uom = (
            cost_uom_by_id.get(int(cost_event.input_uom_id))
            if cost_event is not None and cost_event.input_uom_id is not None
            else None
        )
        average_cost_after = None
        average_cost_uom_code = None
        average_cost_uom_name = None
        if cost_event is not None:
            cost_quantity_after = Decimal(cost_event.quantity_after)
            cost_value_after = Decimal(cost_event.value_after)
            average_base_after = Decimal("0") if cost_quantity_after == 0 else cost_value_after / cost_quantity_after
            if cost_event.input_quantity is not None and Decimal(cost_event.input_quantity) > 0 and input_uom is not None:
                event_factor = Decimal(movement.quantity) / Decimal(cost_event.input_quantity)
                average_cost_after = average_base_after * event_factor
                average_cost_uom_code = str(input_uom.code)
                average_cost_uom_name = str(input_uom.name)
            else:
                average_cost_after = average_base_after * display_factor
                average_cost_uom_code = display_uom_code
                average_cost_uom_name = display_uom_name
            average_cost_after = average_cost_after.quantize(Decimal("0.000001"))

        snapshot = snapshots.get(int(movement.id))
        supplier = supplier_evidence.get(int(movement.id))
        result.append(
            {
                "id": int(movement.id),
                "product_variant_id": int(movement.product_variant_id),
                "product_name": str(product_name),
                "base_uom_id": int(base_uom.id),
                "base_uom_code": str(base_uom.code),
                "quantity_scale": int(quantity_scale),
                "quantity_step": canonical_quantity(quantity_step),
                "type": str(movement.reference_type),
                "reference_type": str(movement.reference_type),
                "movement_kind": str(movement.movement_kind),
                "quantity": canonical_quantity(quantity_delta),
                "balance_before": snapshot[0] if snapshot else None,
                "balance_after": snapshot[1] if snapshot else None,
                "balance_scope": "PRODUCT_LOCATION" if snapshot else None,
                "batch_id": int(movement.batch_id) if movement.batch_id is not None else None,
                "batch_number": batch_number_by_id.get(int(movement.batch_id)) if movement.batch_id is not None else None,
                "source_location_id": int(movement.source_location_id) if movement.source_location_id is not None else None,
                "source_location_name": location_name_by_id.get(int(movement.source_location_id)) if movement.source_location_id is not None else None,
                "destination_location_id": int(movement.destination_location_id) if movement.destination_location_id is not None else None,
                "destination_location_name": location_name_by_id.get(int(movement.destination_location_id)) if movement.destination_location_id is not None else None,
                "source_stock_status": str(movement.source_stock_status) if movement.source_stock_status is not None else None,
                "destination_stock_status": str(movement.destination_stock_status) if movement.destination_stock_status is not None else None,
                "display_uom_id": display_uom_id,
                "display_uom_code": display_uom_code,
                "display_uom_name": display_uom_name,
                "display_factor_to_base": canonical_quantity(display_factor),
                "currency_code": str(currency_code).upper(),
                "cost_method": str(cost_event.method) if cost_event is not None else None,
                "input_quantity": canonical_quantity(cost_event.input_quantity) if cost_event is not None and cost_event.input_quantity is not None else None,
                "input_uom_code": str(input_uom.code) if input_uom is not None else None,
                "input_uom_name": str(input_uom.name) if input_uom is not None else None,
                "input_unit_cost": format(Decimal(cost_event.input_unit_cost).quantize(Decimal("0.000001")), "f") if cost_event is not None and cost_event.input_unit_cost is not None else None,
                "total_cost": format(Decimal(cost_event.total_cost).quantize(Decimal("0.000001")), "f") if cost_event is not None else None,
                "average_cost_after": format(average_cost_after, "f") if average_cost_after is not None else None,
                "average_cost_uom_code": average_cost_uom_code,
                "average_cost_uom_name": average_cost_uom_name,
                "admin_name": str(admin_name) if admin_name else "Unknown",
                "reference": str(movement.reference_id) if movement.reference_id is not None else None,
                "supplier_id": int(supplier.supplier_id) if supplier is not None and supplier.supplier_id is not None else None,
                "supplier_name": str(supplier.supplier_name) if supplier is not None and supplier.supplier_name is not None else None,
                "supplier_code": str(supplier.supplier_code) if supplier is not None and supplier.supplier_code is not None else None,
                "notes": str(movement.notes) if movement.notes is not None else None,
                "date": response_created_at.isoformat(),
            }
        )

    next_cursor = None
    if has_more:
        last = rows[-1][0]
        if last.created_at is None:
            raise RuntimeError("Ledger movement is missing created_at.")
        next_cursor = encode_ledger_cursor(last.created_at, int(last.id), scope=scope)

    return {
        "items": result,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
        "available_types": available_types,
    }
