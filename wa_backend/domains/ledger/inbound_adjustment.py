from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    InventoryLocation,
    InventoryMovement,
    ProductVariant,
    SystemAuditLog,
    UOM,
)
from quantity import canonical_quantity
from services import apply_inventory_movement


class LedgerAdjustmentError(Exception):
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


@dataclass(frozen=True)
class InboundAdjustmentState:
    entry_id: int
    reference: str
    normalized_reference: str
    product_variant_id: int
    batch_id: int | None
    warehouse_location_id: int
    current_total_quantity: Decimal
    base_uom_id: int
    base_uom_code: str

    def response(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "reference": self.reference,
            "product_variant_id": self.product_variant_id,
            "batch_id": self.batch_id,
            "warehouse_location_id": self.warehouse_location_id,
            "current_total_quantity": canonical_quantity(self.current_total_quantity),
            "base_uom_id": self.base_uom_id,
            "base_uom_code": self.base_uom_code,
        }


def _error(status: int, code: str, message: str, **context: Any) -> LedgerAdjustmentError:
    return LedgerAdjustmentError(status, code, message, context=context)


async def _load_original(
    db: AsyncSession,
    *,
    company_id: int,
    entry_id: int,
) -> InventoryMovement:
    original = await db.scalar(
        select(InventoryMovement).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.id == entry_id,
            InventoryMovement.reference_type == "INBOUND_SUPPLIER",
        )
    )
    if original is None:
        raise _error(404, "LEDGER_ADJUSTMENT_SOURCE_NOT_FOUND", "Inbound movement is unavailable.")
    if (
        original.movement_kind != "PHYSICAL"
        or original.source_location_id is not None
        or original.destination_location_id is None
        or original.destination_stock_status != "AVAILABLE"
    ):
        raise _error(409, "LEDGER_ADJUSTMENT_SOURCE_INVALID", "The selected movement is not an eligible supplier inbound movement.")
    reference = (original.reference_id or "").strip()
    if not reference or reference == "بدون فاتورة":
        raise _error(400, "LEDGER_ADJUSTMENT_REFERENCE_INVALID", "The supplier inbound movement has no valid reference.")
    return original


async def _load_base_uom(
    db: AsyncSession,
    *,
    company_id: int,
    variant_id: int,
) -> tuple[int, str]:
    row = (
        await db.execute(
            select(ProductVariant.base_uom_id, UOM.code)
            .join(UOM, UOM.id == ProductVariant.base_uom_id)
            .where(
                ProductVariant.company_id == company_id,
                ProductVariant.id == variant_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise _error(409, "LEDGER_ADJUSTMENT_VARIANT_INVALID", "The inbound product variant is unavailable.")
    return int(row.base_uom_id), str(row.code)


async def _lock_scope(
    db: AsyncSession,
    *,
    company_id: int,
    variant_id: int,
    normalized_reference: str,
) -> None:
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                company_id,
                func.hashtext(f"inbound-adjust:{variant_id}:{normalized_reference}"),
            )
        )
    )


