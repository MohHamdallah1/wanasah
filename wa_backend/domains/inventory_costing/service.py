"""Perpetual inventory costing.

InventoryBalance remains the sole physical quantity authority. This module owns
financial inventory valuation and immutable cost evidence. Physical FEFO batch
allocation and financial cost-flow are deliberately independent authorities.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Company,
    InventoryBalance,
    InventoryCostAllocation,
    InventoryCostEvent,
    InventoryCostLayer,
    InventoryCostPolicy,
    InventoryCostState,
    InventoryMovement,
)

MONEY_QUANT = Decimal("0.000001")
MONEY_MAX = Decimal("99999999999999.999999")
COST_METHODS = frozenset({"MOVING_AVERAGE", "FIFO"})


class CostingError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)
        self.context = dict(context or {})

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


def money6(value: Any, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CostingError(
            "INVENTORY_COST_INVALID",
            f"{field} is invalid.",
            status_code=422,
            context={"field": field},
        ) from exc
    if not amount.is_finite() or amount < 0:
        raise CostingError(
            "INVENTORY_COST_INVALID",
            f"{field} must be finite and non-negative.",
            status_code=422,
            context={"field": field},
        )
    try:
        amount = amount.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise CostingError(
            "INVENTORY_COST_INVALID",
            f"{field} cannot be represented.",
            status_code=422,
            context={"field": field},
        ) from exc
    if amount > MONEY_MAX:
        raise CostingError(
            "INVENTORY_COST_OVERFLOW",
            f"{field} exceeds the supported money range.",
            status_code=422,
            context={"field": field},
        )
    return amount


def _positive_quantity(value: Any, field: str) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CostingError(
            "INVENTORY_COST_QUANTITY_INVALID",
            f"{field} is invalid.",
            status_code=422,
            context={"field": field},
        ) from exc
    if not quantity.is_finite() or quantity <= 0:
        raise CostingError(
            "INVENTORY_COST_QUANTITY_INVALID",
            f"{field} must be greater than zero.",
            status_code=422,
            context={"field": field},
        )
    return quantity


def build_purchase_cost_input(
    *,
    input_uom_id: int,
    input_quantity: Decimal,
    input_unit_cost: Decimal,
    base_quantity: Decimal,
) -> dict[str, Any]:
    input_qty = _positive_quantity(input_quantity, "input_quantity")
    base_qty = _positive_quantity(base_quantity, "base_quantity")
    unit_cost = money6(input_unit_cost, "input_unit_cost")
    total_cost = money6(input_qty * unit_cost, "total_cost")
    return {
        "input_uom_id": int(input_uom_id),
        "input_quantity": input_qty,
        "input_unit_cost": unit_cost,
        "total_cost": total_cost,
        "base_quantity": base_qty,
    }


async def _policy_guard(db: AsyncSession, company_id: int) -> None:
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "CAST(:company_id AS integer), "
            "hashtext('inventory-cost-policy'))"
        ),
        {"company_id": int(company_id)},
    )


async def get_cost_policy(
    db: AsyncSession,
    *,
    company_id: int,
    lock: bool = False,
) -> InventoryCostPolicy | None:
    stmt = select(InventoryCostPolicy).where(
        InventoryCostPolicy.company_id == int(company_id)
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def cost_policy_payload(
    db: AsyncSession,
    *,
    company_id: int,
    can_change: bool,
) -> dict[str, Any]:
    company = await db.scalar(select(Company).where(Company.id == int(company_id)))
    if company is None:
        raise CostingError("COMPANY_NOT_FOUND", "Company was not found.", status_code=404)
    policy = await get_cost_policy(db, company_id=int(company_id))
    if policy is None:
        return {
            "method": "MOVING_AVERAGE",
            "is_active": False,
            "is_locked": False,
            "locked_at": None,
            "version": 0,
            "currency_code": str(company.currency_code).upper(),
            "can_change": bool(can_change),
        }
    return {
        "method": str(policy.method),
        "is_active": bool(policy.is_active),
        "is_locked": bool(policy.locked_at is not None),
        "locked_at": policy.locked_at.isoformat() if policy.locked_at is not None else None,
        "version": int(policy.version),
        "currency_code": str(company.currency_code).upper(),
        "can_change": bool(can_change and not policy.is_active),
    }


async def provision_default_cost_policy(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
) -> InventoryCostPolicy:
    await _policy_guard(db, int(company_id))
    policy = await get_cost_policy(db, company_id=int(company_id), lock=True)
    if policy is not None:
        return policy
    policy = InventoryCostPolicy(
        company_id=int(company_id),
        method="MOVING_AVERAGE",
        is_active=False,
        locked_at=None,
        version=1,
        created_by=int(actor_id),
        updated_by=int(actor_id),
    )
    db.add(policy)
    await db.flush()
    return policy


async def set_cost_policy(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    method: str,
    expected_version: int,
) -> InventoryCostPolicy:
    normalized = str(method or "").strip().upper()
    if normalized not in COST_METHODS:
        raise CostingError(
            "INVENTORY_COST_METHOD_INVALID",
            "Unsupported inventory costing method.",
            status_code=422,
        )
    if type(expected_version) is not int or expected_version < 0:
        raise CostingError(
            "INVENTORY_COST_POLICY_VERSION_INVALID",
            "expected_version is invalid.",
            status_code=422,
        )
    await _policy_guard(db, int(company_id))
    policy = await get_cost_policy(db, company_id=int(company_id), lock=True)
    if policy is None:
        if expected_version != 0:
            raise CostingError(
                "INVENTORY_COST_POLICY_VERSION_CONFLICT",
                "Inventory costing policy changed.",
                context={"current_version": 0},
            )
        policy = InventoryCostPolicy(
            company_id=int(company_id),
            method=normalized,
            is_active=False,
            locked_at=None,
            version=1,
            created_by=int(actor_id),
            updated_by=int(actor_id),
        )
        db.add(policy)
        await db.flush()
        return policy
    if int(policy.version) != expected_version:
        raise CostingError(
            "INVENTORY_COST_POLICY_VERSION_CONFLICT",
            "Inventory costing policy changed.",
            context={"current_version": int(policy.version)},
        )
    if policy.is_active or policy.locked_at is not None:
        raise CostingError(
            "INVENTORY_COST_POLICY_LOCKED",
            "Inventory costing method is locked after the first costed receipt.",
        )
    if str(policy.method) != normalized:
        policy.method = normalized
        policy.version += 1
        policy.updated_by = int(actor_id)
        policy.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.flush()
    return policy


async def activate_costing_for_first_receipt(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
) -> InventoryCostPolicy:
    """Activate/lock the method before the first supplier movement is posted."""
    await _policy_guard(db, int(company_id))
    policy = await get_cost_policy(db, company_id=int(company_id), lock=True)
    if policy is not None and policy.is_active:
        return policy
    existing_quantity = await db.scalar(
        select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), Decimal("0"))).where(
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.on_hand_quantity > 0,
        )
    )
    if Decimal(existing_quantity or 0) != 0:
        raise CostingError(
            "COST_OPENING_BALANCE_REQUIRED",
            "Existing stock needs an explicit opening valuation before costing can be activated.",
            context={"existing_quantity": format(Decimal(existing_quantity or 0), "f")},
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if policy is None:
        policy = InventoryCostPolicy(
            company_id=int(company_id),
            method="MOVING_AVERAGE",
            is_active=True,
            locked_at=now,
            version=1,
            created_by=int(actor_id),
            updated_by=int(actor_id),
        )
        db.add(policy)
    else:
        policy.is_active = True
        policy.locked_at = now
        policy.version += 1
        policy.updated_by = int(actor_id)
        policy.updated_at = now
    await db.flush()
    return policy


async def _acquire_variant_guards(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int],
) -> None:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return
    await db.execute(
        text(
            """
            SELECT pg_advisory_xact_lock(
                CAST(:company_id AS integer),
                hashtext('inventory-cost:' || variant_id::text)
            )
            FROM unnest(CAST(:variant_ids AS integer[])) AS t(variant_id)
            ORDER BY variant_id
            """
        ),
        {"company_id": int(company_id), "variant_ids": ids},
    )


async def _load_states(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int],
) -> dict[int, InventoryCostState]:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return {}
    await db.execute(
        pg_insert(InventoryCostState)
        .values([
            {
                "company_id": int(company_id),
                "product_variant_id": variant_id,
                "quantity": Decimal("0"),
                "inventory_value": Decimal("0"),
                "average_unit_cost": Decimal("0"),
                "version": 1,
            }
            for variant_id in ids
        ])
        .on_conflict_do_nothing(index_elements=["company_id", "product_variant_id"])
    )
    rows = list((await db.scalars(
        select(InventoryCostState)
        .where(
            InventoryCostState.company_id == int(company_id),
            InventoryCostState.product_variant_id.in_(ids),
        )
        .order_by(InventoryCostState.product_variant_id.asc())
        .with_for_update()
    )).all())
    result = {int(row.product_variant_id): row for row in rows}
    if set(result) != set(ids):
        raise CostingError("INVENTORY_COST_STATE_MISSING", "Inventory cost state could not be established.")
    return result


def _set_state(state: InventoryCostState, *, quantity: Decimal, value: Decimal) -> None:
    normalized_value = money6(value, "inventory_value")
    if quantity < 0:
        raise CostingError("INVENTORY_COST_STATE_NEGATIVE", "Inventory cost quantity cannot become negative.")
    if quantity == 0:
        if normalized_value != Decimal("0.000000"):
            raise CostingError(
                "INVENTORY_COST_STATE_INCONSISTENT",
                "Zero inventory quantity cannot retain inventory value.",
            )
        average = Decimal("0.000000")
    else:
        average = money6(normalized_value / quantity, "average_unit_cost")
    state.quantity = quantity
    state.inventory_value = normalized_value
    state.average_unit_cost = average
    state.version += 1
    state.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def _new_event(
    *,
    company_id: int,
    movement: InventoryMovement,
    method: str,
    event_type: str,
    cost_basis: str,
    total_cost: Decimal,
    quantity_before: Decimal,
    value_before: Decimal,
    quantity_after: Decimal,
    value_after: Decimal,
    input_uom_id: int | None = None,
    input_quantity: Decimal | None = None,
    input_unit_cost: Decimal | None = None,
    reversal_of_cost_event_id: int | None = None,
) -> InventoryCostEvent:
    quantity = _positive_quantity(movement.quantity, "movement.quantity")
    total = money6(total_cost, "total_cost")
    return InventoryCostEvent(
        company_id=int(company_id),
        inventory_movement_id=int(movement.id),
        product_variant_id=int(movement.product_variant_id),
        batch_id=int(movement.batch_id),
        method=str(method),
        event_type=str(event_type),
        cost_basis=str(cost_basis),
        quantity=quantity,
        unit_cost=money6(total / quantity, "unit_cost"),
        total_cost=total,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        value_before=money6(value_before, "value_before"),
        value_after=money6(value_after, "value_after"),
        input_uom_id=input_uom_id,
        input_quantity=input_quantity,
        input_unit_cost=input_unit_cost,
        reversal_of_cost_event_id=reversal_of_cost_event_id,
    )


def _external_physical(movement: InventoryMovement) -> bool:
    return (
        str(movement.movement_kind) == "PHYSICAL"
        and ((movement.source_location_id is None) != (movement.destination_location_id is None))
    )


async def validate_inventory_costing_replays(
    db: AsyncSession,
    *,
    company_id: int,
    movement_specs: list[tuple[InventoryMovement, dict[str, Any]]],
) -> None:
    if not movement_specs:
        return
    external = [(movement, spec) for movement, spec in movement_specs if _external_physical(movement)]
    for movement, spec in movement_specs:
        if _external_physical(movement):
            continue
        if spec.get("inventory_cost_input") is not None or spec.get("cost_reversal_of_movement_id") is not None:
            raise CostingError(
                "INVENTORY_COST_REPLAY_CONFLICT",
                "Internal movement cannot carry external cost metadata.",
            )
    if not external:
        return
    policy = await get_cost_policy(db, company_id=int(company_id))
    movement_ids = [int(movement.id) for movement, _spec in external]
    events = list((await db.scalars(
        select(InventoryCostEvent).where(
            InventoryCostEvent.company_id == int(company_id),
            InventoryCostEvent.inventory_movement_id.in_(movement_ids),
        )
    )).all())
    event_by_movement = {int(event.inventory_movement_id): event for event in events}
    if policy is None or not policy.is_active:
        if events or any(spec.get("inventory_cost_input") is not None for _movement, spec in external):
            raise CostingError("INVENTORY_COST_REPLAY_CONFLICT", "Inventory costing replay state is inconsistent.")
        return
    missing = sorted(set(movement_ids) - set(event_by_movement))
    if missing:
        raise CostingError(
            "INVENTORY_COST_EVENT_MISSING",
            "Cost event is missing for an existing external inventory movement.",
            context={"inventory_movement_ids": missing[:20]},
        )
    reversal_source_ids = sorted({
        int(spec["cost_reversal_of_movement_id"])
        for _movement, spec in external
        if spec.get("cost_reversal_of_movement_id") is not None
    })
    original_by_movement: dict[int, int] = {}
    if reversal_source_ids:
        rows = (await db.execute(
            select(InventoryCostEvent.inventory_movement_id, InventoryCostEvent.id).where(
                InventoryCostEvent.company_id == int(company_id),
                InventoryCostEvent.inventory_movement_id.in_(reversal_source_ids),
            )
        )).all()
        original_by_movement = {int(row.inventory_movement_id): int(row.id) for row in rows}
    for movement, spec in external:
        event = event_by_movement[int(movement.id)]
        if str(movement.reference_type) == "INBOUND_SUPPLIER":
            raw = spec.get("inventory_cost_input")
            if not isinstance(raw, dict):
                raise CostingError("INBOUND_COST_REQUIRED", "Supplier inbound replay requires the original purchase cost.")
            input_qty = _positive_quantity(raw["input_quantity"], "input_quantity")
            input_cost = money6(raw["input_unit_cost"], "input_unit_cost")
            expected_total = money6(input_qty * input_cost, "total_cost")
            if not (
                str(event.event_type) == "PURCHASE_IN"
                and int(event.input_uom_id) == int(raw["input_uom_id"])
                and Decimal(event.input_quantity) == input_qty
                and Decimal(event.input_unit_cost) == input_cost
                and Decimal(event.total_cost) == expected_total
            ):
                raise CostingError(
                    "INVENTORY_COST_REPLAY_CONFLICT",
                    "Supplier inbound idempotency key was reused with a different cost.",
                )
        reversal_of = spec.get("cost_reversal_of_movement_id")
        if reversal_of is not None:
            original_event_id = original_by_movement.get(int(reversal_of))
            if original_event_id is None or event.reversal_of_cost_event_id != original_event_id:
                raise CostingError(
                    "INVENTORY_COST_REPLAY_CONFLICT",
                    "Inventory reversal replay does not match its original cost event.",
                )


async def apply_inventory_costing_for_movements(
    db: AsyncSession,
    *,
    company_id: int,
    movement_specs: list[tuple[InventoryMovement, dict[str, Any]]],
) -> None:
    if not movement_specs:
        return
    policy = await get_cost_policy(db, company_id=int(company_id))
    has_cost_input = any(isinstance(spec.get("inventory_cost_input"), dict) for _movement, spec in movement_specs)
    if policy is None or not policy.is_active:
        if has_cost_input:
            raise CostingError(
                "INVENTORY_COST_POLICY_NOT_ACTIVE",
                "Inventory costing policy must be active before a costed receipt.",
            )
        return
    method = str(policy.method).upper()
    if method not in COST_METHODS:
        raise CostingError("INVENTORY_COST_METHOD_INVALID", "Inventory costing policy is invalid.")
    external_pairs = [(movement, spec) for movement, spec in movement_specs if _external_physical(movement)]
    if not external_pairs:
        return
    if any(
        not _external_physical(movement)
        and (spec.get("inventory_cost_input") is not None or spec.get("cost_reversal_of_movement_id") is not None)
        for movement, spec in movement_specs
    ):
        raise CostingError(
            "INVENTORY_COST_METADATA_SCOPE_INVALID",
            "Cost metadata is only valid on external physical movements.",
        )

    variant_ids = sorted({int(movement.product_variant_id) for movement, _spec in external_pairs})
    await _acquire_variant_guards(db, company_id=int(company_id), variant_ids=variant_ids)
    states = await _load_states(db, company_id=int(company_id), variant_ids=variant_ids)

    reversal_source_ids = sorted({
        int(spec["cost_reversal_of_movement_id"])
        for _movement, spec in external_pairs
        if spec.get("cost_reversal_of_movement_id") is not None
    })
    original_events_by_movement: dict[int, InventoryCostEvent] = {}
    original_allocations: dict[int, list[InventoryCostAllocation]] = defaultdict(list)
    source_layer_by_event: dict[int, InventoryCostLayer] = {}
    layer_ids_to_lock: set[int] = set()
    if reversal_source_ids:
        originals = list((await db.scalars(
            select(InventoryCostEvent).where(
                InventoryCostEvent.company_id == int(company_id),
                InventoryCostEvent.inventory_movement_id.in_(reversal_source_ids),
            )
        )).all())
        original_events_by_movement = {int(event.inventory_movement_id): event for event in originals}
        if set(original_events_by_movement) != set(reversal_source_ids):
            raise CostingError("COST_REVERSAL_SOURCE_MISSING", "One or more original cost events are missing.")
        original_event_ids = [int(event.id) for event in originals]
        prior_reversal_ids = set((await db.scalars(
            select(InventoryCostEvent.reversal_of_cost_event_id).where(
                InventoryCostEvent.company_id == int(company_id),
                InventoryCostEvent.reversal_of_cost_event_id.in_(original_event_ids),
            )
        )).all())
        if prior_reversal_ids:
            raise CostingError(
                "COST_REVERSAL_ALREADY_APPLIED",
                "One or more original cost events were already reversed.",
                context={"cost_event_ids": sorted(int(value) for value in prior_reversal_ids)[:20]},
            )
        if method == "FIFO":
            allocations = list((await db.scalars(
                select(InventoryCostAllocation)
                .where(
                    InventoryCostAllocation.company_id == int(company_id),
                    InventoryCostAllocation.cost_event_id.in_(original_event_ids),
                    InventoryCostAllocation.allocation_type == "CONSUME",
                )
                .order_by(InventoryCostAllocation.cost_event_id.asc(), InventoryCostAllocation.id.asc())
            )).all())
            for allocation in allocations:
                original_allocations[int(allocation.cost_event_id)].append(allocation)
                layer_ids_to_lock.add(int(allocation.cost_layer_id))
            source_layers = list((await db.scalars(
                select(InventoryCostLayer).where(
                    InventoryCostLayer.company_id == int(company_id),
                    InventoryCostLayer.source_cost_event_id.in_(original_event_ids),
                )
            )).all())
            source_layer_by_event = {int(layer.source_cost_event_id): layer for layer in source_layers}
            layer_ids_to_lock.update(int(layer.id) for layer in source_layers)

    fifo_layers_by_variant: dict[int, list[InventoryCostLayer]] = defaultdict(list)
    layer_by_id: dict[int, InventoryCostLayer] = {}
    if method == "FIFO":
        consume_variant_ids = sorted({
            int(movement.product_variant_id)
            for movement, spec in external_pairs
            if movement.source_location_id is not None and spec.get("cost_reversal_of_movement_id") is None
        })
        conditions = []
        if consume_variant_ids:
            conditions.append(InventoryCostLayer.product_variant_id.in_(consume_variant_ids))
        if layer_ids_to_lock:
            conditions.append(InventoryCostLayer.id.in_(sorted(layer_ids_to_lock)))
        if conditions:
            layers = list((await db.scalars(
                select(InventoryCostLayer)
                .where(InventoryCostLayer.company_id == int(company_id), or_(*conditions))
                .order_by(
                    InventoryCostLayer.product_variant_id.asc(),
                    InventoryCostLayer.created_at.asc(),
                    InventoryCostLayer.id.asc(),
                )
                .with_for_update()
            )).all())
            for layer in layers:
                layer_by_id[int(layer.id)] = layer
                if Decimal(layer.remaining_quantity) > 0:
                    fifo_layers_by_variant[int(layer.product_variant_id)].append(layer)
        if layer_ids_to_lock - set(layer_by_id):
            raise CostingError("FIFO_REVERSAL_LAYER_MISSING", "A FIFO cost layer required by a reversal is missing.")
        source_layer_by_event = {
            int(event_id): layer_by_id[int(layer.id)]
            for event_id, layer in source_layer_by_event.items()
            if int(layer.id) in layer_by_id
        }

    pending_events: list[InventoryCostEvent] = []
    pending_layers: list[tuple[InventoryCostLayer, InventoryCostEvent]] = []
    pending_allocations: list[tuple[InventoryCostEvent, InventoryCostLayer, str, Decimal, Decimal]] = []
    reversed_original_ids: set[int] = set()
    affected: set[int] = set()

    for movement, spec in external_pairs:
        variant_id = int(movement.product_variant_id)
        batch_id = int(movement.batch_id)
        state = states[variant_id]
        affected.add(variant_id)
        before_q = Decimal(state.quantity)
        before_v = Decimal(state.inventory_value)
        quantity = _positive_quantity(movement.quantity, "movement.quantity")
        reversal_source = spec.get("cost_reversal_of_movement_id")

        if reversal_source is not None:
            original = original_events_by_movement[int(reversal_source)]
            if (
                int(original.product_variant_id) != variant_id
                or int(original.batch_id) != batch_id
                or Decimal(original.quantity) != quantity
                or str(original.method) != method
                or str(original.event_type) in {"REVERSAL_IN", "REVERSAL_OUT"}
            ):
                raise CostingError("COST_REVERSAL_SOURCE_MISMATCH", "Original cost event does not match the inventory reversal.")
            if int(original.id) in reversed_original_ids:
                raise CostingError("COST_REVERSAL_ALREADY_APPLIED", "The same original cost event is reversed twice.")
            reversed_original_ids.add(int(original.id))
            total_cost = Decimal(original.total_cost)

            if movement.source_location_id is None:
                if str(original.event_type) != "OUTBOUND":
                    raise CostingError("COST_REVERSAL_DIRECTION_MISMATCH", "Inbound reversal requires an original outbound cost event.")
                after_q = before_q + quantity
                after_v = money6(before_v + total_cost, "inventory_value")
                event_type = "REVERSAL_IN"
                if method == "FIFO":
                    allocations = original_allocations.get(int(original.id), [])
                    if not allocations:
                        raise CostingError("FIFO_REVERSAL_ALLOCATIONS_MISSING", "FIFO outbound allocations are missing.")
                    for allocation in allocations:
                        layer = layer_by_id[int(allocation.cost_layer_id)]
                        restored_qty = Decimal(layer.remaining_quantity) + Decimal(allocation.quantity)
                        restored_value = money6(Decimal(layer.remaining_value) + Decimal(allocation.amount), "fifo_restored_value")
                        if restored_qty > Decimal(layer.original_quantity) or restored_value > Decimal(layer.original_value):
                            raise CostingError("FIFO_REVERSAL_LAYER_OVERFLOW", "FIFO reversal would restore more than the original layer.")
                        layer.remaining_quantity = restored_qty
                        layer.remaining_value = restored_value
                        layer.version += 1
                        layer.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        if layer not in fifo_layers_by_variant[variant_id]:
                            fifo_layers_by_variant[variant_id].append(layer)
                            fifo_layers_by_variant[variant_id].sort(key=lambda row: (row.created_at, int(row.id)))
                        pending_allocations.append((None, layer, "RESTORE", Decimal(allocation.quantity), Decimal(allocation.amount)))
            else:
                if str(original.event_type) not in {"PURCHASE_IN", "ADJUSTMENT_IN"}:
                    raise CostingError("COST_REVERSAL_DIRECTION_MISMATCH", "Outbound reversal requires an original inbound cost event.")
                if before_q < quantity or before_v < total_cost:
                    raise CostingError("COST_REVERSAL_STATE_SHORTAGE", "Current cost state cannot reverse the original inbound value exactly.")
                after_q = before_q - quantity
                after_v = money6(before_v - total_cost, "inventory_value")
                event_type = "REVERSAL_OUT"
                if method == "FIFO":
                    layer = source_layer_by_event.get(int(original.id))
                    if layer is None:
                        raise CostingError("FIFO_REVERSAL_LAYER_MISSING", "Original inbound FIFO layer is missing.")
                    if Decimal(layer.remaining_quantity) < quantity or Decimal(layer.remaining_value) < total_cost:
                        raise CostingError(
                            "FIFO_REVERSAL_LAYER_ALREADY_CONSUMED",
                            "The original inbound FIFO layer was already consumed and cannot be reversed exactly.",
                        )
                    layer.remaining_quantity = Decimal(layer.remaining_quantity) - quantity
                    layer.remaining_value = money6(Decimal(layer.remaining_value) - total_cost, "fifo_unwind_value")
                    layer.version += 1
                    layer.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    pending_allocations.append((None, layer, "UNWIND", quantity, total_cost))

            if after_q == 0 and after_v != Decimal("0.000000"):
                raise CostingError("INVENTORY_COST_STATE_INCONSISTENT", "Reversal would leave value on zero quantity.")
            event = _new_event(
                company_id=company_id,
                movement=movement,
                method=method,
                event_type=event_type,
                cost_basis="ORIGINAL_REVERSAL",
                total_cost=total_cost,
                quantity_before=before_q,
                value_before=before_v,
                quantity_after=after_q,
                value_after=after_v,
                reversal_of_cost_event_id=int(original.id),
            )
            pending_events.append(event)
            # Replace placeholder event on allocations added by this reversal.
            for index in range(len(pending_allocations) - 1, -1, -1):
                alloc_event, layer, alloc_type, alloc_qty, alloc_amount = pending_allocations[index]
                if alloc_event is not None:
                    break
                pending_allocations[index] = (event, layer, alloc_type, alloc_qty, alloc_amount)
            _set_state(state, quantity=after_q, value=after_v)
            continue

        if movement.source_location_id is None:
            if str(movement.reference_type) == "INBOUND_SUPPLIER":
                raw = spec.get("inventory_cost_input")
                if not isinstance(raw, dict):
                    raise CostingError(
                        "INBOUND_COST_REQUIRED",
                        "Supplier inbound requires actual purchase cost.",
                        status_code=422,
                        context={"product_variant_id": variant_id},
                    )
                base_qty = _positive_quantity(raw["base_quantity"], "base_quantity")
                if base_qty != quantity:
                    raise CostingError("INBOUND_COST_QUANTITY_MISMATCH", "Cost quantity does not match inventory movement quantity.")
                input_qty = _positive_quantity(raw["input_quantity"], "input_quantity")
                input_unit_cost = money6(raw["input_unit_cost"], "input_unit_cost")
                total_cost = money6(input_qty * input_unit_cost, "total_cost")
                if total_cost != money6(raw["total_cost"], "total_cost"):
                    raise CostingError("INBOUND_COST_TOTAL_MISMATCH", "Purchase cost total is inconsistent.")
                after_q = before_q + quantity
                after_v = money6(before_v + total_cost, "inventory_value")
                event = _new_event(
                    company_id=company_id,
                    movement=movement,
                    method=method,
                    event_type="PURCHASE_IN",
                    cost_basis="PURCHASE_ACTUAL",
                    total_cost=total_cost,
                    quantity_before=before_q,
                    value_before=before_v,
                    quantity_after=after_q,
                    value_after=after_v,
                    input_uom_id=int(raw["input_uom_id"]),
                    input_quantity=input_qty,
                    input_unit_cost=input_unit_cost,
                )
            else:
                if before_q <= 0:
                    raise CostingError(
                        "COST_BASIS_REQUIRED",
                        "External inventory increase has no exact/current cost basis.",
                        context={
                            "product_variant_id": variant_id,
                            "reference_type": str(movement.reference_type),
                        },
                    )
                total_cost = money6(Decimal(state.average_unit_cost) * quantity, "adjustment_cost")
                after_q = before_q + quantity
                after_v = money6(before_v + total_cost, "inventory_value")
                event = _new_event(
                    company_id=company_id,
                    movement=movement,
                    method=method,
                    event_type="ADJUSTMENT_IN",
                    cost_basis="CURRENT_AVERAGE_ESTIMATE",
                    total_cost=total_cost,
                    quantity_before=before_q,
                    value_before=before_v,
                    quantity_after=after_q,
                    value_after=after_v,
                )
            pending_events.append(event)
            if method == "FIFO":
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                layer = InventoryCostLayer(
                    company_id=int(company_id),
                    product_variant_id=variant_id,
                    batch_id=batch_id,
                    source_cost_event_id=0,
                    original_quantity=quantity,
                    remaining_quantity=quantity,
                    unit_cost=money6(total_cost / quantity, "layer_unit_cost"),
                    original_value=total_cost,
                    remaining_value=total_cost,
                    created_at=now,
                    updated_at=now,
                )
                pending_layers.append((layer, event))
                fifo_layers_by_variant[variant_id].append(layer)
            _set_state(state, quantity=after_q, value=after_v)
            continue

        # External outbound. Financial FIFO intentionally follows acquisition
        # layers globally for the product, not the physical FEFO batch selected
        # by the vehicle/inventory engine.
        if before_q < quantity:
            raise CostingError(
                "INVENTORY_COST_QUANTITY_SHORTAGE",
                "Cost state does not cover the outbound inventory quantity.",
                context={
                    "product_variant_id": variant_id,
                    "available_quantity": format(before_q, "f"),
                    "requested_quantity": format(quantity, "f"),
                },
            )
        fifo_consumed: list[tuple[InventoryCostLayer, Decimal, Decimal]] = []
        if method == "MOVING_AVERAGE":
            total_cost = before_v if quantity == before_q else money6(Decimal(state.average_unit_cost) * quantity, "outbound_cost")
            if total_cost > before_v:
                total_cost = before_v
            basis = "MOVING_AVERAGE"
        else:
            remaining = quantity
            total_cost = Decimal("0.000000")
            for layer in fifo_layers_by_variant[variant_id]:
                if remaining <= 0:
                    break
                layer_qty = Decimal(layer.remaining_quantity)
                layer_value = Decimal(layer.remaining_value)
                if layer_qty <= 0:
                    continue
                take = min(layer_qty, remaining)
                value = layer_value if take == layer_qty else money6(layer_value * take / layer_qty, "fifo_allocation_value")
                if value > layer_value:
                    value = layer_value
                layer.remaining_quantity = layer_qty - take
                layer.remaining_value = money6(layer_value - value, "fifo_layer_remaining_value")
                layer.version += 1
                layer.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                fifo_consumed.append((layer, take, value))
                total_cost = money6(total_cost + value, "fifo_total_cost")
                remaining -= take
            if remaining != 0:
                raise CostingError(
                    "FIFO_COST_LAYER_SHORTAGE",
                    "FIFO cost layers do not cover the outbound product quantity.",
                    context={"product_variant_id": variant_id, "missing_quantity": format(remaining, "f")},
                )
            basis = "FIFO_LAYER"
        after_q = before_q - quantity
        after_v = money6(before_v - total_cost, "inventory_value")
        if after_q == 0:
            if method == "FIFO" and total_cost != before_v:
                raise CostingError(
                    "FIFO_COST_VALUE_RECONCILIATION_FAILED",
                    "FIFO layers do not reconcile with inventory value.",
                    context={
                        "product_variant_id": variant_id,
                        "state_value": format(before_v, "f"),
                        "fifo_value": format(total_cost, "f"),
                    },
                )
            total_cost = before_v
            after_v = Decimal("0.000000")
        event = _new_event(
            company_id=company_id,
            movement=movement,
            method=method,
            event_type="OUTBOUND",
            cost_basis=basis,
            total_cost=total_cost,
            quantity_before=before_q,
            value_before=before_v,
            quantity_after=after_q,
            value_after=after_v,
        )
        pending_events.append(event)
        for layer, consumed_qty, consumed_value in fifo_consumed:
            pending_allocations.append((event, layer, "CONSUME", consumed_qty, consumed_value))
        _set_state(state, quantity=after_q, value=after_v)

    db.add_all(pending_events)
    await db.flush()
    if pending_layers:
        for layer, event in pending_layers:
            layer.source_cost_event_id = int(event.id)
            db.add(layer)
        await db.flush()
    if pending_allocations:
        for event, layer, allocation_type, quantity, amount in pending_allocations:
            if event is None or layer.id is None:
                raise CostingError("FIFO_COST_ALLOCATION_ID_MISSING", "FIFO costing identity was not established.")
            db.add(InventoryCostAllocation(
                company_id=int(company_id),
                cost_event_id=int(event.id),
                cost_layer_id=int(layer.id),
                allocation_type=allocation_type,
                quantity=quantity,
                amount=amount,
            ))
    await db.flush()

    inventory_rows = (await db.execute(
        select(
            InventoryBalance.product_variant_id,
            func.coalesce(func.sum(InventoryBalance.on_hand_quantity), Decimal("0")).label("quantity"),
        )
        .where(
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.product_variant_id.in_(sorted(affected)),
        )
        .group_by(InventoryBalance.product_variant_id)
    )).all()
    actual = {int(row.product_variant_id): Decimal(row.quantity) for row in inventory_rows}
    for variant_id in affected:
        state_quantity = Decimal(states[variant_id].quantity)
        actual_quantity = actual.get(variant_id, Decimal("0"))
        if state_quantity != actual_quantity:
            raise CostingError(
                "INVENTORY_COST_RECONCILIATION_FAILED",
                "Inventory cost quantity does not reconcile with physical stock.",
                context={
                    "product_variant_id": variant_id,
                    "cost_quantity": format(state_quantity, "f"),
                    "physical_quantity": format(actual_quantity, "f"),
                },
            )
