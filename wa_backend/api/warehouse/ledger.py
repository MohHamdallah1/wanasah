from datetime import timezone, datetime
from decimal import Decimal
import base64
import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryCostEvent,
    InventoryMovement,
    InventoryMovementImpact,
    ProductBatch,
    ProductUomConversion,
    ProductVariant,
    UOM,
)
from quantity import canonical_quantity
from schemas import WarehouseLedgerCursorPage

from ._shared import _escape_like, _warehouse_array_membership


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


# =================================================================================
# 4. جلب سجل حركات المستودع (Ledger) - InventoryMovement هو المصدر الوحيد
# =================================================================================
# إنشاء بصمة ثابتة لنطاق Cursor الخاص بسجل الحركات.
def _ledger_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


# ترميز Cursor سجل الحركات وربطه بنطاق البحث والفلاتر الحالية.
def _encode_ledger_cursor(
    created_at: datetime,
    movement_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 2,
            "kind": "warehouse-ledger",
            "scope": _ledger_cursor_scope_hash(scope),
            "created_at": created_at.isoformat(),
            "id": int(movement_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# فك Cursor سجل الحركات والتحقق من مطابقته لنطاق البحث الحالي.
def _decode_ledger_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> tuple[datetime, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 2
            or payload.get("kind") != "warehouse-ledger"
            or payload.get("scope")
            != _ledger_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        movement_id = payload.get("id")
        if type(movement_id) is not int or movement_id <= 0:
            raise ValueError

        created_at = datetime.fromisoformat(str(payload.get("created_at")))
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

        return created_at, movement_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor سجل الحركات غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc



# تحميل وحدة العرض التجارية الدقيقة للمنتجات الظاهرة في سجل الحركات.
async def _load_inventory_display_uoms(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int] | set[int],
) -> dict[int, dict]:
    ids = sorted({int(value) for value in variant_ids})
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
                ProductUomConversion.company_id == int(company_id),
                _warehouse_array_membership(
                    ProductUomConversion.product_variant_id,
                    ids,
                    "inventory_display_uom_variant_ids",
                ),
                ProductUomConversion.to_uom_id == ProductVariant.base_uom_id,
            )
            .order_by(
                ProductUomConversion.product_variant_id.asc(),
                ProductUomConversion.id.asc(),
            )
        )
    ).all()

    candidates: dict[int, list[dict]] = {}
    for conversion, uom in rows:
        numerator = Decimal(conversion.numerator)
        denominator = Decimal(conversion.denominator)
        if numerator <= 0 or denominator <= 0:
            raise RuntimeError("Invalid product UOM conversion.")
        factor = numerator / denominator
        if factor <= 1:
            continue
        candidates.setdefault(int(conversion.product_variant_id), []).append({
            "uom_id": int(uom.id),
            "uom_code": str(uom.code),
            "uom_name": str(uom.name),
            "factor_to_base": factor,
        })

    # Never guess between multiple commercial units.  One exact direct conversion
    # is safe to use as the default display; otherwise the caller falls back to base.
    return {
        variant_id: rows[0]
        for variant_id, rows in candidates.items()
        if len(rows) == 1
    }


