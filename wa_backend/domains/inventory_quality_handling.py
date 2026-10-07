from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryTransferHeader, InventoryTransferLine
from services import InventoryMutationError, apply_inventory_movements_batch


QUALITY_STAGE_REFERENCE_PREFIX = "QSTG-"


def quality_stage_target_status(purpose: str, source_status: str) -> str:
    normalized_purpose = str(purpose or "").strip().upper()
    normalized_status = str(source_status or "").strip().upper()
    if normalized_purpose == "DISPOSAL":
        return "DISPOSAL_PENDING"
    if normalized_purpose == "RETURN_TO_VENDOR":
        if normalized_status in {"QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED"}:
            return normalized_status
        if normalized_status == "AVAILABLE":
            return "QUARANTINED"
    raise InventoryMutationError("Quality handling stage is not valid for this stock state.")


async def stage_quality_handling_direct(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    source_location_id: int,
    destination_location_id: int,
    transfer_purpose: str,
    tenant_policy_id: int,
    tenant_policy_revision: int,
    source_location_type: str,
    destination_location_type: str,
    source_lines: list[dict[str, Any]],
    notes: str,
) -> dict[str, Any]:
    """Stage disposal/vendor handling atomically without a user-visible transit leg.

    destination_location_id is immutable policy evidence. Whole-product in-place
    handling may intentionally set it to the physical source; stock remains at
    the source and only its status changes until the terminal action is confirmed.
    """
    purpose = str(transfer_purpose or "").strip().upper()
    if purpose not in {"DISPOSAL", "RETURN_TO_VENDOR"}:
        raise InventoryMutationError("Unsupported quality handling purpose.")
    if not source_lines:
        raise InventoryMutationError("Quality handling stage requires stock lines.")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    transfer_ref = f"{QUALITY_STAGE_REFERENCE_PREFIX}{uuid.uuid4().hex.upper()}"
    header = InventoryTransferHeader(
        company_id=company_id,
        reference_number=transfer_ref,
        source_location_id=source_location_id,
        destination_location_id=destination_location_id,
        transit_location_id=None,
        workflow_type="DIRECT",
        status="POSTED",
        transfer_purpose=purpose,
        commercial_context={
            "schema_version": 1,
            "quality_stage_v1": True,
            "tenant_policy_id": int(tenant_policy_id),
            "tenant_policy_revision": int(tenant_policy_revision),
            "source_location_type": str(source_location_type),
            "destination_location_type": str(destination_location_type),
            "transfer_purpose": purpose,
        },
        tenant_policy_id=int(tenant_policy_id),
        tenant_policy_revision=int(tenant_policy_revision),
        dispatched_by=actor_id,
        posted_at=now_utc,
        notes=notes,
    )
    db.add(header)
    await db.flush()

    transfer_lines: list[InventoryTransferLine] = []
    movement_specs: list[dict[str, Any]] = []
    for line_no, line in enumerate(source_lines, start=1):
        source_status = str(line["source_stock_status"]).upper()
        target_status = quality_stage_target_status(purpose, source_status)
        transfer_lines.append(InventoryTransferLine(
            company_id=company_id,
            transfer_header_id=header.id,
            product_variant_id=line["product_variant_id"],
            batch_id=line["batch_id"],
            quantity=line["quantity"],
            source_stock_status=source_status,
            lifecycle_revision_snapshot=line["lifecycle_revision_snapshot"],
            lifecycle_status_snapshot=line["lifecycle_status_snapshot"],
            operational_hold_snapshot=line["operational_hold_snapshot"],
            fefo_override_reason_id=None,
            fefo_overridden_by=None,
            fefo_override_note=None,
        ))
        if target_status != source_status:
            movement_specs.append({
                "product_variant_id": line["product_variant_id"],
                "batch_id": line["batch_id"],
                "quantity": line["quantity"],
                "movement_kind": "STATUS_CHANGE",
                "reference_type": "QUALITY_HANDLING_STAGE",
                "reference_id": transfer_ref,
                "idempotency_key": f"QSTG-STATUS-{header.id}-{line_no}",
                "source_location_id": source_location_id,
                "destination_location_id": source_location_id,
                "source_stock_status": source_status,
                "destination_stock_status": target_status,
                "transfer_header_id": header.id,
                "notes": notes,
            })

    db.add_all(transfer_lines)
    if movement_specs:
        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=actor_id,
            movements=movement_specs,
        )

    return {
        "header_id": int(header.id),
        "transfer_reference": transfer_ref,
        "transfer_purpose": purpose,
        "source_location_id": int(source_location_id),
        "destination_location_id": int(destination_location_id),
        "tenant_policy_id": int(tenant_policy_id),
        "tenant_policy_revision": int(tenant_policy_revision),
    }
