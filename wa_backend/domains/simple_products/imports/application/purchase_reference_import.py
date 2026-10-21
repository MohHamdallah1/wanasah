"""Bounded, atomic purchase-reference writer for Product Import.

Runs only when at least one validated row contains optional purchase cost.
No changes to import staging, row locks, 200-row batching or worker scheduling.
The owning Product Import transaction commits Product/Pricing/reference/audit once.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import insert, select

from models import Company, UOM
from domains.inventory_costing.purchase_reference.models import (
    PurchaseCostReference, PurchaseReferenceChange, PurchaseReferenceCommand,
)
from domains.inventory_costing.purchase_reference.values import currency_value


def has_import_cost(rows) -> bool:
    return any((row.normalized_data or {}).get("purchase_unit_cost") is not None for row in rows)


async def record_import_reference_batch(
    db, *, access, company_id: int, job_id, request_id, request_hash, rows, created,
) -> None:
    """Store at most 200 explicit base-unit references with 3 bulk inserts.

    Caller must acquire reference writer guard before Product and Pricing locks.
    Caller checks MANAGE authorization before starting Product creation.
    Absent reference values cause no I/O; no silent inferred historical cost.
    """
    selected = [
        (row, result[0])
        for row, result in zip(rows, created, strict=True)
        if (row.normalized_data or {}).get("purchase_unit_cost") is not None
    ]
    if not selected:
        return
    if len(selected) > 200 or access.company_id != company_id:
        raise ValueError("Invalid bounded import reference scope")
    base_id = await db.scalar(select(UOM.id).where(UOM.code == "EACH"))
    company_currency = await db.scalar(select(Company.currency_code).where(Company.id == company_id))
    if base_id is None or company_currency is None:
        raise ValueError("Purchase cost reference UOM/currency is unavailable")
    currency = currency_value(company_currency)
    timestamp = datetime.now(timezone.utc)
    command = dict(
        company_id=company_id, request_id=request_id, operation="PRODUCT_IMPORT_SET",
        actor_principal_id=access.subject.principal_id,
        actor_backoffice_user_id=access.subject.backoffice_user_id,
        request_hash=request_hash,
        response_json={"job_id": str(job_id), "count": len(selected)},
        created_at=timestamp,
    )
    current, changes = [], []
    for row, variant in selected:
        if int(variant.company_id) != company_id or int(variant.base_uom_id) != int(base_id):
            raise ValueError("New Product Import variant has unexpected base UOM / company")
        amount = Decimal(str(row.normalized_data["purchase_unit_cost"]))
        payload = dict(
            company_id=company_id, product_variant_id=int(variant.id),
            revision=1, amount=amount, purchase_uom_id=int(base_id),
            base_uom_id=int(base_id), factor_numerator=1, factor_denominator=1,
            currency_code=currency, source="PRODUCT_IMPORT",
            source_cost_event_id=None,
            provenance={"operation": "PRODUCT_IMPORT_ROW_CREATE",
                        "job_id": str(job_id), "request_id": str(request_id),
                        "source_row_id": int(row.id)},
            changed_at=timestamp,
        )
        current.append(payload)
        changes.append({**payload, "request_id": request_id, "before_snapshot": None})
    # Preserve command->history audit attribution and deferred current->history
    # FK, all inside the already-owned Import row-creation transaction.
    await db.execute(insert(PurchaseReferenceCommand).values(command))
    await db.execute(insert(PurchaseCostReference).values(current))
    await db.execute(insert(PurchaseReferenceChange).values(changes))
