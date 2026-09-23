from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.product_tracking import (
    ProductTrackingError,
    load_company_product_tracking_defaults_state,
    save_company_product_tracking_defaults_serialized,
    update_product_tracking_modes,
)
from inventory_access import InventoryAccess
from models import Driver, SystemAuditLog
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(
    prefix="/simple-products/tracking",
    tags=["Product Tracking"],
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductTrackingDefaultsUpdate(StrictRequest):
    request_id: UUID
    lot_control_mode: str = Field(
        min_length=1,
        max_length=20,
    )
    expiry_control_mode: str = Field(
        min_length=1,
        max_length=20,
    )


class ProductTrackingUpdate(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    lot_control_mode: str = Field(
        min_length=1,
        max_length=20,
    )
    expiry_control_mode: str = Field(
        min_length=1,
        max_length=20,
    )


def _tracking_http_error(
    exc: ProductTrackingError,
) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "context": exc.context,
        },
    )


def _request_hash(
    payload: BaseModel,
    **scope: Any,
) -> str:
    body = payload.model_dump(
        mode="json",
        exclude={"request_id"},
    )
    body.update(scope)
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()


async def _require(
    db: AsyncSession,
    actor: Driver,
    permission: str,
) -> None:
    await InventoryAccess(
        db,
        actor,
    ).require(
        permission,
        any_location=True,
    )


def _audit_change(
    db: AsyncSession,
    *,
    actor: Driver,
    target: str,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    db.add(
        SystemAuditLog(
            company_id=int(actor.company_id),
            admin_id=int(actor.id),
            target_id=target,
            action_type=action,
            old_value=json.dumps(
                before,
                ensure_ascii=False,
                default=str,
                sort_keys=True,
            ),
            new_value=json.dumps(
                after,
                ensure_ascii=False,
                default=str,
                sort_keys=True,
            ),
        )
    )


def _defaults_payload(state) -> dict[str, str]:
    return {
        "lot_control_mode": state.lot_control_mode,
        "expiry_control_mode": state.expiry_control_mode,
        "lot_control_source": state.lot_control_source,
        "expiry_control_source": state.expiry_control_source,
    }


@router.get("/defaults")
async def get_product_tracking_defaults(
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    try:
        state = (
            await load_company_product_tracking_defaults_state(
                db,
                company_id=int(actor.company_id),
            )
        )
        return _defaults_payload(state)
    except ProductTrackingError as exc:
        raise _tracking_http_error(exc) from exc


@router.put("/defaults")
async def update_product_tracking_defaults(
    payload: ProductTrackingDefaultsUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.manage",
    )

    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            operation="PRODUCT_TRACKING_DEFAULTS_UPDATE_V1",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay

        before_state = (
            await load_company_product_tracking_defaults_state(
                db,
                company_id=int(actor.company_id),
            )
        )
        after_state = (
            await save_company_product_tracking_defaults_serialized(
                db,
                company_id=int(actor.company_id),
                lot_control_mode=payload.lot_control_mode,
                expiry_control_mode=payload.expiry_control_mode,
            )
        )

        before = _defaults_payload(before_state)
        after = _defaults_payload(after_state)
        if before != after:
            _audit_change(
                db,
                actor=actor,
                target=f"Company_{int(actor.company_id)}",
                action="PRODUCT_TRACKING_DEFAULTS_UPDATED_V1",
                before=before,
                after=after,
            )

        response = dict(after)
        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response

    except ProductTrackingError as exc:
        await db.rollback()
        raise _tracking_http_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_TRACKING_DEFAULTS_CONFLICT",
                "message": (
                    "Product tracking defaults could not be updated."
                ),
                "context": {},
            },
        ) from exc


@router.patch("/variants/{variant_id}")
async def update_variant_product_tracking(
    variant_id: int,
    payload: ProductTrackingUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.manage",
    )

    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            operation="PRODUCT_TRACKING_UPDATE_V1",
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload,
                variant_id=int(variant_id),
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        result = await update_product_tracking_modes(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            request_id=payload.request_id,
            product_variant_id=int(variant_id),
            expected_version=int(
                payload.expected_version
            ),
            lot_control_mode=payload.lot_control_mode,
            expiry_control_mode=payload.expiry_control_mode,
        )

        response = {
            "product_variant_id": result.product_variant_id,
            "version": result.version,
            "lot_control_mode": result.lot_control_mode,
            "expiry_control_mode": result.expiry_control_mode,
            "changed": result.changed,
        }
        if result.changed:
            _audit_change(
                db,
                actor=actor,
                target=(
                    f"ProductVariant_{result.product_variant_id}"
                ),
                action="PRODUCT_TRACKING_UPDATED_V1",
                before=dict(result.before_snapshot),
                after=dict(result.after_snapshot),
            )

        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response

    except ProductTrackingError as exc:
        await db.rollback()
        raise _tracking_http_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_TRACKING_CONFLICT",
                "message": (
                    "Product tracking settings could not be updated."
                ),
                "context": {},
            },
        ) from exc
