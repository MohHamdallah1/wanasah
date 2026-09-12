from __future__ import annotations

import ast
import os
import py_compile
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"
MODELS = BACKEND / "models.py"
SCHEMAS = BACKEND / "schemas.py"
WAREHOUSE = BACKEND / "api" / "warehouse.py"


def normalize(data: bytes) -> str:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def patch_models(text: str) -> str:
    if "ix_inventory_location_company_type_active_id" in text:
        raise RuntimeError("models.py: warehouse location management appears already applied.")

    old = '''        CheckConstraint("location_type IN ('WAREHOUSE', 'VEHICLE', 'IN_TRANSIT', 'SCRAP')", name='chk_inv_loc_type'),
        CheckConstraint("length(trim(code)) > 0", name='chk_inv_loc_code_not_blank'),
        CheckConstraint("vehicle_id IS NULL OR location_type = 'VEHICLE'", name='chk_inv_loc_vehicle_type'),
        CheckConstraint("location_type <> 'VEHICLE' OR vehicle_id IS NOT NULL", name='chk_inv_loc_vehicle_required'),
        Index('uq_active_inventory_location_vehicle', 'company_id', 'vehicle_id', unique=True,
              postgresql_where=text("vehicle_id IS NOT NULL AND is_active IS TRUE")),
'''
    new = '''        CheckConstraint("location_type IN ('WAREHOUSE', 'VEHICLE', 'IN_TRANSIT', 'SCRAP')", name='chk_inv_loc_type'),
        CheckConstraint("length(trim(name)) > 0", name='chk_inv_loc_name_not_blank'),
        CheckConstraint("length(trim(code)) > 0", name='chk_inv_loc_code_not_blank'),
        CheckConstraint("vehicle_id IS NULL OR location_type = 'VEHICLE'", name='chk_inv_loc_vehicle_type'),
        CheckConstraint("location_type <> 'VEHICLE' OR vehicle_id IS NOT NULL", name='chk_inv_loc_vehicle_required'),
        Index(
            'ix_inventory_location_company_type_active_id',
            'company_id', 'location_type', 'is_active', 'id'
        ),
        Index('uq_active_inventory_location_vehicle', 'company_id', 'vehicle_id', unique=True,
              postgresql_where=text("vehicle_id IS NOT NULL AND is_active IS TRUE")),
'''
    return replace_once(text, old, new, "models InventoryLocation constraints/index")


def patch_schemas(text: str) -> str:
    if "class WarehouseLocationCreateRequest" in text:
        raise RuntimeError("schemas.py: warehouse location management appears already applied.")

    text = replace_once(
        text,
        "from decimal import Decimal, InvalidOperation, ROUND_HALF_UP\n",
        "from decimal import Decimal, InvalidOperation, ROUND_HALF_UP\nimport re\n",
        "schemas import re",
    )

    old = '''class WarehouseStatusResponse(BaseModel):
    status: str

class SimpleProductVariantItem(BaseModel):
'''
    new = '''class WarehouseStatusResponse(BaseModel):
    status: str


def _warehouse_code_input(v: Any) -> str:
    value = _required_text(v).upper()
    if len(value) > 50:
        raise ValueError("كود المستودع يجب ألا يتجاوز 50 حرفاً.")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", value):
        raise ValueError(
            "كود المستودع يقبل أحرف A-Z وأرقاماً والرمزين - و _ فقط، "
            "ويجب أن يبدأ بحرف أو رقم."
        )
    return value


class WarehouseLocationCreateRequest(RequestModel):
    request_id: UUID
    name: str = Field(..., min_length=1, max_length=150)
    code: str = Field(..., min_length=1, max_length=50)
    branch_id: OptionalPositiveDbInt = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, v: Any) -> str:
        return _warehouse_code_input(v)


class WarehouseLocationUpdateRequest(RequestModel):
    request_id: UUID
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    branch_id: OptionalPositiveDbInt = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return _required_text(v)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return _warehouse_code_input(v)

    @model_validator(mode="after")
    def require_mutation(self) -> "WarehouseLocationUpdateRequest":
        if not ({"name", "code", "branch_id"} & self.model_fields_set):
            raise ValueError("يجب إرسال حقل واحد على الأقل لتعديل المستودع.")
        return self


class WarehouseLocationStateRequest(RequestModel):
    request_id: UUID
    reason: Optional[str] = Field(None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


class WarehouseLocationItem(BaseModel):
    id: int
    name: str
    code: str
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WarehouseLocationCursorPage(BaseModel):
    items: List[WarehouseLocationItem]
    next_cursor: Optional[str] = None
    has_more: bool
    total: Optional[int] = None


class WarehouseLocationMutationResponse(BaseModel):
    message: str
    location: WarehouseLocationItem


class SimpleProductVariantItem(BaseModel):
'''
    return replace_once(text, old, new, "schemas warehouse location contracts")


