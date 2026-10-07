from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.inventory_quality_handling import (
    quality_stage_target_status,
    stage_quality_handling_direct,
)
from domains.inventory_terminal_quality import confirm_final_disposal
from domains.inventory_terminal_vendor import confirm_vendor_handover
from domains.inventory_whole_product_quality_policy import ensure_whole_product_quality_policy
from inventory_access import InventoryAccess
from models import Driver, InventoryBalance, InventoryLocation, ProductVariant, SystemAuditLog
from product_lifecycle import acquire_product_lifecycle_guards
from quantity import canonical_quantity
from schemas import SpecialTransferItem
from services import (
    InventoryMutationError,
    InventoryRuleError,
    SPECIAL_TRANSFER_PERMISSION,
    acquire_inventory_location_guards,
    begin_idempotent_operation,
    complete_idempotent_operation,
    get_company_local_date,
    inventory_business_error,
    validate_special_transfer_source_items_locked,
)

from ._shared import _stable_request_hash


router = APIRouter()
_MAX_WHOLE_PRODUCT_LINES = 5000
_MAX_WHOLE_PRODUCT_LOCATIONS = 100


class WholeProductQualityResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    action: Literal["DISPOSE", "RETURN_TO_VENDOR"]
    reason: str = Field(..., min_length=1, max_length=1000)
    disposal_method: str | None = Field(default=None, max_length=200)
    evidence_reference: str | None = Field(default=None, max_length=500)
    recipient_name: str | None = Field(default=None, max_length=300)
    handover_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_action_evidence(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason is required")
        if self.action == "RETURN_TO_VENDOR":
            self.recipient_name = (self.recipient_name or "").strip() or None
            self.handover_reference = (self.handover_reference or "").strip() or None
            if self.recipient_name is None or self.handover_reference is None:
                raise ValueError("recipient_name and handover_reference are required for vendor return")
        return self


class WholeProductQualityLocationResult(BaseModel):
    location_id: int
    location_name: str
    quantity: str


class WholeProductQualityResolveResponse(BaseModel):
    message: str
    action: Literal["DISPOSE", "RETURN_TO_VENDOR"]
    product_variant_id: int
    total_quantity: str
    location_count: int
    locations: list[WholeProductQualityLocationResult]


def _business_detail(code: str, message: str, *, context: dict | None = None):
    return inventory_business_error(code, message, context=context or {})


@router.post(
    "/warehouse/quality/products/{product_variant_id}/resolve-all",
    response_model=WholeProductQualityResolveResponse,
    status_code=200,
)
async def resolve_whole_product_quality(
    product_variant_id: int,
    payload: WholeProductQualityResolveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    company_id = int(current_admin.company_id)
    actor_id = int(current_admin.id)
    purpose = "DISPOSAL" if payload.action == "DISPOSE" else "RETURN_TO_VENDOR"
    terminal_permission = (
        "inventory.disposal.confirm"
        if payload.action == "DISPOSE"
        else "inventory.vendor_return.confirm"
    )

    access = InventoryAccess(db, current_admin)
    await access.require(SPECIAL_TRANSFER_PERMISSION[purpose])

    try:
        request_hash = _stable_request_hash(
            payload,
            context={"product_variant_id": int(product_variant_id)},
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="WHOLE_PRODUCT_QUALITY_RESOLVE_ALL",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        await acquire_product_lifecycle_guards(
            db,
            company_id,
            [int(product_variant_id)],
            exclusive=True,
        )
        variant = (
            await db.execute(
                select(ProductVariant.id, ProductVariant.base_uom_id, ProductVariant.operational_hold).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id == int(product_variant_id),
                )
            )
        ).one_or_none()
        if variant is None:
            raise HTTPException(status_code=404, detail="المنتج غير موجود أو لا يتبع شركتك.")
        if str(variant.operational_hold or "").upper() != "RECALL":
            raise HTTPException(
                status_code=409,
                detail=_business_detail(
                    "PRODUCT_QUALITY_ISSUE_NOT_ACTIVE",
                    "لا توجد مشكلة جودة مفتوحة على المنتج بالكامل.",
                ),
            )

        rows = (
            await db.execute(
                select(
                    InventoryBalance,
                    InventoryLocation.name.label("location_name"),
                    InventoryLocation.location_type.label("location_type"),
                    InventoryLocation.is_active.label("location_active"),
                )
                .join(
                    InventoryLocation,
                    and_(
                        InventoryLocation.company_id == InventoryBalance.company_id,
                        InventoryLocation.id == InventoryBalance.location_id,
                    ),
                )
                .where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.product_variant_id == int(product_variant_id),
                    InventoryBalance.on_hand_quantity > 0,
                )
                .order_by(
                    InventoryBalance.location_id.asc(),
                    InventoryBalance.batch_id.asc(),
                    InventoryBalance.stock_status.asc(),
                )
                .limit(_MAX_WHOLE_PRODUCT_LINES + 1)
            )
        ).all()
        if len(rows) > _MAX_WHOLE_PRODUCT_LINES:
            raise HTTPException(
                status_code=409,
                detail=_business_detail(
                    "WHOLE_PRODUCT_QUALITY_CAPACITY_EXCEEDED",
                    "عدد سجلات المخزون المتأثرة أكبر من حد المعالجة الآمنة في عملية واحدة.",
                ),
            )
        if not rows:
            raise HTTPException(
                status_code=409,
                detail=_business_detail(
                    "WHOLE_PRODUCT_QUALITY_NO_STOCK",
                    "لا توجد كمية حالية لهذا المنتج لمعالجتها.",
                ),
            )

        unsupported = []
        reserved = []
        location_names: dict[int, str] = {}
        location_quantities: dict[int, Decimal] = defaultdict(Decimal)
        rows_by_location: dict[int, list[InventoryBalance]] = defaultdict(list)
        for balance, location_name, location_type, location_active in rows:
            location_id = int(balance.location_id)
            location_names[location_id] = str(location_name)
            location_quantities[location_id] += Decimal(balance.on_hand_quantity or 0)
            rows_by_location[location_id].append(balance)
            if str(location_type).upper() != "WAREHOUSE" or not bool(location_active):
                unsupported.append({
                    "location_id": location_id,
                    "location_name": str(location_name),
                    "location_type": str(location_type).upper(),
                    "active": bool(location_active),
                })
            if Decimal(balance.reserved_quantity or 0) > 0:
                reserved.append({
                    "location_id": location_id,
                    "location_name": str(location_name),
                    "quantity": canonical_quantity(Decimal(balance.reserved_quantity or 0)),
                })

        if unsupported:
            raise HTTPException(
                status_code=409,
                detail=_business_detail(
                    "WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER",
                    "يوجد جزء من الكمية خارج مستودع تشغيلي صالح. أعد عهدة المركبة أو أنهِ الحركة المعلقة أولاً.",
                    context={"locations": unsupported[:20]},
                ),
            )
        if reserved:
            raise HTTPException(
                status_code=409,
                detail=_business_detail(
                    "WHOLE_PRODUCT_QUALITY_RESERVED_STOCK",
                    "يوجد جزء من الكمية مرتبط بعملية تشغيلية. أنهِ الارتباط قبل معالجة المنتج بالكامل.",
                    context={"locations": reserved[:20]},
                ),
            )

        location_ids = sorted(rows_by_location)
        if len(location_ids) > _MAX_WHOLE_PRODUCT_LOCATIONS:
            raise HTTPException(
                status_code=409,
                detail=_business_detail(
                    "WHOLE_PRODUCT_QUALITY_LOCATION_CAPACITY_EXCEEDED",
                    "عدد المستودعات المتأثرة أكبر من حد العملية الواحدة.",
                ),
            )

        codes_by_location = await access.codes_by_location(location_ids)
        required_location_codes = {"inventory.read", "transfer.send", terminal_permission}
        denied = [
            {
                "location_id": location_id,
                "location_name": location_names[location_id],
            }
            for location_id in location_ids
            if not required_location_codes.issubset(set(codes_by_location.get(location_id, ())))
        ]
        if denied:
            raise HTTPException(
                status_code=403,
                detail=_business_detail(
                    "WHOLE_PRODUCT_QUALITY_LOCATION_PERMISSION_DENIED",
                    "لا تملك الصلاحيات اللازمة لمعالجة كل مستودعات المنتج.",
                    context={"locations": denied[:20]},
                ),
            )

        await acquire_inventory_location_guards(db, company_id, location_ids)
        policy = await ensure_whole_product_quality_policy(
            db,
            company_id=company_id,
            actor_id=actor_id,
        )
        as_of_date = await get_company_local_date(db, company_id)
        total_quantity = Decimal(0)
        response_locations: list[dict] = []

        for location_id in location_ids:
            items = [
                SpecialTransferItem(
                    product_variant_id=int(product_variant_id),
                    batch_id=int(balance.batch_id),
                    source_status=str(balance.stock_status),
                    quantity=Decimal(balance.on_hand_quantity or 0),
                    uom_id=int(variant.base_uom_id),
                )
                for balance in rows_by_location[location_id]
            ]
            source_lines = await validate_special_transfer_source_items_locked(
                db,
                company_id=company_id,
                source_location_id=location_id,
                transfer_purpose=purpose,
                items=items,
                as_of_date=as_of_date,
                quality_issue_stage=True,
            )
            if any(str(line["operational_hold_snapshot"]).upper() != "RECALL" for line in source_lines):
                raise InventoryRuleError(
                    "PRODUCT_QUALITY_ISSUE_NOT_ACTIVE",
                    "Whole-product handling requires an active product quality issue.",
                )

            await stage_quality_handling_direct(
                db,
                company_id=company_id,
                actor_id=actor_id,
                source_location_id=location_id,
                destination_location_id=location_id,
                transfer_purpose=purpose,
                tenant_policy_id=int(policy.id),
                tenant_policy_revision=int(policy.revision),
                source_location_type="WAREHOUSE",
                destination_location_type="WAREHOUSE",
                source_lines=source_lines,
                notes=payload.reason,
            )

            for line in source_lines:
                quantity = Decimal(line["quantity"])
                batch_id = int(line["batch_id"])
                child_request_id = uuid5(
                    payload.request_id,
                    f"{payload.action}:{location_id}:{batch_id}:{line['source_stock_status']}",
                )
                if payload.action == "DISPOSE":
                    await confirm_final_disposal(
                        db,
                        company_id=company_id,
                        actor_id=actor_id,
                        request_id=child_request_id,
                        source_location_id=location_id,
                        product_variant_id=int(product_variant_id),
                        batch_id=batch_id,
                        quantity=quantity,
                        reason=payload.reason,
                        method=(payload.disposal_method or "").strip() or None,
                        evidence_reference=(payload.evidence_reference or "").strip() or None,
                    )
                else:
                    await confirm_vendor_handover(
                        db,
                        company_id=company_id,
                        actor_id=actor_id,
                        request_id=child_request_id,
                        source_location_id=location_id,
                        product_variant_id=int(product_variant_id),
                        batch_id=batch_id,
                        source_status=quality_stage_target_status(purpose, str(line["source_stock_status"])),
                        quantity=quantity,
                        vendor_name=str(payload.recipient_name),
                        vendor_reference=str(payload.handover_reference),
                        handover_reference=str(payload.handover_reference),
                    )
                total_quantity += quantity

            response_locations.append({
                "location_id": location_id,
                "location_name": location_names[location_id],
                "quantity": canonical_quantity(location_quantities[location_id]),
            })

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=actor_id,
            target_id=f"ProductVariant_{int(product_variant_id)}",
            action_type=(
                "WHOLE_PRODUCT_QUALITY_DISPOSED"
                if payload.action == "DISPOSE"
                else "WHOLE_PRODUCT_QUALITY_RETURNED_TO_VENDOR"
            ),
            old_value="quality_issue=RECALL",
            new_value=(
                f"action={payload.action}; locations={len(response_locations)}; "
                f"quantity={canonical_quantity(total_quantity)}"
            ),
        ))
        response_payload = {
            "message": (
                "تم إتلاف كل الكميات الحالية للمنتج."
                if payload.action == "DISPOSE"
                else "تم تسجيل تسليم كل الكميات الحالية للجهة المستلمة."
            ),
            "action": payload.action,
            "product_variant_id": int(product_variant_id),
            "total_quantity": canonical_quantity(total_quantity),
            "location_count": len(response_locations),
            "locations": response_locations,
        }
        complete_idempotent_operation(idem, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryRuleError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=_business_detail("WHOLE_PRODUCT_QUALITY_REJECTED", str(exc)),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=_business_detail(
                "WHOLE_PRODUCT_QUALITY_CONFLICT",
                "تعذر إتمام العملية بسبب تعارض في بيانات المخزون. حدّث البيانات وحاول مجددًا.",
            ),
        ) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_business_detail(
                "WHOLE_PRODUCT_QUALITY_INTERNAL_ERROR",
                "تعذر تنفيذ معالجة المنتج بالكامل.",
            ),
        ) from exc
