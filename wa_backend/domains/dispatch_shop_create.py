"""Authoritative, atomic Dashboard Shop-create operation and immutable receipt.

An explicit client UUID is durable only when committed together with the Shop
and opening-money audit. Legacy POST without a UUID remains supported but is
NOT idempotent. A missing receipt is UNKNOWN, never inferred from Shop metadata.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from models import OperationIdempotency, Shop, SystemAuditLog
from schemas import AdminAddShopRequest
from services import begin_idempotent_operation, complete_idempotent_operation

SHOP_CREATE_OPERATION = "DISPATCH_SHOP_CREATE_V1"


class ShopCreateDuplicate(Exception):
    """Preserve the historical 409 duplicate-shop warning contract."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response


def shop_create_request_hash(payload: AdminAddShopRequest) -> str:
    """Hash normalized validated business values; UUID is an identity, not payload."""
    document = payload.model_dump(mode="json", exclude={"request_id"})
    return sha256(json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


async def create_shop(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    payload: AdminAddShopRequest,
    lock_zones: Callable[..., Awaitable[dict]],
    lock_advisory: Callable[..., Awaitable[None]],
    require_tax: Callable[..., Awaitable[set[int]]],
) -> dict[str, Any]:
    """Only caller commits. All writes and the idempotency receipt share ONE TX."""
    request_id = str(payload.request_id) if payload.request_id is not None else None
    record = None
    if request_id is not None:
        # Lock the canonical id first. A concurrent identical POST waits, then
        # replays the committed receipt without re-validating mutable zone state.
        record, previous = await begin_idempotent_operation(
            db, company_id=company_id, actor_id=actor_id,
            operation=SHOP_CREATE_OPERATION,
            request_id=request_id, request_hash=shop_create_request_hash(payload),
        )
        if previous is not None:
            if previous.get("shop_id") is None or previous.get("request_id") != request_id:
                raise RuntimeError("Shop create receipt is inconsistent")
            return previous

    await require_tax(
        db, company_id=company_id,
        jurisdiction_ids=(
            [payload.taxJurisdictionId]
            if payload.taxJurisdictionId is not None else []
        ),
    )

    name = payload.name.strip()
    phone = payload.phone.strip() if payload.phone and payload.phone.strip() else None
    map_link = payload.mapLink.strip() if payload.mapLink else ""
    zone_id = int(payload.zoneId)
    lat = float(payload.latitude) if payload.latitude is not None else None
    lng = float(payload.longitude) if payload.longitude is not None else None

    zones = await lock_zones(db, company_id=company_id, zone_ids=[zone_id])
    if not zones[zone_id].is_active:
        raise HTTPException(
            status_code=400,
            detail="المنطقة المحددة مؤرشفة ولا يمكن إضافة محل جديد إليها.",
        )

    if phone:
        await lock_advisory(
            db, company_id=company_id, keys=[f"shop-phone:{phone}"],
        )

    duplicate_shop = None
    if phone:
        duplicate_shop = (await db.execute(
            select(Shop).options(joinedload(Shop.zone)).filter(
                Shop.company_id == company_id, Shop.phone_number == phone,
            ).order_by(Shop.id.asc())
        )).scalars().first()
    if duplicate_shop is None and name and map_link:
        duplicate_shop = (await db.execute(
            select(Shop).options(joinedload(Shop.zone)).filter(
                Shop.company_id == company_id,
                Shop.name == name, Shop.location_link == map_link,
            ).order_by(Shop.id.asc())
        )).scalars().first()
    if duplicate_shop is None and lat is not None and lng is not None:
        duplicate_shop = (await db.execute(
            select(Shop).options(joinedload(Shop.zone)).filter(
                Shop.company_id == company_id,
                Shop.name == name,
                Shop.latitude.isnot(None), Shop.longitude.isnot(None),
                func.abs(cast(Shop.latitude, Float) - lat) < 0.0001,
                func.abs(cast(Shop.longitude, Float) - lng) < 0.0001,
            ).order_by(Shop.id.asc())
        )).scalars().first()
    if duplicate_shop and not payload.force_save:
        zone_name = duplicate_shop.zone.name if duplicate_shop.zone else "بدون منطقة"
        raise ShopCreateDuplicate({
            "message": "تنبيه: يوجد محل مسجل مسبقاً بمعلومات مطابقة.",
            "is_duplicate": True,
            "existing_shop": {
                "id": str(duplicate_shop.id),
                "name": duplicate_shop.name,
                "owner": duplicate_shop.contact_person or "غير مسجل",
                "phone": duplicate_shop.phone_number,
                "mapLink": duplicate_shop.location_link,
                "zone_name": zone_name + (" (مؤرشف)" if duplicate_shop.is_archived else ""),
            },
        })
    if duplicate_shop and phone and duplicate_shop.phone_number == phone:
        raise HTTPException(
            status_code=409,
            detail="رقم الهاتف مستخدم لمحل آخر داخل الشركة ولا يمكن تجاوزه بالحفظ الإجباري.",
        )

    new_shop = Shop(
        company_id=company_id, name=name,
        contact_person=payload.owner.strip() if payload.owner else "",
        phone_number=phone, location_link=map_link,
        latitude=payload.latitude, longitude=payload.longitude,
        zone_id=zone_id,
        tax_jurisdiction_id=(
            int(payload.taxJurisdictionId)
            if payload.taxJurisdictionId is not None else None
        ),
        is_active=True, is_archived=False,
        current_balance=payload.initialDebt,
        max_debt_limit=payload.maxDebtLimit,
        added_by_driver_id=actor_id, sequence=int(payload.sequence),
    )
    db.add(new_shop)
    await db.flush()
    shop_id = str(new_shop.id)

    # The original creation amount and cap must not be mistaken for the live
    # balance after FIELD collections. Append-only audit is in the same TX.
    opening = format(payload.initialDebt, ".3f")
    cap = format(payload.maxDebtLimit, ".3f")
    audit = SystemAuditLog(
        company_id=company_id, admin_id=actor_id,
        target_id=f"Shop_{shop_id}", action_type="SHOP_CREATED",
        old_value=None,
        new_value=json.dumps({
            "shop_id": shop_id, "request_id": request_id,
            "opening_receivable": opening, "opening_credit_cap": cap,
        }, sort_keys=True, separators=(",", ":")),
    )
    db.add(audit)
    await db.flush()

    response: dict[str, Any] = {
        "message": "تم إضافة المحل بنجاح",
        "shop_id": shop_id,
    }
    if record is not None:
        response.update({
            "request_id": request_id,
            "state": "COMMITTED",
            "opening_evidence": {
                "opening_receivable": opening,
                "opening_credit_cap": cap,
                "audit_id": str(audit.id),
            },
        })
        complete_idempotent_operation(record, response)
        await db.flush()
    return response


async def read_shop_create_receipt(
    db: AsyncSession, *, company_id: int, actor_id: int, request_id: UUID,
) -> dict[str, Any]:
    """Authorized actor-only read, never a name/phone inference or mutation.

    An uncommitted transaction is invisible at READ COMMITTED; absent/expired
    records deliberately remain UNKNOWN. Receipts have no automatic expiry.
    """
    canonical = str(request_id)
    record = await db.scalar(
        select(OperationIdempotency).where(
            OperationIdempotency.company_id == company_id,
            OperationIdempotency.created_by == actor_id,
            OperationIdempotency.operation == SHOP_CREATE_OPERATION,
            OperationIdempotency.request_id == canonical,
        )
    )
    if record is None:
        return {"request_id": canonical, "state": "UNKNOWN"}
    if (
        str(record.state or "").upper() != "COMMITTED"
        or record.completed_at is None
        or not isinstance(record.response_json, dict)
        or record.response_json.get("request_id") != canonical
        or not record.response_json.get("shop_id")
    ):
        return {"request_id": canonical, "state": "UNKNOWN"}
    return {
        "request_id": canonical,
        "state": "COMMITTED",
        "response": dict(record.response_json),
    }