def patch_warehouse(text: str) -> str:
    if "WAREHOUSE_LOCATION_CREATE" in text:
        raise RuntimeError("warehouse.py: warehouse location management appears already applied.")

    text = replace_once(
        text,
        '''from models import (Driver, Product, ProductVariant,
DispatchRoute, SystemAuditLog,
''',
        '''from models import (Driver, Product, ProductVariant, Branch,
DispatchRoute, SystemAuditLog,
''',
        "warehouse Branch import",
    )

    text = replace_once(
        text,
        '''WarehouseStatusResponse, SimpleProductVariantItem, SimpleProductVariantCursorPage, ProductVariantResolveRequest,
AddProductVariantRequest, AdjustWarehouseEntryRequest, UpgradedInboundRequest, UnifiedDispatchRequest, UnifiedReceiveRequest,
''',
        '''WarehouseStatusResponse, WarehouseLocationCreateRequest, WarehouseLocationUpdateRequest,
WarehouseLocationStateRequest, WarehouseLocationCursorPage, WarehouseLocationMutationResponse,
SimpleProductVariantItem, SimpleProductVariantCursorPage, ProductVariantResolveRequest,
AddProductVariantRequest, AdjustWarehouseEntryRequest, UpgradedInboundRequest, UnifiedDispatchRequest, UnifiedReceiveRequest,
''',
        "warehouse location schema imports",
    )

    helper_anchor = '''def _transfer_cursor_scope_hash(scope: str) -> str:
'''
    helpers = '''def _warehouse_location_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_warehouse_location_cursor(
    location_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "warehouse-location",
            "scope": _warehouse_location_cursor_scope_hash(scope),
            "id": int(location_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_warehouse_location_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "warehouse-location"
            or payload.get("scope")
            != _warehouse_location_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        location_id = payload.get("id")
        if type(location_id) is not int or location_id <= 0:
            raise ValueError

        return location_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor المستودعات غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc


def _transfer_cursor_scope_hash(scope: str) -> str:
'''
    text = replace_once(text, helper_anchor, helpers, "warehouse location cursor helpers")

    route_anchor = '''# =================================================================================
# 1. استلام بضاعة من المورد (Inbound) - المحرك الموحد
# =================================================================================
'''
    routes = r'''def _warehouse_location_to_payload(
    location: InventoryLocation,
    *,
    branch_name: Optional[str] = None,
) -> dict:
    def _as_iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()

    return {
        "id": int(location.id),
        "name": str(location.name),
        "code": str(location.code),
        "branch_id": (
            int(location.branch_id)
            if location.branch_id is not None
            else None
        ),
        "branch_name": branch_name,
        "is_active": bool(location.is_active),
        "created_at": _as_iso(location.created_at),
        "updated_at": _as_iso(location.updated_at),
    }


async def _get_warehouse_branch(
    db: AsyncSession,
    *,
    company_id: int,
    branch_id: Optional[int],
    require_active: bool,
):
    if branch_id is None:
        return None

    row = (
        await db.execute(
            select(
                Branch.id,
                Branch.name,
                Branch.is_active,
            ).filter(
                Branch.company_id == company_id,
                Branch.id == branch_id,
            )
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="الفرع المحدد غير موجود أو لا يتبع شركتك.",
        )

    if require_active and not bool(row.is_active):
        raise HTTPException(
            status_code=409,
            detail="لا يمكن ربط المستودع بفرع غير فعال.",
        )

    return row


async def _load_locked_warehouse_location(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
) -> InventoryLocation:
    location = (
        await db.execute(
            select(InventoryLocation).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.location_type == 'WAREHOUSE',
            ).with_for_update()
        )
    ).scalar_one_or_none()

    if location is None:
        raise HTTPException(
            status_code=404,
            detail="المستودع غير موجود أو لا يتبع شركتك.",
        )
    return location


@router.get(
    "/warehouse/locations/manage",
    response_model=WarehouseLocationCursorPage,
    status_code=200,
)
async def manage_warehouse_locations(
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    include_inactive: bool = Query(default=True),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    clean_search = (search or "").strip().lower()

    scope = (
        f"warehouse-locations|{company_id}|"
        f"{1 if include_inactive else 0}|{clean_search}"
    )

    stmt = (
        select(
            InventoryLocation,
            Branch.name.label("branch_name"),
        )
        .outerjoin(
            Branch,
            and_(
                Branch.company_id == InventoryLocation.company_id,
                Branch.id == InventoryLocation.branch_id,
            ),
        )
        .filter(
            InventoryLocation.company_id == company_id,
            InventoryLocation.location_type == 'WAREHOUSE',
        )
    )

    if not include_inactive:
        stmt = stmt.filter(InventoryLocation.is_active.is_(True))

    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(InventoryLocation.name).like(pattern, escape="\\"),
                func.lower(InventoryLocation.code).like(pattern, escape="\\"),
            )
        )

    total = None
    if cursor is None:
        count_stmt = select(func.count()).select_from(
            stmt.with_only_columns(
                InventoryLocation.id,
                maintain_column_froms=True,
            ).order_by(None).subquery()
        )
        total = int((await db.execute(count_stmt)).scalar_one())

    if cursor is not None:
        cursor_id = _decode_warehouse_location_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.filter(InventoryLocation.id > cursor_id)

    rows = (
        await db.execute(
            stmt.order_by(InventoryLocation.id.asc()).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        _warehouse_location_to_payload(
            location,
            branch_name=branch_name,
        )
        for location, branch_name in rows
    ]

    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_warehouse_location_cursor(
            int(rows[-1][0].id),
            scope=scope,
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


@router.post(
    "/warehouse/locations",
    response_model=WarehouseLocationMutationResponse,
    status_code=201,
)
async def create_warehouse_location(
    payload: WarehouseLocationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_CREATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        if payload.code == "TRANSIT-SYS":
            raise HTTPException(
                status_code=409,
                detail="الكود TRANSIT-SYS محجوز لموقع العبور الداخلي للنظام.",
            )

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=payload.branch_id,
            require_active=True,
        )

        duplicate_id = (
            await db.execute(
                select(InventoryLocation.id).filter(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.code == payload.code,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if duplicate_id is not None:
            raise HTTPException(
                status_code=409,
                detail="كود الموقع مستخدم مسبقاً داخل شركتك.",
            )

        location = InventoryLocation(
            company_id=company_id,
            branch_id=payload.branch_id,
            name=payload.name,
            code=payload.code,
            location_type='WAREHOUSE',
            vehicle_id=None,
            is_active=True,
        )
        db.add(location)
        await db.flush()

        branch_name = str(branch_row.name) if branch_row is not None else None
        location_payload = _warehouse_location_to_payload(
            location,
            branch_name=branch_name,
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"InventoryLocation_{location.id}",
            action_type="WAREHOUSE_LOCATION_CREATED",
            old_value=None,
            new_value=json.dumps(location_payload, sort_keys=True, ensure_ascii=False),
        ))

        response_payload = {
            "message": "تم إنشاء المستودع بنجاح.",
            "location": location_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="تعذر إنشاء المستودع بسبب تعارض متزامن أو كود مكرر.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في إنشاء المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إنشاء المستودع.")


@router.patch(
    "/warehouse/locations/{location_id}",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def update_warehouse_location(
    location_id: int,
    payload: WarehouseLocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload, context={"location_id": int(location_id)})
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_UPDATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        location = await _load_locked_warehouse_location(
            db,
            company_id=company_id,
            location_id=location_id,
        )

        current_branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=False,
        )
        old_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(current_branch_row.name) if current_branch_row is not None else None),
        )

        branch_row = current_branch_row
        if "branch_id" in payload.model_fields_set:
            branch_row = await _get_warehouse_branch(
                db,
                company_id=company_id,
                branch_id=payload.branch_id,
                require_active=True,
            )
            location.branch_id = payload.branch_id

        if "name" in payload.model_fields_set:
            location.name = payload.name

        if "code" in payload.model_fields_set:
            if payload.code == "TRANSIT-SYS":
                raise HTTPException(
                    status_code=409,
                    detail="الكود TRANSIT-SYS محجوز لموقع العبور الداخلي للنظام.",
                )
            duplicate_id = (
                await db.execute(
                    select(InventoryLocation.id).filter(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.code == payload.code,
                        InventoryLocation.id != location.id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if duplicate_id is not None:
                raise HTTPException(status_code=409, detail="كود الموقع مستخدم مسبقاً داخل شركتك.")
            location.code = payload.code

        location.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.flush()

        new_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(branch_row.name) if branch_row is not None else None),
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"InventoryLocation_{location.id}",
            action_type="WAREHOUSE_LOCATION_UPDATED",
            old_value=json.dumps(old_payload, sort_keys=True, ensure_ascii=False),
            new_value=json.dumps(new_payload, sort_keys=True, ensure_ascii=False),
        ))

        response_payload = {
            "message": "تم تحديث المستودع بنجاح.",
            "location": new_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="تعذر تحديث المستودع بسبب تعارض متزامن أو كود مكرر.")
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تحديث المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تحديث المستودع.")


@router.post(
    "/warehouse/locations/{location_id}/activate",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def activate_warehouse_location(
    location_id: int,
    payload: WarehouseLocationStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload, context={"location_id": int(location_id)})
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_ACTIVATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
        location = await _load_locked_warehouse_location(
            db,
            company_id=company_id,
            location_id=location_id,
        )

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=True,
        )

        if not location.is_active:
            location.is_active = True
            location.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"InventoryLocation_{location.id}",
                action_type="WAREHOUSE_LOCATION_ACTIVATED",
                old_value="inactive",
                new_value=payload.reason or "active",
            ))

        await db.flush()
        location_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(branch_row.name) if branch_row is not None else None),
        )
        response_payload = {
            "message": "تم تفعيل المستودع بنجاح.",
            "location": location_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تفعيل المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تفعيل المستودع.")


@router.post(
    "/warehouse/locations/{location_id}/deactivate",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def deactivate_warehouse_location(
    location_id: int,
    payload: WarehouseLocationStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="سبب تعطيل المستودع مطلوب للتدقيق.")

    try:
        request_hash = _stable_request_hash(payload, context={"location_id": int(location_id)})
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_DEACTIVATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        # Serializes deactivation against all inventory mutations using this location.
        await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
        location = await _load_locked_warehouse_location(
            db,
            company_id=company_id,
            location_id=location_id,
        )

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=False,
        )

        if location.is_active:
            stock_row = (
                await db.execute(
                    select(
                        func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0),
                        func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0),
                    ).filter(
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.location_id == location.id,
                    )
                )
            ).one()
            on_hand_total = int(stock_row[0] or 0)
            reserved_total = int(stock_row[1] or 0)
            if on_hand_total > 0 or reserved_total > 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "لا يمكن تعطيل المستودع لأنه يحتوي مخزوناً فعلياً "
                        f"(on_hand={on_hand_total}, reserved={reserved_total})."
                    ),
                )

            transit_ref = (
                await db.execute(
                    select(InventoryTransferHeader.reference_number).filter(
                        InventoryTransferHeader.company_id == company_id,
                        InventoryTransferHeader.workflow_type == 'TRANSIT',
                        InventoryTransferHeader.status == 'IN_TRANSIT',
                        or_(
                            InventoryTransferHeader.source_location_id == location.id,
                            InventoryTransferHeader.destination_location_id == location.id,
                        ),
                    ).order_by(InventoryTransferHeader.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if transit_ref is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"لا يمكن تعطيل المستودع لوجود حوالة IN_TRANSIT مرتبطة به ({transit_ref}).",
                )

            active_lock_id = (
                await db.execute(
                    select(InventoryLock.id).filter(
                        InventoryLock.company_id == company_id,
                        InventoryLock.location_id == location.id,
                        InventoryLock.released_at.is_(None),
                    ).order_by(InventoryLock.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if active_lock_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="لا يمكن تعطيل المستودع أثناء وجود جرد/قفل مخزني نشط عليه.",
                )

            active_route_id = (
                await db.execute(
                    select(DispatchRoute.id).filter(
                        DispatchRoute.company_id == company_id,
                        DispatchRoute.source_location_id == location.id,
                        DispatchRoute.status.in_(['active', 'waiting', 'postponed']),
                    ).order_by(DispatchRoute.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if active_route_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="لا يمكن تعطيل المستودع لأنه مصدر لخط سير تشغيلي غير مغلق.",
                )

            location.is_active = False
            location.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"InventoryLocation_{location.id}",
                action_type="WAREHOUSE_LOCATION_DEACTIVATED",
                old_value="active",
                new_value=reason,
            ))

        await db.flush()
        location_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(branch_row.name) if branch_row is not None else None),
        )
        response_payload = {
            "message": "تم تعطيل المستودع بنجاح.",
            "location": location_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تعطيل المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تعطيل المستودع.")


# =================================================================================
# 1. استلام بضاعة من المورد (Inbound) - المحرك الموحد
# =================================================================================
'''
    text = replace_once(text, route_anchor, routes, "warehouse location management routes")
    return text