# إعادة بناء رصيد المنتج في الموقع قبل وبعد كل حركة ضمن صفحة السجل.
async def _ledger_product_location_snapshots(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_ids: list[int] | set[int],
    movement_ids: list[int],
) -> dict[int, tuple[Decimal, Decimal]]:
    variant_ids = sorted({int(value) for value in product_variant_ids})
    page_movement_ids = sorted({int(value) for value in movement_ids})
    if not variant_ids or not page_movement_ids:
        return {}

    movement_delta_subq = (
        select(
            InventoryMovement.id.label("movement_id"),
            InventoryMovement.product_variant_id.label("product_variant_id"),
            InventoryMovement.created_at.label("created_at"),
            func.sum(
                InventoryMovementImpact.on_hand_after
                - InventoryMovementImpact.on_hand_before
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
            InventoryMovement.company_id == int(company_id),
            InventoryMovement.product_variant_id.in_(variant_ids),
            InventoryMovementImpact.company_id == int(company_id),
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.location_id == int(location_id),
        )
        .group_by(
            InventoryMovement.id,
            InventoryMovement.product_variant_id,
            InventoryMovement.created_at,
        )
        .subquery()
    )

    history_subq = (
        select(
            movement_delta_subq.c.movement_id,
            movement_delta_subq.c.product_variant_id,
            movement_delta_subq.c.location_delta,
            func.sum(movement_delta_subq.c.location_delta)
            .over(
                partition_by=movement_delta_subq.c.product_variant_id,
                order_by=(
                    movement_delta_subq.c.created_at.asc(),
                    movement_delta_subq.c.movement_id.asc(),
                ),
                rows=(None, 0),
            )
            .label("cumulative_delta"),
            func.sum(movement_delta_subq.c.location_delta)
            .over(partition_by=movement_delta_subq.c.product_variant_id)
            .label("total_delta"),
        )
        .subquery()
    )

    current_balance_subq = (
        select(
            InventoryBalance.product_variant_id.label("product_variant_id"),
            func.sum(InventoryBalance.on_hand_quantity).label("current_total"),
        )
        .filter(
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.location_id == int(location_id),
            InventoryBalance.product_variant_id.in_(variant_ids),
        )
        .group_by(InventoryBalance.product_variant_id)
        .subquery()
    )

    snapshot_rows = (
        await db.execute(
            select(
                history_subq.c.movement_id,
                history_subq.c.location_delta,
                history_subq.c.cumulative_delta,
                history_subq.c.total_delta,
                func.coalesce(current_balance_subq.c.current_total, 0).label(
                    "current_total"
                ),
            )
            .outerjoin(
                current_balance_subq,
                current_balance_subq.c.product_variant_id
                == history_subq.c.product_variant_id,
            )
            .filter(history_subq.c.movement_id.in_(page_movement_ids))
        )
    ).all()

    result: dict[int, tuple[Decimal, Decimal]] = {}
    for row in snapshot_rows:
        delta = Decimal(row.location_delta or 0)
        cumulative = Decimal(row.cumulative_delta or 0)
        total_delta = Decimal(row.total_delta or 0)
        current_total = Decimal(row.current_total or 0)
        opening_total = current_total - total_delta
        after = opening_total + cumulative
        before = after - delta
        if before < 0 or after < 0:
            raise RuntimeError(
                "Ledger product/location balance reconstruction became negative."
            )
        result[int(row.movement_id)] = (before, after)
    return result


# Legacy list ledger endpoint removed after Dashboard cursor migration.
# Cursor API لسجل الحركات؛ الـCursor مربوط بالـTenant والفلاتر الحالية.
@router.get(
    "/warehouse/ledger/cursor",
    response_model=WarehouseLedgerCursorPage,
    status_code=200,
)
async def get_warehouse_ledger_cursor(
    location_id: Optional[int] = None,
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    reference_type: Optional[str] = Query(default=None, max_length=50),
    reference_id: Optional[str] = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('ledger.read', location_id, any_location=location_id is None)

    company_id = current_admin.company_id

    clean_search = (search or "").strip().lower()
    clean_type = (reference_type or "").strip()
    clean_reference = (reference_id or "").strip()

    if clean_search and len(clean_search) < 2:
        raise HTTPException(
            status_code=400,
            detail="البحث في السجل يتطلب حرفين على الأقل.",
        )

    ledger_scope = (
        f"ledger|{company_id}|{location_id or 0}|"
        f"{clean_search}|{clean_type}|{clean_reference}"
    )

    try:
        if location_id is not None:
            stmt_location = select(InventoryLocation.id).filter_by(
                id=location_id,
                company_id=company_id,
                location_type='WAREHOUSE',
            )
            if (await db.execute(stmt_location)).scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=404,
                    detail="المستودع غير موجود أو لا يتبع شركتك.",
                )

        stmt = select(
            InventoryMovement,
            ProductVariant.name,
            UOM,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            Driver.full_name,
        ).join(
            ProductVariant,
            and_(
                ProductVariant.company_id == InventoryMovement.company_id,
                ProductVariant.id == InventoryMovement.product_variant_id,
            ),
        ).join(UOM, UOM.id == ProductVariant.base_uom_id).join(
            Driver,
            and_(
                Driver.company_id == InventoryMovement.company_id,
                Driver.id == InventoryMovement.performed_by,
            ),
        ).filter(
            InventoryMovement.company_id == company_id,
            or_(access.allows('ledger.read', InventoryMovement.source_location_id),
                access.allows('ledger.read', InventoryMovement.destination_location_id)),
        )

        if location_id is not None:
            stmt = stmt.filter(
                or_(
                    InventoryMovement.source_location_id == location_id,
                    InventoryMovement.destination_location_id == location_id,
                )
            )

        if clean_type:
            stmt = stmt.filter(
                InventoryMovement.reference_type == clean_type,
            )

        if clean_reference:
            stmt = stmt.filter(
                InventoryMovement.reference_id == clean_reference
            )

        if clean_search:
            like_pattern = f"%{_escape_like(clean_search)}%"
            stmt = stmt.filter(
                or_(
                    func.lower(ProductVariant.name).like(
                        like_pattern, escape="\\"
                    ),
                    func.lower(InventoryMovement.reference_id).like(
                        like_pattern, escape="\\"
                    ),
                    func.lower(Driver.full_name).like(
                        like_pattern, escape="\\"
                    ),
                    func.lower(
                        func.coalesce(InventoryMovement.notes, "")
                    ).like(
                        like_pattern, escape="\\"
                    ),
                )
            )

        total = None
        if cursor is None:
            count_stmt = select(func.count()).select_from(
                stmt.with_only_columns(
                    InventoryMovement.id,
                    maintain_column_froms=True,
                ).order_by(None).subquery()
            )
            total = int((await db.execute(count_stmt)).scalar_one())

        if cursor is not None:
            cursor_created_at, cursor_id = _decode_ledger_cursor(
                cursor,
                expected_scope=ledger_scope,
            )
            stmt = stmt.filter(
                or_(
                    InventoryMovement.created_at < cursor_created_at,
                    and_(
                        InventoryMovement.created_at == cursor_created_at,
                        InventoryMovement.id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(
            InventoryMovement.created_at.desc(),
            InventoryMovement.id.desc(),
        ).limit(limit + 1)

        rows = (await db.execute(stmt)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        available_types: list[str] = []
        if cursor is None and reference_id is None:
            type_stmt = select(
                InventoryMovement.reference_type
            ).filter(
                InventoryMovement.company_id == company_id,
            or_(access.allows('ledger.read', InventoryMovement.source_location_id),
                access.allows('ledger.read', InventoryMovement.destination_location_id)),
            )

            if location_id is not None:
                type_stmt = type_stmt.filter(
                    or_(
                        InventoryMovement.source_location_id == location_id,
                        InventoryMovement.destination_location_id == location_id,
                    )
                )

            available_types = list(
                (
                    await db.execute(
                        type_stmt.distinct().order_by(
                            InventoryMovement.reference_type.asc()
                        )
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

        movement_ids = [row[0].id for row in rows]
        page_variant_ids = sorted({int(row[0].product_variant_id) for row in rows})

        aggregate_snapshots = (
            await _ledger_product_location_snapshots(
                db,
                company_id=company_id,
                location_id=location_id,
                product_variant_ids=page_variant_ids,
                movement_ids=movement_ids,
            )
            if location_id is not None
            else {}
        )
        display_uoms = await _load_inventory_display_uoms(
            db,
            company_id=company_id,
            variant_ids=page_variant_ids,
        )

        batch_ids = sorted({
            int(row[0].batch_id)
            for row in rows
            if row[0].batch_id is not None
        })
        batch_number_by_id: dict[int, str] = {}
        if batch_ids:
            batch_number_by_id = {
                int(batch_id): str(batch_number)
                for batch_id, batch_number in (
                    await db.execute(
                        select(ProductBatch.id, ProductBatch.batch_number).filter(
                            ProductBatch.company_id == company_id,
                            ProductBatch.id.in_(batch_ids),
                        )
                    )
                ).all()
            }

        cost_events = list(
            (
                await db.scalars(
                    select(InventoryCostEvent).filter(
                        InventoryCostEvent.company_id == company_id,
                        InventoryCostEvent.inventory_movement_id.in_(movement_ids),
                    )
                )
            ).all()
        )
        cost_event_by_movement = {
            int(event.inventory_movement_id): event for event in cost_events
        }
        cost_uom_ids = sorted({
            int(event.input_uom_id)
            for event in cost_events
            if event.input_uom_id is not None
        })
        cost_uom_by_id: dict[int, UOM] = {}
        if cost_uom_ids:
            cost_uom_by_id = {
                int(row.id): row
                for row in (
                    await db.scalars(select(UOM).where(UOM.id.in_(cost_uom_ids)))
                ).all()
            }
        ledger_currency_code = await db.scalar(
            select(Company.currency_code).where(Company.id == company_id)
        )
        if not ledger_currency_code:
            raise RuntimeError("Company currency is unavailable.")

        stmt_impacts = select(
            InventoryMovementImpact,
            InventoryBalance,
        ).join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id
                == InventoryMovementImpact.company_id,
                InventoryBalance.id
                == InventoryMovementImpact.inventory_balance_id,
            ),
        ).filter(
            InventoryMovementImpact.company_id == company_id,
            InventoryMovementImpact.movement_id.in_(movement_ids),
            InventoryBalance.company_id == company_id,
            access.allows('ledger.read', InventoryBalance.location_id),
        )

        if location_id is not None:
            stmt_impacts = stmt_impacts.filter(
                InventoryBalance.location_id == location_id
            )

        impacts_by_movement: dict[
            int,
            list[tuple[InventoryMovementImpact, InventoryBalance]],
        ] = {}

        for impact, balance in (await db.execute(stmt_impacts)).all():
            impacts_by_movement.setdefault(
                impact.movement_id,
                [],
            ).append((impact, balance))

        result = []

        for movement, product_name, base_uom, quantity_scale, quantity_step, admin_name in rows:
            candidates = impacts_by_movement.get(movement.id, [])
            chosen = None

            def _find_impact(target_location_id, target_status):
                if target_location_id is None or target_status is None:
                    return None
                for impact_row, balance_row in candidates:
                    if (
                        balance_row.location_id == target_location_id
                        and balance_row.stock_status == target_status
                    ):
                        return impact_row, balance_row
                return None

            if movement.movement_kind == 'STATUS_CHANGE':
                chosen = _find_impact(
                    movement.source_location_id,
                    'AVAILABLE',
                )
            elif location_id is not None:
                if movement.source_location_id == location_id:
                    chosen = _find_impact(
                        location_id,
                        movement.source_stock_status,
                    )
                if (
                    chosen is None
                    and movement.destination_location_id == location_id
                ):
                    chosen = _find_impact(
                        location_id,
                        movement.destination_stock_status,
                    )
            else:
                chosen = _find_impact(
                    movement.source_location_id,
                    movement.source_stock_status,
                )
                if chosen is None:
                    chosen = _find_impact(
                        movement.destination_location_id,
                        movement.destination_stock_status,
                    )

            balance_before = None
            balance_after = None
            quantity_packs = None

            if chosen is not None:
                impact, _balance = chosen

                if movement.movement_kind == 'RESERVATION':
                    balance_before = (
                        Decimal(impact.on_hand_before)
                        - Decimal(impact.reserved_before)
                    )
                    balance_after = (
                        Decimal(impact.on_hand_after)
                        - Decimal(impact.reserved_after)
                    )
                else:
                    balance_before = Decimal(impact.on_hand_before)
                    balance_after = Decimal(impact.on_hand_after)

                quantity_packs = balance_after - balance_before

            if quantity_packs is None:
                quantity = Decimal(movement.quantity)

                if movement.movement_kind == 'RESERVATION':
                    quantity_packs = (
                        -quantity
                        if movement.reservation_action == 'RESERVE'
                        else quantity
                    )
                elif movement.movement_kind == 'STATUS_CHANGE':
                    quantity_packs = (
                        -quantity
                        if movement.source_stock_status == 'AVAILABLE'
                        else quantity
                    )
                elif location_id is not None:
                    quantity_packs = (
                        -quantity
                        if movement.source_location_id == location_id
                        else quantity
                    )
                else:
                    quantity_packs = (
                        -quantity
                        if movement.source_location_id is not None
                        else quantity
                    )

            created_at = movement.created_at
            if created_at is not None:
                if created_at.tzinfo is None:
                    response_created_at = created_at.replace(
                        tzinfo=timezone.utc
                    )
                else:
                    response_created_at = created_at.astimezone(
                        timezone.utc
                    )
            else:
                response_created_at = None

            aggregate_snapshot = aggregate_snapshots.get(int(movement.id))
            total_balance_before = (
                aggregate_snapshot[0] if aggregate_snapshot is not None else None
            )
            total_balance_after = (
                aggregate_snapshot[1] if aggregate_snapshot is not None else None
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
                average_base_after = (
                    Decimal("0")
                    if cost_quantity_after == 0
                    else cost_value_after / cost_quantity_after
                )
                if (
                    cost_event.input_quantity is not None
                    and Decimal(cost_event.input_quantity) > 0
                    and input_uom is not None
                ):
                    event_factor = (
                        Decimal(movement.quantity)
                        / Decimal(cost_event.input_quantity)
                    )
                    average_cost_after = average_base_after * event_factor
                    average_cost_uom_code = str(input_uom.code)
                    average_cost_uom_name = str(input_uom.name)
                else:
                    average_cost_after = average_base_after * display_factor
                    average_cost_uom_code = display_uom_code
                    average_cost_uom_name = display_uom_name
                average_cost_after = average_cost_after.quantize(
                    Decimal("0.000001")
                )

            result.append({
                "id": movement.id,
                "product_variant_id": movement.product_variant_id,
                "product_name": product_name,
                "base_uom_id": base_uom.id,
                "base_uom_code": base_uom.code,
                "quantity_scale": int(quantity_scale),
                "quantity_step": canonical_quantity(quantity_step),
                "type": movement.reference_type,
                "quantity": canonical_quantity(quantity_packs),
                "balance_before": total_balance_before,
                "balance_after": total_balance_after,
                "balance_scope": (
                    "PRODUCT_LOCATION"
                    if aggregate_snapshot is not None
                    else None
                ),
                "batch_number": (
                    batch_number_by_id.get(int(movement.batch_id))
                    if movement.batch_id is not None
                    else None
                ),
                "display_uom_id": display_uom_id,
                "display_uom_code": display_uom_code,
                "display_uom_name": display_uom_name,
                "display_factor_to_base": canonical_quantity(display_factor),
                "currency_code": str(ledger_currency_code).upper(),
                "cost_method": (
                    str(cost_event.method) if cost_event is not None else None
                ),
                "input_quantity": (
                    canonical_quantity(cost_event.input_quantity)
                    if cost_event is not None
                    and cost_event.input_quantity is not None
                    else None
                ),
                "input_uom_code": (
                    str(input_uom.code) if input_uom is not None else None
                ),
                "input_uom_name": (
                    str(input_uom.name) if input_uom is not None else None
                ),
                "input_unit_cost": (
                    format(
                        Decimal(cost_event.input_unit_cost).quantize(
                            Decimal("0.000001")
                        ),
                        "f",
                    )
                    if cost_event is not None
                    and cost_event.input_unit_cost is not None
                    else None
                ),
                "total_cost": (
                    format(
                        Decimal(cost_event.total_cost).quantize(
                            Decimal("0.000001")
                        ),
                        "f",
                    )
                    if cost_event is not None
                    else None
                ),
                "average_cost_after": (
                    format(average_cost_after, "f")
                    if average_cost_after is not None
                    else None
                ),
                "average_cost_uom_code": average_cost_uom_code,
                "average_cost_uom_name": average_cost_uom_name,
                "admin_name": admin_name or "غير معروف",
                "reference": movement.reference_id,
                "notes": movement.notes,
                "date": (
                    response_created_at.isoformat()
                    if response_created_at
                    else ""
                ),
            })

        next_cursor = None
        if has_more and rows:
            last_movement = rows[-1][0]
            if last_movement.created_at is None:
                raise RuntimeError(
                    "Ledger invariant violated: movement without created_at."
                )
            next_cursor = _encode_ledger_cursor(
                last_movement.created_at,
                last_movement.id,
                scope=ledger_scope,
            )

        return {
            "items": result,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
            "available_types": available_types,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"خطأ في Cursor سجل المستودع: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي أثناء جلب صفحة سجل الحركات.",
        )

