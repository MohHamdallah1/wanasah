"""Conservative current-stock Supplier provenance for terminal inventory actions.

Never guesses a Supplier from the newest receipt. FIFO can identify exact remaining
Supplier quantities through live cost layers. Other costing modes fall back to a
safe historical rule: auto-resolve only when every external acquisition is
Supplier-tagged and all such acquisitions belong to one Supplier.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Mapping

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory_supplier_evidence import InventorySupplierEvidence
from models import InventoryCostEvent, InventoryCostLayer, InventoryMovement


SupplierResolutionStatus = Literal["SINGLE", "MULTIPLE", "UNKNOWN"]


@dataclass(frozen=True)
class SupplierStockCandidate:
    supplier_id: int
    supplier_name: str
    supplier_code: str | None
    quantity: Decimal | None


@dataclass(frozen=True)
class SupplierStockResolution:
    status: SupplierResolutionStatus
    candidates: tuple[SupplierStockCandidate, ...]
    quantities_exact: bool


def _candidate(
    supplier_id: int,
    supplier_name: str,
    supplier_code: str | None,
    quantity: Decimal | None,
) -> SupplierStockCandidate:
    return SupplierStockCandidate(
        supplier_id=int(supplier_id),
        supplier_name=str(supplier_name),
        supplier_code=str(supplier_code) if supplier_code is not None else None,
        quantity=quantity,
    )


async def resolve_current_stock_suppliers(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    current_batches: Mapping[int, Decimal],
) -> SupplierStockResolution:
    """Resolve current-stock Supplier provenance without historical guesswork."""
    normalized_batches = {
        int(batch_id): Decimal(quantity)
        for batch_id, quantity in current_batches.items()
        if Decimal(quantity) > 0
    }
    total_quantity = sum(normalized_batches.values(), Decimal("0"))
    if total_quantity <= 0:
        return SupplierStockResolution("UNKNOWN", (), False)

    layer_rows = (
        await db.execute(
            select(
                InventoryCostLayer.remaining_quantity,
                InventorySupplierEvidence.supplier_id,
                InventorySupplierEvidence.supplier_name,
                InventorySupplierEvidence.supplier_code,
            )
            .join(
                InventoryCostEvent,
                and_(
                    InventoryCostEvent.company_id == InventoryCostLayer.company_id,
                    InventoryCostEvent.id == InventoryCostLayer.source_cost_event_id,
                ),
            )
            .outerjoin(
                InventorySupplierEvidence,
                and_(
                    InventorySupplierEvidence.company_id == InventoryCostEvent.company_id,
                    InventorySupplierEvidence.movement_id == InventoryCostEvent.inventory_movement_id,
                ),
            )
            .where(
                InventoryCostLayer.company_id == company_id,
                InventoryCostLayer.product_variant_id == product_variant_id,
                InventoryCostLayer.remaining_quantity > 0,
            )
            .order_by(InventoryCostLayer.created_at.asc(), InventoryCostLayer.id.asc())
        )
    ).all()

    if layer_rows:
        layer_quantity = sum(
            (Decimal(row.remaining_quantity or 0) for row in layer_rows),
            Decimal("0"),
        )
        if layer_quantity == total_quantity and all(row.supplier_id is not None for row in layer_rows):
            grouped: dict[int, list] = {}
            for row in layer_rows:
                supplier_id = int(row.supplier_id)
                current = grouped.get(supplier_id)
                if current is None:
                    grouped[supplier_id] = [
                        str(row.supplier_name),
                        str(row.supplier_code) if row.supplier_code is not None else None,
                        Decimal(row.remaining_quantity or 0),
                    ]
                else:
                    current[0] = str(row.supplier_name)
                    current[1] = str(row.supplier_code) if row.supplier_code is not None else None
                    current[2] += Decimal(row.remaining_quantity or 0)
            candidates = tuple(
                _candidate(supplier_id, values[0], values[1], values[2])
                for supplier_id, values in sorted(grouped.items())
            )
            return SupplierStockResolution(
                "SINGLE" if len(candidates) == 1 else "MULTIPLE",
                candidates,
                True,
            )
        # Existing live layers that do not fully and Supplier-safely explain current
        # stock are stronger evidence of ambiguity than old receipt history.
        return SupplierStockResolution("UNKNOWN", (), False)

    acquisition_rows = (
        await db.execute(
            select(
                InventoryMovement.batch_id,
                InventorySupplierEvidence.supplier_id,
                InventorySupplierEvidence.supplier_name,
                InventorySupplierEvidence.supplier_code,
            )
            .outerjoin(
                InventorySupplierEvidence,
                and_(
                    InventorySupplierEvidence.company_id == InventoryMovement.company_id,
                    InventorySupplierEvidence.movement_id == InventoryMovement.id,
                ),
            )
            .where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.product_variant_id == product_variant_id,
                InventoryMovement.batch_id.in_(sorted(normalized_batches)),
                InventoryMovement.movement_kind == "PHYSICAL",
                InventoryMovement.source_location_id.is_(None),
                InventoryMovement.destination_location_id.is_not(None),
            )
            .order_by(InventoryMovement.created_at.asc(), InventoryMovement.id.asc())
        )
    ).all()
    if not acquisition_rows or any(row.supplier_id is None for row in acquisition_rows):
        return SupplierStockResolution("UNKNOWN", (), False)

    suppliers_by_batch: dict[int, dict[int, tuple[str, str | None]]] = {
        batch_id: {} for batch_id in normalized_batches
    }
    for row in acquisition_rows:
        batch_id = int(row.batch_id)
        suppliers_by_batch.setdefault(batch_id, {})[int(row.supplier_id)] = (
            str(row.supplier_name),
            str(row.supplier_code) if row.supplier_code is not None else None,
        )
    if any(not suppliers_by_batch.get(batch_id) for batch_id in normalized_batches):
        return SupplierStockResolution("UNKNOWN", (), False)

    identity: dict[int, tuple[str, str | None]] = {}
    exact_quantities: dict[int, Decimal] = {}
    quantities_exact = True
    for batch_id, suppliers in suppliers_by_batch.items():
        for supplier_id, snapshot in suppliers.items():
            identity[supplier_id] = snapshot
        if len(suppliers) == 1:
            supplier_id = next(iter(suppliers))
            exact_quantities[supplier_id] = exact_quantities.get(supplier_id, Decimal("0")) + normalized_batches[batch_id]
        else:
            quantities_exact = False

    candidates = tuple(
        _candidate(
            supplier_id,
            snapshot[0],
            snapshot[1],
            exact_quantities.get(supplier_id) if quantities_exact else None,
        )
        for supplier_id, snapshot in sorted(identity.items())
    )
    if not candidates:
        return SupplierStockResolution("UNKNOWN", (), False)
    return SupplierStockResolution(
        "SINGLE" if len(candidates) == 1 else "MULTIPLE",
        candidates,
        quantities_exact,
    )