def validate(prepared: dict[str, str]) -> None:
    required = {
        "models": [
            "chk_inv_loc_name_not_blank",
            "ix_inventory_location_company_type_active_id",
        ],
        "schemas": [
            "class WarehouseLocationCreateRequest",
            "class WarehouseLocationUpdateRequest",
            "class WarehouseLocationStateRequest",
            "class WarehouseLocationCursorPage",
            "class WarehouseLocationMutationResponse",
        ],
        "warehouse": [
            "WAREHOUSE_LOCATION_CREATE",
            "WAREHOUSE_LOCATION_UPDATE",
            "WAREHOUSE_LOCATION_ACTIVATE",
            "WAREHOUSE_LOCATION_DEACTIVATE",
            '"/warehouse/locations/manage"',
            '"/warehouse/locations/{location_id}/activate"',
            '"/warehouse/locations/{location_id}/deactivate"',
            "exclusive=True",
            "InventoryBalance.on_hand_quantity",
            "InventoryTransferHeader.status == 'IN_TRANSIT'",
            "InventoryLock.released_at.is_(None)",
            "DispatchRoute.status.in_(['active', 'waiting', 'postponed'])",
        ],
    }
    for name, tokens in required.items():
        for token in tokens:
            if token not in prepared[name]:
                raise RuntimeError(f"{name}: missing invariant {token}")

    if prepared["warehouse"].count('operation="WAREHOUSE_LOCATION_CREATE"') != 1:
        raise RuntimeError("warehouse.py: duplicated location create operation")
    if prepared["models"].count("ix_inventory_location_company_type_active_id") != 1:
        raise RuntimeError("models.py: duplicated location management index")


