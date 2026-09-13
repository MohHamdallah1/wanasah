from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.sales_calculation.policy import (
    COMMERCIAL_ROUNDING_POLICY_CODE,
    CommercialPolicyError,
    publish_commercial_rounding_policy,
    resolve_commercial_rounding_policy,
)
from inventory_access import InventoryAccess
from models import Driver, SystemAuditLog
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(prefix="/commercial-policy", tags=["Commercial Policy"])


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoundingPolicyPublishRequest(StrictRequest):
    request_id: UUID
    expected_revision: int = Field(..., ge=0)
    precision: int = Field(..., ge=0, le=6)
    mode: Literal["HALF_UP", "HALF_EVEN"]
    reason: str = Field(..., min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("reason must be text.")
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise ValueError("reason is invalid.")
        return clean


def _request_hash(payload: BaseModel) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude={"request_id"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _require(
    db: AsyncSession,
    actor: Driver,
    permission: str,
) -> None:
    await InventoryAccess(db, actor).require(permission, any_location=True)


def _response(resolved) -> dict[str, Any]:
    return {
        "policy_code": COMMERCIAL_ROUNDING_POLICY_CODE,
        "policy_id": int(resolved.policy_id),
        "revision": int(resolved.policy_revision),
        "effective_from": resolved.effective_from.isoformat(),
        "schema_version": int(resolved.rounding_policy.version),
        "currency_code": resolved.rounding_policy.currency_code,
        "precision": int(resolved.rounding_policy.precision),
        "mode": resolved.rounding_policy.mode,
    }


def _http_error(exc: CommercialPolicyError) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.as_detail())


@router.get("/rounding")
async def get_rounding_policy(
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    from datetime import datetime, timezone

    try:
        resolved = await resolve_commercial_rounding_policy(
            db,
            company_id=actor.company_id,
            as_of=datetime.now(timezone.utc),
        )
        return {"policy": _response(resolved)}
    except CommercialPolicyError as exc:
        if exc.code == "COMMERCIAL_ROUNDING_NOT_CONFIGURED":
            return {"policy": None}
        raise _http_error(exc) from exc


@router.post("/rounding/publish", status_code=201)
async def publish_rounding_policy(
    payload: RoundingPolicyPublishRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    # Publishing a financial calculation policy requires both management and
    # approval authority; admins naturally satisfy both through InventoryAccess.
    await _require(db, actor, "pricing.manage")
    await _require(db, actor, "pricing.approve")

    try:
        operation, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="COMMERCIAL_ROUNDING_PUBLISH",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay

        resolved = await publish_commercial_rounding_policy(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            expected_revision=payload.expected_revision,
            precision=payload.precision,
            mode=payload.mode,
        )
        response = {"policy": _response(resolved)}
        db.add(
            SystemAuditLog(
                company_id=actor.company_id,
                admin_id=actor.id,
                target_id=f"CommercialRoundingPolicy_{resolved.policy_id}",
                action_type="COMMERCIAL_ROUNDING_PUBLISHED",
                old_value=None,
                new_value=json.dumps(
                    {
                        **response,
                        "reason": payload.reason,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            )
        )
        complete_idempotent_operation(operation, response)
        await db.commit()
        return response
    except CommercialPolicyError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "COMMERCIAL_ROUNDING_CONFLICT",
                "message": "Concurrent commercial rounding policy publication conflicted.",
                "context": {},
            },
        ) from exc
