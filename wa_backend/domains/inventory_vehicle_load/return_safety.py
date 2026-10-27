"""Shared Vehicle-return safety; extracted without changing Vehicle Load semantics."""
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import ProductVariant
from domains.vehicles.contracts import VehicleError
from services import resolve_inflight_transfer_destination_statuses


def _error(code, message, *, status_code=409, **context):
    return VehicleError(code, message, status_code=status_code, context=context)


def _preserve_or_tighten_unload_status(
    source_status: str,
    current_safe_status: str,
) -> str:
    """Never make Vehicle custody more sellable while unloading it."""
    source = str(source_status or "").strip().upper()
    safe = str(current_safe_status or "").strip().upper()
    if source in {"DAMAGED", "DISPOSAL_PENDING"}:
        return source
    if safe == "RECALLED" or source == "RECALLED":
        return "RECALLED"
    if safe == "BLOCKED" or source == "BLOCKED":
        return "BLOCKED"
    if safe == "QUARANTINED" or source == "QUARANTINED":
        return "QUARANTINED"
    return "AVAILABLE"


async def _safe_unload_terminal_statuses(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_id: int,
    allocations: list[dict],
) -> dict[int, str]:
    """Reuse the canonical in-flight safety resolver for direct Vehicle cleanup.

    Direct Vehicle unload has no TransferHeader/Line document, so we provide the
    resolver only the immutable-shaped evidence it requires. Creation evidence
    is the current locked Product lifecycle revision: the operation starts and
    finishes in this same transaction, while the resolver owns Batch/shelf-life
    and current safety precedence.
    """
    if not allocations:
        return {}

    variant_ids = sorted({
        int(item["product_variant_id"])
        for item in allocations
    })
    variant_rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
                ProductVariant.lifecycle_revision,
            ).where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id.in_(variant_ids),
            )
        )
    ).all()
    variants = {int(row.id): row for row in variant_rows}
    if set(variants) != set(variant_ids):
        raise _error(
            "VEHICLE_LOAD_PRODUCT_NOT_FOUND",
            "أحد أصناف عهدة السيارة لم يعد موجوداً داخل الشركة.",
            status_code=409,
        )

    lines = []
    for index, item in enumerate(allocations, start=1):
        variant = variants[int(item["product_variant_id"])]
        lines.append(SimpleNamespace(
            id=index,
            product_variant_id=int(item["product_variant_id"]),
            batch_id=int(item["batch_id"]),
            source_stock_status=str(item["stock_status"]),
            lifecycle_revision_snapshot=int(variant.lifecycle_revision),
            lifecycle_status_snapshot=str(variant.lifecycle_status),
            operational_hold_snapshot=str(variant.operational_hold),
        ))

    resolved = await resolve_inflight_transfer_destination_statuses(
        db,
        company_id=int(company_id),
        destination_location_id=int(warehouse_id),
        transfer_purpose="WAREHOUSE_BALANCING",
        lines=lines,
    )
    return {
        index: _preserve_or_tighten_unload_status(
            str(allocations[index - 1]["stock_status"]),
            resolved[index],
        )
        for index in resolved
    }


preserve_or_tighten_unload_status = _preserve_or_tighten_unload_status
safe_unload_terminal_statuses = _safe_unload_terminal_statuses