async def load_inbound_adjustment_state(
    db: AsyncSession,
    *,
    company_id: int,
    entry_id: int,
    lock: bool,
) -> InboundAdjustmentState:
    original = await _load_original(db, company_id=company_id, entry_id=entry_id)
    reference = (original.reference_id or "").strip()
    normalized_reference = reference.lower()

    if lock:
        await _lock_scope(
            db,
            company_id=company_id,
            variant_id=int(original.product_variant_id),
            normalized_reference=normalized_reference,
        )
        original = await _load_original(db, company_id=company_id, entry_id=entry_id)
        locked_reference = (original.reference_id or "").strip()
        if locked_reference.lower() != normalized_reference:
            raise _error(409, "LEDGER_ADJUSTMENT_SOURCE_CHANGED", "The inbound source changed while the correction was waiting for its lock.")

    base_uom_id, base_uom_code = await _load_base_uom(
        db,
        company_id=company_id,
        variant_id=int(original.product_variant_id),
    )

    supplier_movements = list(
        (
            await db.scalars(
                select(InventoryMovement)
                .where(
                    InventoryMovement.company_id == company_id,
                    InventoryMovement.product_variant_id == original.product_variant_id,
                    InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                    func.lower(func.trim(InventoryMovement.reference_id)) == normalized_reference,
                )
                .order_by(InventoryMovement.id.asc())
            )
        ).all()
    )
    if not supplier_movements:
        raise _error(409, "LEDGER_ADJUSTMENT_SOURCE_CHAIN_MISSING", "The original inbound movement chain is unavailable.")

    batch_ids = {movement.batch_id for movement in supplier_movements}
    destination_ids = {movement.destination_location_id for movement in supplier_movements}
    if len(batch_ids) != 1:
        raise _error(409, "LEDGER_ADJUSTMENT_MULTIPLE_BATCHES", "This reference contains multiple batches for the same product.")
    if len(destination_ids) != 1 or None in destination_ids:
        raise _error(409, "LEDGER_ADJUSTMENT_DESTINATION_AMBIGUOUS", "The original inbound chain has an ambiguous warehouse destination.")

    batch_id = next(iter(batch_ids))
    warehouse_location_id = int(next(iter(destination_ids)))
    location_exists = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == warehouse_location_id,
            InventoryLocation.location_type == "WAREHOUSE",
        )
    )
    if location_exists is None:
        raise _error(409, "LEDGER_ADJUSTMENT_DESTINATION_INVALID", "The authoritative inbound warehouse is unavailable.")

    for movement in supplier_movements:
        if (
            movement.movement_kind != "PHYSICAL"
            or movement.source_location_id is not None
            or movement.destination_location_id != warehouse_location_id
            or movement.destination_stock_status != "AVAILABLE"
            or movement.batch_id != batch_id
        ):
            raise _error(409, "LEDGER_ADJUSTMENT_SOURCE_CHAIN_INCONSISTENT", "The original inbound movement chain is inconsistent.")

    invoice_movements = list(
        (
            await db.scalars(
                select(InventoryMovement)
                .where(
                    InventoryMovement.company_id == company_id,
                    InventoryMovement.product_variant_id == original.product_variant_id,
                    InventoryMovement.batch_id == batch_id,
                    InventoryMovement.reference_type.in_(["INBOUND_SUPPLIER", "INBOUND_CORRECTION"]),
                    func.lower(func.trim(InventoryMovement.reference_id)) == normalized_reference,
                )
                .order_by(InventoryMovement.id.asc())
            )
        ).all()
    )

    current_total = Decimal("0")
    for movement in invoice_movements:
        quantity = Decimal(movement.quantity)
        if quantity <= 0 or movement.movement_kind != "PHYSICAL":
            raise _error(409, "LEDGER_ADJUSTMENT_CHAIN_INCONSISTENT", "The inbound correction chain contains an invalid movement.")
        if movement.reference_type == "INBOUND_SUPPLIER":
            if (
                movement.source_location_id is not None
                or movement.destination_location_id != warehouse_location_id
                or movement.destination_stock_status != "AVAILABLE"
            ):
                raise _error(409, "LEDGER_ADJUSTMENT_CHAIN_INCONSISTENT", "The inbound movement chain is inconsistent.")
            current_total += quantity
            continue

        positive = (
            movement.source_location_id is None
            and movement.destination_location_id == warehouse_location_id
            and movement.destination_stock_status == "AVAILABLE"
            and movement.source_stock_status is None
        )
        negative = (
            movement.source_location_id == warehouse_location_id
            and movement.destination_location_id is None
            and movement.source_stock_status == "AVAILABLE"
            and movement.destination_stock_status is None
        )
        if positive:
            current_total += quantity
        elif negative:
            current_total -= quantity
        else:
            raise _error(409, "LEDGER_ADJUSTMENT_CHAIN_INCONSISTENT", "The inbound correction chain is inconsistent.")

    if current_total < 0:
        raise _error(409, "LEDGER_ADJUSTMENT_NEGATIVE_HISTORY", "The authoritative inbound net is negative.")

    return InboundAdjustmentState(
        entry_id=int(original.id),
        reference=reference,
        normalized_reference=normalized_reference,
        product_variant_id=int(original.product_variant_id),
        batch_id=int(batch_id) if batch_id is not None else None,
        warehouse_location_id=warehouse_location_id,
        current_total_quantity=current_total,
        base_uom_id=base_uom_id,
        base_uom_code=base_uom_code,
    )


async def apply_inbound_adjustment(
    db: AsyncSession,
    *,
    company_id: int,
    entry_id: int,
    actor_id: int,
    new_total_quantity: Decimal,
    uom_id: int,
    notes: str | None,
) -> tuple[InboundAdjustmentState, Decimal, int | None]:
    if new_total_quantity < 0:
        raise _error(400, "LEDGER_ADJUSTMENT_NEGATIVE_TOTAL", "The requested inbound total cannot be negative.")

    state = await load_inbound_adjustment_state(
        db,
        company_id=company_id,
        entry_id=entry_id,
        lock=True,
    )
    if int(uom_id) != state.base_uom_id:
        raise _error(
            422,
            "UOM_MISMATCH",
            "The correction must use the product base UOM.",
            expected_uom_id=state.base_uom_id,
        )

    delta = Decimal(new_total_quantity) - state.current_total_quantity
    if delta == 0:
        return state, delta, None

    idempotency_raw = (
        f"{company_id}|{state.normalized_reference}|{state.product_variant_id}|"
        f"{state.batch_id or 0}|{canonical_quantity(state.current_total_quantity)}|"
        f"{canonical_quantity(new_total_quantity)}"
    )
    idempotency_key = "ADJ-" + hashlib.sha256(idempotency_raw.encode("utf-8")).hexdigest()
    correction_notes = f"Supplier inbound correction: {notes}" if notes else "Supplier inbound correction"

    correction = await apply_inventory_movement(
        db,
        company_id=company_id,
        performed_by=actor_id,
        product_variant_id=state.product_variant_id,
        batch_id=state.batch_id,
        quantity=abs(delta),
        movement_kind="PHYSICAL",
        reference_type="INBOUND_CORRECTION",
        reference_id=state.reference,
        idempotency_key=idempotency_key,
        source_location_id=state.warehouse_location_id if delta < 0 else None,
        destination_location_id=state.warehouse_location_id if delta > 0 else None,
        source_stock_status="AVAILABLE" if delta < 0 else None,
        destination_stock_status="AVAILABLE" if delta > 0 else None,
        notes=correction_notes,
    )

    db.add(
        SystemAuditLog(
            company_id=company_id,
            admin_id=actor_id,
            target_id=f"InventoryMovement_{correction.id}",
            action_type="INBOUND_ADJUSTMENT",
            old_value=json.dumps(
                {
                    "reference": state.reference,
                    "product_variant_id": state.product_variant_id,
                    "batch_id": state.batch_id,
                    "total_quantity": canonical_quantity(state.current_total_quantity),
                    "uom_id": state.base_uom_id,
                },
                ensure_ascii=False,
            ),
            new_value=json.dumps(
                {
                    "total_quantity": canonical_quantity(new_total_quantity),
                    "delta": canonical_quantity(delta),
                    "uom_id": state.base_uom_id,
                },
                ensure_ascii=False,
            ),
        )
    )
    return state, delta, int(correction.id)
