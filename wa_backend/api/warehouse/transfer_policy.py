from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Driver, TenantOperationalPolicy
from schemas import (
    TransferDestinationPolicyMutationResponse,
    TransferDestinationPolicyPublishRequest,
    TransferDestinationPolicySaveRequest,
    TransferDestinationPolicyStateResponse,
)
from services import (
    InventoryMutationError,
    InventoryRuleError,
    begin_idempotent_operation,
    complete_idempotent_operation,
    get_transfer_destination_policy_state,
    inventory_business_error,
    publish_transfer_destination_policy,
    save_transfer_destination_policy_draft,
)

# Staging-only dependency: remains sourced from the untouched monolith until
# _stable_request_hash is moved once to _shared.py in its dedicated stage.
from api.warehouse import _stable_request_hash


router = APIRouter()


# ====================================================
# 9. سياسة وجهات التحويل التشغيلية
# ====================================================
# STAGE4E2A_TRANSFER_POLICY_GUARD
_TRANSFER_POLICY_VALIDATION_CODES = frozenset({
    "TRANSFER_POLICY_PAYLOAD_INVALID",
    "TRANSFER_POLICY_LOCATION_INVALID",
    "TRANSFER_POLICY_LOCATION_TYPE_INVALID",
})


# ====================================================
# 9.1 تحويل سجل سياسة وجهات التحويل إلى عقد الاستجابة
# ====================================================
def _transfer_policy_to_payload(policy: Optional[TenantOperationalPolicy]):
    if policy is None:
        return None
    return {
        "id": int(policy.id),
        "policy_code": str(policy.policy_code),
        "schema_version": int(policy.schema_version),
        "revision": int(policy.revision),
        "validated_payload": dict(policy.validated_payload or {}),
        "status": str(policy.status),
        "effective_from": (
            policy.effective_from.isoformat()
            if policy.effective_from is not None
            else None
        ),
        "effective_to": (
            policy.effective_to.isoformat()
            if policy.effective_to is not None
            else None
        ),
        "approved_by": (
            int(policy.approved_by)
            if policy.approved_by is not None
            else None
        ),
        "approved_at": (
            policy.approved_at.isoformat()
            if policy.approved_at is not None
            else None
        ),
        "created_by": int(policy.created_by),
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


# ====================================================
# 9.2 التحقق من صلاحية قراءة المواقع المشار إليها في السياسة
# ====================================================
async def _require_transfer_policy_location_access(
    access: InventoryAccess,
    validated_payload: dict,
) -> None:
    location_ids = sorted({
        int(validated_payload["quarantine_location_id"]),
        int(validated_payload["disposal_location_id"]),
        int(validated_payload["vendor_return_staging_location_id"]),
    })
    for location_id in location_ids:
        # Policy administration itself is company-scoped; referenced locations
        # must still be visible to the actor through the normal location ACL.
        await access.require(
            "location.read",
            location_id,
        )


# ====================================================
# 9.3 جلب حالة سياسة وجهات التحويل Draft والمنشورة
# ====================================================
@router.get(
    "/warehouse/operational-policy/transfer-destinations",
    response_model=TransferDestinationPolicyStateResponse,
    status_code=200,
)
async def get_transfer_destination_policy(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.transfer_policy.manage", any_location=True)

    try:
        draft, published = await get_transfer_destination_policy_state(
            db,
            company_id=current_admin.company_id,
        )
        return {
            "draft": _transfer_policy_to_payload(draft),
            "published": _transfer_policy_to_payload(published),
        }
    except InventoryMutationError as exc:
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_READ_FAILED",
                str(exc),
            ),
        ) from exc


# ====================================================
# 9.4 حفظ Draft سياسة وجهات التحويل مع التحقق وidempotency
# ====================================================
@router.put(
    "/warehouse/operational-policy/transfer-destinations/draft",
    response_model=TransferDestinationPolicyMutationResponse,
    status_code=200,
)
async def save_transfer_destination_policy(
    payload: TransferDestinationPolicySaveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.transfer_policy.manage", any_location=True)
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="TRANSFER_DESTINATION_POLICY_DRAFT_SAVE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        policy = await save_transfer_destination_policy_draft(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            payload=payload.payload.model_dump(mode="python"),
        )
        await _require_transfer_policy_location_access(
            access,
            dict(policy.validated_payload),
        )

        response = {
            "message": "تم حفظ Draft سياسة وجهات التحويل بعد التحقق الصارم من المواقع.",
            "policy": _transfer_policy_to_payload(policy),
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response

    except InventoryRuleError as exc:
        await db.rollback()
        status_code = (
            400
            if exc.code in _TRANSFER_POLICY_VALIDATION_CODES
            else 409
        )
        raise HTTPException(
            status_code=status_code,
            detail=exc.as_detail(),
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_SAVE_REJECTED",
                str(exc),
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_CONFLICT",
                "حدث تعارض متزامن أثناء حفظ السياسة.",
            ),
        ) from exc


# ====================================================
# 9.5 نشر سياسة وجهات التحويل بعد إعادة التحقق من المواقع
# ====================================================
@router.post(
    "/warehouse/operational-policy/transfer-destinations/{policy_id}/publish",
    response_model=TransferDestinationPolicyMutationResponse,
    status_code=200,
)
async def publish_transfer_destination_policy_endpoint(
    policy_id: int,
    payload: TransferDestinationPolicyPublishRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.transfer_policy.manage", any_location=True)
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(
            payload,
            context={"policy_id": int(policy_id)},
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="TRANSFER_DESTINATION_POLICY_PUBLISH",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        policy = await publish_transfer_destination_policy(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            policy_id=policy_id,
            expected_revision=payload.expected_revision,
            request_id=payload.request_id,
        )
        await _require_transfer_policy_location_access(
            access,
            dict(policy.validated_payload),
        )

        response = {
            "message": "تم نشر سياسة وجهات التحويل بعد إعادة التحقق من المواقع.",
            "policy": _transfer_policy_to_payload(policy),
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response

    except InventoryRuleError as exc:
        await db.rollback()
        if exc.code in _TRANSFER_POLICY_VALIDATION_CODES:
            status_code = 400
        elif exc.code == "TRANSFER_POLICY_DRAFT_NOT_FOUND":
            status_code = 404
        else:
            status_code = 409
        raise HTTPException(
            status_code=status_code,
            detail=exc.as_detail(),
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_PUBLISH_REJECTED",
                str(exc),
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_CONFLICT",
                "حدث تعارض متزامن أثناء نشر السياسة.",
            ),
        ) from exc


# =================================================================================
# [المرحلة الرابعة والخامسة] المحرك الموحد للحوالات ونظام الصلاحية (FEFO & IN_TRANSIT)
# =================================================================================