def main() -> None:
    files = {"models": MODELS, "schemas": SCHEMAS, "warehouse": WAREHOUSE}
    for path in files.values():
        if not path.is_file():
            raise SystemExit(f"ERROR: missing {path}")

    originals = {name: path.read_bytes() for name, path in files.items()}
    prepared = {}

    for name, path in files.items():
        text = normalize(originals[name])
        if name == "models":
            text = patch_models(text)
        elif name == "schemas":
            text = patch_schemas(text)
        else:
            text = patch_warehouse(text)
        ast.parse(text, filename=str(path))
        prepared[name] = text

    validate(prepared)

    written = []
    try:
        for name, path in files.items():
            tmp = path.with_suffix(path.suffix + ".warehouse_locations.tmp")
            tmp.write_text(prepared[name], encoding="utf-8", newline="\n")
            py_compile.compile(str(tmp), doraise=True)
            os.replace(tmp, path)
            written.append(name)
    except Exception:
        for name in written:
            files[name].write_bytes(originals[name])
        raise

    print("WAREHOUSE_LOCATION_MANAGEMENT_PATCH_OK")
    print("PY_COMPILE=OK")
    print("CREATE_EDIT_ACTIVATE_DEACTIVATE=ENABLED")
    print("LOCATION_MUTATIONS_IDEMPOTENT=ENABLED")
    print("DEACTIVATE_WITH_STOCK=BLOCKED")
    print("DEACTIVATE_WITH_IN_TRANSIT=BLOCKED")
    print("DEACTIVATE_WITH_ACTIVE_STOCKTAKE_LOCK=BLOCKED")
    print("DEACTIVATE_WITH_ACTIVE_DISPATCH_ROUTE=BLOCKED")
    print("DEACTIVATION_CONCURRENCY_GUARD=EXCLUSIVE")
    print("LOCATION_MANAGEMENT_CURSOR=BOUNDED")
    print("SERVICES_ENGINE=UNCHANGED")
    print("NEXT=REBUILD_DEV_SCHEMA_AND_RUN_LOCATION_E2E")


if __name__ == "__main__":
    main()
