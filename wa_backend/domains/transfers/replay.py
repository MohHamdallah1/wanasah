"""Reauthorize saved results using current tenant-scoped document authority."""
from fastapi import HTTPException
from sqlalchemy import select

from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected,
)
from models import InventoryTransferHeader, TenantOperationalPolicy
from services import SPECIAL_TRANSFER_DESTINATION_POLICY_KEY, SPECIAL_TRANSFER_PERMISSION, TRANSFER_DESTINATION_POLICY_CODE, load_published_transfer_destination_policy


async def require_transfer_replay(access: BackofficeCapabilityAccess, header_id: int, *, destination: bool = False) -> None:
    row = (await access.db.execute(
        select(InventoryTransferHeader.transfer_purpose, InventoryTransferHeader.destination_location_id).where(
            InventoryTransferHeader.company_id == access.company_id,
            InventoryTransferHeader.id == header_id,
        )
    )).one_or_none()
    if row is None:
        raise HTTPException(404, detail={"code": "TRANSFER_NOT_FOUND", "context": {}})
    purpose, destination_id = row
    if destination:
        await _require_destination(access, int(destination_id))
    permission = SPECIAL_TRANSFER_PERMISSION.get(str(purpose).upper())
    if permission is not None:
        try:
            await access.require(permission)
        except BackofficeCapabilityAccessRejected:
            raise HTTPException(403, detail={"code": "TRANSFER_CAPABILITY_REQUIRED", "context": {}}) from None


async def policy_reference_payload(access: BackofficeCapabilityAccess, policy_id: int) -> dict:
    payload = await access.db.scalar(
        select(TenantOperationalPolicy.validated_payload).where(
            TenantOperationalPolicy.company_id == access.company_id,
            TenantOperationalPolicy.id == policy_id,
            TenantOperationalPolicy.policy_code == TRANSFER_DESTINATION_POLICY_CODE,
        )
    )
    if payload is None:
        raise HTTPException(404, detail={"code": "TRANSFER_POLICY_DRAFT_NOT_FOUND", "context": {}})
    return dict(payload)


async def _require_destination(access: BackofficeCapabilityAccess, location_id: int) -> None:
    try:
        await access.require("transfer.destination", location_id)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(403, detail={"code": "TRANSFER_CAPABILITY_REQUIRED", "context": {}}) from None


async def require_special_destination(
    access: BackofficeCapabilityAccess,
    purpose: str,
    *,
    source_location_id: int | None = None,
) -> None:
    _, payload = await load_published_transfer_destination_policy(
        access.db, company_id=access.company_id, revalidate_locations=False,
    )
    key = SPECIAL_TRANSFER_DESTINATION_POLICY_KEY[purpose]
    destination_id = payload[key]
    if destination_id is None:
        if source_location_id is None:
            raise HTTPException(
                409,
                detail={"code": "TRANSFER_POLICY_STALE", "context": {}},
            )
        destination_id = source_location_id
    await _require_destination(access, int(destination_id))
