from pathlib import Path
import ast
import re
import sys

PATCH_ID = "DRIVER_UPDATE_VISIT_V4"
ROOT = Path.cwd()
MODELS = ROOT / "wa_backend" / "models.py"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
DRIVER = ROOT / "wa_backend" / "api" / "driver.py"

for path in (MODELS, SCHEMAS, DRIVER):
    if not path.is_file():
        raise SystemExit(f"PATCH_ABORT: الملف غير موجود: {path}. شغّل الباتش من جذر المشروع.")


def read_source(path: Path):
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"PATCH_ABORT: {path} ليس UTF-8.") from exc
    return text.replace("\r\n", "\n"), newline


def write_source(path: Path, normalized_text: str, newline: str):
    data = normalized_text.replace("\n", newline).encode("utf-8")
    path.write_bytes(data)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"PATCH_ABORT: {label}: expected exactly 1 anchor, found {count}. لا تعدّل يدوياً فوق حالة غير متوقعة."
        )
    return text.replace(old, new, 1)


def class_block(text: str, class_name: str, next_anchor: str):
    start_token = f"class {class_name}"
    start = text.find(start_token)
    if start < 0:
        raise SystemExit(f"PATCH_ABORT: class {class_name} غير موجود.")
    end = text.find(next_anchor, start)
    if end < 0:
        raise SystemExit(f"PATCH_ABORT: نهاية class {class_name} غير قابلة للتحديد.")
    return start, end, text[start:end]


def ensure_import_names(text: str, module: str, names):
    multi = re.search(
        rf"^from {re.escape(module)} import \(\n(?P<body>.*?)\n\)",
        text,
        flags=re.M | re.S,
    )
    if multi:
        body = multi.group("body")
        missing = [name for name in names if re.search(rf"\b{re.escape(name)}\b", body) is None]
        if not missing:
            return text
        new_body = body.rstrip() + "".join(f"\n    {name}," for name in missing)
        return text[:multi.start("body")] + new_body + text[multi.end("body"):]

    single = re.search(
        rf"^from {re.escape(module)} import (?P<body>[^\n]+)$",
        text,
        flags=re.M,
    )
    if not single:
        raise SystemExit(f"PATCH_ABORT: import من {module} غير موجود.")
    existing = [part.strip() for part in single.group("body").split(",") if part.strip()]
    for name in names:
        if name not in existing:
            existing.append(name)
    block = f"from {module} import (\n" + "".join(f"    {name},\n" for name in existing) + ")"
    return text[:single.start()] + block + text[single.end():]


models, models_nl = read_source(MODELS)
schemas, schemas_nl = read_source(SCHEMAS)
driver, driver_nl = read_source(DRIVER)

already_done = (
    "fk_visit_return_tenant_batch" in models
    and "request_id: UUID" in schemas
    and f"# PATCH: {PATCH_ID}" in driver
)
if already_done:
    print(f"{PATCH_ID}_ALREADY_APPLIED")
    raise SystemExit(0)

# -----------------------------------------------------------------------------
# 1) models.py — VisitReturn must retain the physical batch identity.
# -----------------------------------------------------------------------------
start, end, block = class_block(models, "VisitReturn(Base):", "# =================================================================================\n# ⑩")

if "fk_visit_return_tenant_batch" not in block:
    old_fk = """        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_visit_return_tenant_variant'),
        Index('ix_visit_return_composite', 'visit_id', 'product_variant_id'),
"""
    new_fk = """        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_visit_return_tenant_variant'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_visit_return_tenant_batch'
        ),
        Index('ix_visit_return_composite', 'visit_id', 'product_variant_id'),
"""
    block = replace_once(block, old_fk, new_fk, "models.VisitReturn batch FK")

if re.search(r"^\s+batch_id\s*=", block, flags=re.M) is None:
    old_cols = """    visit_id           = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
"""
    new_cols = """    visit_id           = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_id           = Column(Integer, nullable=False, index=True)
"""
    block = replace_once(block, old_cols, new_cols, "models.VisitReturn batch_id column")

models = models[:start] + block + models[end:]

# -----------------------------------------------------------------------------
# 2) schemas.py — scanned return batch + request-level idempotency.
# -----------------------------------------------------------------------------

def add_batch_field_to_schema(text: str, class_name: str, next_anchor: str) -> str:
    s, e, b = class_block(text, class_name, next_anchor)
    if re.search(r"^\s+batch_id:\s*", b, flags=re.M) is None:
        b = replace_once(
            b,
            "    product_variant_id: int\n",
            "    product_variant_id: int\n    batch_id: int\n",
            f"schemas.{class_name}.batch_id",
        )
    return text[:s] + b + text[e:]

schemas = add_batch_field_to_schema(
    schemas,
    "VisitDetailsReturnResponse(BaseModel):",
    "class VisitDetailsResponse",
)
schemas = add_batch_field_to_schema(
    schemas,
    "VisitReturnResponse(BaseModel):",
    "class DriverVisitResponse",
)

s, e, b = class_block(schemas, "VisitReturnInput(RequestModel):", "class VisitUpdateRequest")
if re.search(r"^\s+batch_id:\s*", b, flags=re.M) is None:
    b = replace_once(
        b,
        "    product_variant_id: PositiveDbInt\n",
        "    product_variant_id: PositiveDbInt\n    batch_id: PositiveDbInt\n",
        "schemas.VisitReturnInput.batch_id",
    )
schemas = schemas[:s] + b + schemas[e:]

s, e, b = class_block(schemas, "VisitUpdateRequest(RequestModel):", "# +++ سكيما الدالة القادمة")
if "request_id: UUID" not in b:
    b = replace_once(
        b,
        "class VisitUpdateRequest(RequestModel):\n    outcome:",
        "class VisitUpdateRequest(RequestModel):\n    request_id: UUID\n    outcome:",
        "schemas.VisitUpdateRequest.request_id",
    )
old_return_keys = """        return_keys = [
            (item.product_variant_id, item.return_type)
            for item in self.returns
        ]
"""
new_return_keys = """        return_keys = [
            (item.product_variant_id, item.batch_id, item.return_type)
            for item in self.returns
        ]
"""
if old_return_keys in b:
    b = replace_once(
        b,
        old_return_keys,
        new_return_keys,
        "schemas.VisitUpdateRequest return uniqueness",
    )
elif new_return_keys not in b:
    raise SystemExit("PATCH_ABORT: schemas.VisitUpdateRequest return_keys في حالة غير متوقعة.")
schemas = schemas[:s] + b + schemas[e:]

# -----------------------------------------------------------------------------
# 3) driver.py imports required by the unified update_visit.
# -----------------------------------------------------------------------------
if re.search(r"^import hashlib$", driver, flags=re.M) is None:
    if "import logging\n" not in driver:
        raise SystemExit("PATCH_ABORT: import logging anchor غير موجود في driver.py")
    driver = driver.replace("import logging\n", "import hashlib\nimport logging\n", 1)
if re.search(r"^import json$", driver, flags=re.M) is None:
    if "import hashlib\n" not in driver:
        raise SystemExit("PATCH_ABORT: import hashlib anchor غير موجود في driver.py")
    driver = driver.replace("import hashlib\n", "import hashlib\nimport json\n", 1)

driver = ensure_import_names(
    driver,
    "services",
    [
        "reverse_previous_visit_state",
        "InventoryReversalError",
        "InventoryMutationError",
        "get_setting",
        "calculate_invoice",
        "check_debt_limits",
        "check_inventory_lock",
        "get_company_local_date",
        "allocate_fefo_inventory_batch",
        "apply_inventory_movements_batch",
        "begin_idempotent_operation",
        "complete_idempotent_operation",
    ],
)

# Previous Patch 1 should already have migrated the model import surface.
for required_model_name in ("InventoryTransferHeader", "InventoryLocation", "ProductBatch"):
    if re.search(rf"\b{required_model_name}\b", driver.split("from schemas import", 1)[0]) is None:
        raise SystemExit(
            f"PATCH_ABORT: driver.py لا يستورد {required_model_name}. نفّذ Patch 1 السابق أولاً."
        )

NEW_UPDATE_VISIT = r'''@router.put("/visits/{visit_id}", status_code=200)
async def update_visit(
    visit_id: int,
    payload: VisitUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # PATCH: DRIVER_UPDATE_VISIT_V4
    # Workflow الميدان محفوظ؛ التغيير هنا محصور في العزل ومحرك المخزون الموحد والـidempotency.
    company_id = current_driver.company_id
    driver_id = current_driver.id

    canonical_payload = payload.model_dump(mode="json", exclude={"request_id"})
    request_hash = hashlib.sha256(
        json.dumps(
            {"visit_id": visit_id, "payload": canonical_payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=driver_id,
            operation="DRIVER_UPDATE_VISIT",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )

        if replay_response is not None:
            await db.rollback()
            return replay_response

        # Lock order: idempotency -> session -> shop -> visit -> inventory.
        active_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    driver_id=driver_id,
                    end_time=None,
                )
                .order_by(WorkSession.id.asc())
                .limit(1)
                .with_for_update()
            )
        ).scalars().first()

        if active_session is None:
            raise HTTPException(
                status_code=403,
                detail="لا يمكنك تنفيذ العملية. الرجاء بدء يوم العمل أولاً.",
            )

        # Tenant-safe probe لمعرفة shop_id فقط؛ لا نكشف زيارة خارج الشركة/المندوب.
        visit_shop_id = (
            await db.execute(
                select(Visit.shop_id).filter_by(
                    company_id=company_id,
                    id=visit_id,
                    driver_id=driver_id,
                )
            )
        ).scalar_one_or_none()

        if visit_shop_id is None:
            raise HTTPException(status_code=404, detail="الزيارة غير موجودة")

        shop = (
            await db.execute(
                select(Shop)
                .filter_by(company_id=company_id, id=visit_shop_id)
                .order_by(Shop.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()

        if shop is None:
            raise HTTPException(
                status_code=404,
                detail="المحل المربوط بالزيارة غير موجود في النظام.",
            )

        visit = (
            await db.execute(
                select(Visit)
                .options(
                    selectinload(Visit.work_session),
                    selectinload(Visit.items).selectinload(VisitItem.product_variant),
                    selectinload(Visit.returns),
                )
                .filter_by(
                    company_id=company_id,
                    id=visit_id,
                    driver_id=driver_id,
                )
                .order_by(Visit.id.asc())
                .with_for_update()
            )
        ).scalars().first()

        if visit is None or visit.shop_id != shop.id:
            raise HTTPException(status_code=404, detail="الزيارة غير موجودة")

        locked_original_status = visit.status

        if visit.status == "Cancelled":
            raise HTTPException(
                status_code=403,
                detail=(
                    "مرفوض أمنياً: هذه الزيارة تم إلغاؤها من قبل الإدارة "
                    "(أو المنطقة مؤرشفة). لا يمكنك التعديل عليها."
                ),
            )

        visit.shop = shop

        if visit.work_session and visit.work_session.is_settled:
            raise HTTPException(
                status_code=403,
                detail="مرفوض: لا يمكن تعديل زيارة تم تسويتها ماليًا واعتمادها من الإدارة.",
            )

        if visit.driver_id != driver_id:
            raise HTTPException(
                status_code=403,
                detail="مرفوض أمنياً: لا تملك صلاحية التعديل على هذه الزيارة.",
            )

        if visit.work_session_id is not None and visit.work_session_id != active_session.id:
            raise HTTPException(
                status_code=409,
                detail="الزيارة مرتبطة بجلسة عمل أخرى ولا يجوز نقلها بين الجلسات أثناء التحديث.",
            )

        current_route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=active_session.id,
                    driver_id=driver_id,
                    status="active",
                )
                .order_by(DispatchRoute.id.asc())
                .limit(1)
            )
        ).scalars().first()

        if current_route is None:
            raise HTTPException(
                status_code=403,
                detail="تم سحب خط السير أو إيقافه من قبل الإدارة. لا يمكنك إتمام العملية.",
            )

        if current_route.vehicle_id is None:
            raise HTTPException(
                status_code=409,
                detail="خط السير الحالي غير مربوط بسيارة صالحة للمخزون.",
            )

        has_active_shortage = (
            await db.execute(
                select(ShortageRequest.id)
                .filter_by(
                    company_id=company_id,
                    shop_id=shop.id,
                    status="pending",
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

        is_emergency_request = payload.is_emergency or visit.is_emergency
        if shop.zone_id != current_route.zone_id and not (
            is_emergency_request or has_active_shortage
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "مرفوض أمنياً: لا يمكنك البيع لمحل خارج منطقة عملك المخصصة "
                    "إلا بتصريح طلب عاجل."
                ),
            )

        veh_loc_id = (
            await db.execute(
                select(InventoryLocation.id).filter_by(
                    company_id=company_id,
                    vehicle_id=current_route.vehicle_id,
                    location_type="VEHICLE",
                    is_active=True,
                )
            )
        ).scalar_one_or_none()

        if veh_loc_id is None:
            raise HTTPException(
                status_code=409,
                detail="السيارة الحالية لا تملك موقع مخزون VEHICLE فعالاً داخل الشركة.",
            )

        try:
            await check_inventory_lock(db, company_id, veh_loc_id)

            touched_variants = sorted(
                {item.product_variant_id for item in payload.cart_items}
                | {ret.product_variant_id for ret in payload.returns}
            )
            for variant_id in touched_variants:
                await check_inventory_lock(
                    db,
                    company_id,
                    veh_loc_id,
                    variant_id=variant_id,
                )

            # المرتجع يدخل Batch بعينه، لذلك لا يجوز تجاوز قفل Batch محدد.
            for ret in payload.returns:
                await check_inventory_lock(
                    db,
                    company_id,
                    veh_loc_id,
                    variant_id=ret.product_variant_id,
                    batch_id=ret.batch_id,
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"تم تجميد مبيعات سيارتك مؤقتاً لمراجعة العهدة: {str(exc)}",
            ) from exc

        if active_session.break_start_time and not active_session.break_end_time:
            raise HTTPException(
                status_code=403,
                detail="أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.",
            )

        if not active_session.is_authorized_to_sell:
            raise HTTPException(
                status_code=403,
                detail="غير مصرح لك بإجراء عمليات بيع حالياً. بانتظار تفعيل خط السير من الإدارة.",
            )

        pending_handshake = (
            await db.execute(
                select(InventoryTransferHeader.id)
                .filter(
                    InventoryTransferHeader.company_id == company_id,
                    InventoryTransferHeader.work_session_id == active_session.id,
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                    InventoryTransferHeader.status == "PENDING",
                    InventoryTransferHeader.expected_receiver_id == driver_id,
                )
                .order_by(InventoryTransferHeader.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if pending_handshake is not None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "مرفوض: لديك حوالة معلقة من الإدارة (مصافحة). "
                    "يرجى تأكيدها أو رفضها أولاً."
                ),
            )

        if visit.status == "Completed":
            await reverse_previous_visit_state(
                db,
                visit,
                active_session,
                shop,
                admin_id=driver_id,
            )

        debt_paid_input = Decimal(str(payload.debt_paid))
        original_shop_balance = Decimal(str(shop.current_balance or "0.000"))
        cash_collected = Decimal(str(payload.cash_collected))

        if debt_paid_input < Decimal("0") or cash_collected < Decimal("0"):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: لا يمكن إدخال قيم مالية سالبة في التحصيل أو النقد.",
            )

        if debt_paid_input > Decimal("0"):
            if original_shop_balance <= Decimal("0"):
                raise HTTPException(
                    status_code=400,
                    detail=f"مرفوض: المحل رصيده دائن أو مُصفر ({original_shop_balance}). لا توجد ذمم.",
                )
            if debt_paid_input > original_shop_balance:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"مرفوض: التحصيل ({debt_paid_input}) أكبر من ذمة المحل "
                        f"({original_shop_balance})."
                    ),
                )

        if visit.status == "Pending":
            visit.visit_timestamp = get_utc_now()

        visit.outcome = payload.outcome
        visit.status = "Completed" if payload.outcome in {"Sale", "NoSale"} else "Pending"
        visit.notes = payload.notes
        visit.latitude = payload.latitude if payload.latitude is not None else visit.latitude
        visit.longitude = payload.longitude if payload.longitude is not None else visit.longitude
        visit.shop_balance_before = original_shop_balance
        visit.is_emergency = payload.is_emergency or visit.is_emergency
        visit.work_session_id = active_session.id

        if payload.outcome == "Postponed" and (
            payload.cart_items
            or payload.returns
            or payload.debt_paid > Decimal("0")
            or payload.cash_collected > Decimal("0")
        ):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: لا يمكن تسجيل مبيعات أو مرتجعات أو تحصيل لزيارة حالتها (مؤجلة).",
            )

        has_real_sales = any(
            item.quantity > 0 or item.packs_quantity > 0
            for item in payload.cart_items
        )
        if payload.outcome == "NoSale" and (
            has_real_sales or cash_collected > Decimal("0")
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "مرفوض أمنياً: لا يمكن تسجيل مبيعات حقيقية أو كاش نقدي لحالة "
                    "(لا يوجد بيع). يسمح بالمرتجعات والعينات فقط، أو تحصيل ديون سابقة."
                ),
            )

        cart_pids = [item.product_variant_id for item in payload.cart_items]
        ret_keys = [
            (ret.product_variant_id, ret.batch_id, ret.return_type)
            for ret in payload.returns
        ]
        if len(cart_pids) != len(set(cart_pids)):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: سلة المبيعات تحتوي على أصناف مكررة.",
            )
        if len(ret_keys) != len(set(ret_keys)):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: المرتجعات تحتوي السطر نفسه (الصنف/الدفعة/النوع) أكثر من مرة.",
            )
        if payload.outcome == "Sale" and not payload.cart_items:
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: لا يمكن تسجيل حالة (بيع) دون وجود منتجات فعلية في السلة.",
            )

        all_var_ids = sorted(
            set(cart_pids + [ret.product_variant_id for ret in payload.returns])
        )
        variants_map = {}
        if all_var_ids:
            variant_rows = (
                await db.execute(
                    select(ProductVariant)
                    .filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(all_var_ids),
                    )
                    .order_by(ProductVariant.id.asc())
                )
            ).scalars().all()
            variants_map = {variant.id: variant for variant in variant_rows}
            missing_variants = sorted(set(all_var_ids) - set(variants_map))
            if missing_variants:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "أحد المنتجات غير موجود أو لا يتبع الشركة الحالية: "
                        f"{missing_variants[:10]}"
                    ),
                )

        # Batch المرتجع قد يكون منتهياً/غير فعال، لكنه يجب أن يكون حقيقياً ومن نفس الصنف والشركة.
        return_batch_ids = sorted({ret.batch_id for ret in payload.returns})
        if return_batch_ids:
            batch_rows = (
                await db.execute(
                    select(ProductBatch.id, ProductBatch.product_variant_id)
                    .filter(
                        ProductBatch.company_id == company_id,
                        ProductBatch.id.in_(return_batch_ids),
                    )
                    .order_by(ProductBatch.id.asc())
                )
            ).all()
            return_batch_map = {
                int(batch_id): int(product_variant_id)
                for batch_id, product_variant_id in batch_rows
            }
            if set(return_batch_map) != set(return_batch_ids):
                raise HTTPException(
                    status_code=400,
                    detail="إحدى دفعات المرتجع غير موجودة أو لا تتبع الشركة الحالية.",
                )
            for ret in payload.returns:
                if return_batch_map.get(ret.batch_id) != ret.product_variant_id:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"الدفعة ({ret.batch_id}) لا تتبع الصنف "
                            f"({ret.product_variant_id}) المحدد في المرتجع."
                        ),
                    )

        for variant in variants_map.values():
            if variant.packs_per_carton is None or int(variant.packs_per_carton) <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"إعداد عدد الحبات في الكرتونة غير صالح للصنف ({variant.variant_name}).",
                )

        company_local_date = await get_company_local_date(db, company_id)

        sample_items = [
            item
            for item in payload.cart_items
            if item.sample_quantity > 0 or item.sample_packs_quantity > 0
        ]
        if sample_items:
            sample_pids = sorted({item.product_variant_id for item in sample_items})
            past_rows = (
                await db.execute(
                    select(
                        VisitItem.product_variant_id,
                        func.sum(
                            VisitItem.sample_quantity * ProductVariant.packs_per_carton
                            + VisitItem.sample_packs_quantity
                        ),
                    )
                    .join(
                        Visit,
                        and_(
                            Visit.company_id == VisitItem.company_id,
                            Visit.id == VisitItem.visit_id,
                        ),
                    )
                    .join(
                        ProductVariant,
                        and_(
                            ProductVariant.company_id == VisitItem.company_id,
                            ProductVariant.id == VisitItem.product_variant_id,
                        ),
                    )
                    .join(
                        WorkSession,
                        and_(
                            WorkSession.company_id == Visit.company_id,
                            WorkSession.id == Visit.work_session_id,
                        ),
                    )
                    .filter(
                        VisitItem.company_id == company_id,
                        Visit.company_id == company_id,
                        Visit.driver_id == driver_id,
                        WorkSession.company_id == company_id,
                        WorkSession.driver_id == driver_id,
                        WorkSession.session_date == company_local_date,
                        Visit.status == "Completed",
                        VisitItem.product_variant_id.in_(sample_pids),
                        VisitItem.is_cancelled.is_(False),
                    )
                    .group_by(VisitItem.product_variant_id)
                )
            ).all()
            past_samples_map = {
                int(product_variant_id): int(total or 0)
                for product_variant_id, total in past_rows
            }

            for item in sample_items:
                variant = variants_map[item.product_variant_id]
                ppc = int(variant.packs_per_carton)
                requested_packs = item.sample_quantity * ppc + item.sample_packs_quantity
                past_packs = past_samples_map.get(item.product_variant_id, 0)
                max_allowed_packs = (
                    int(getattr(variant, "default_max_samples_per_day", 0) or 0) * ppc
                )
                # نحافظ على Workflow الحالي: صفر = لا يوجد سقف مفعل حالياً.
                if max_allowed_packs > 0 and past_packs + requested_packs > max_allowed_packs:
                    max_cartons = max_allowed_packs // ppc
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "مرفوض أمنياً: تجاوزت الحد المسموح من العينات لمنتج "
                            f"({variant.variant_name}). المسموح لك باليوم: {max_cartons} كرتونة."
                        ),
                    )

        if locked_original_status == "Pending":
            for existing_item in list(visit.items):
                await db.delete(existing_item)
            for existing_return in list(visit.returns):
                await db.delete(existing_return)
            visit.items.clear()
            visit.returns.clear()
        else:
            for existing_item in visit.items:
                if not getattr(existing_item, "is_cancelled", False):
                    existing_item.is_cancelled = True
            for existing_return in visit.returns:
                if not getattr(existing_return, "is_cancelled", False):
                    existing_return.is_cancelled = True

        total_final_amount = Decimal("0.000")
        total_base_amount = Decimal("0.000")
        total_discount = Decimal("0.000")
        total_tax = Decimal("0.000")

        current_tax_pct = await get_setting(
            db,
            company_id,
            "tax_percentage",
            Decimal("0.000"),
            Decimal,
            strict_conversion=True,
        )
        active_offers = (
            await db.execute(
                select(OfferRule)
                .filter_by(company_id=company_id, is_active=True)
                .order_by(OfferRule.threshold_quantity.desc(), OfferRule.id.asc())
            )
        ).scalars().all()

        item_contexts = []
        return_contexts = []
        outgoing_requests = {}

        # Pass 1: نحسب الفاتورة والبونص أولاً ثم نجمع طلب FEFO لكل صنف.
        for line_index, item in enumerate(payload.cart_items):
            variant = variants_map[item.product_variant_id]
            if not variant.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"مرفوض: المنتج ({variant.variant_name}) مسحوب من السوق أو موقوف حالياً ولا يمكن بيعه.",
                )

            ppc = int(variant.packs_per_carton)
            invoice = calculate_invoice(
                item.quantity,
                item.packs_quantity,
                variant.price_per_carton,
                variant.price_per_pack,
                current_tax_pct,
                active_offers,
                company_id=company_id,
                packs_per_carton=ppc,
                variant_id=item.product_variant_id,
            )
            final_bonus_cartons = int(invoice["bonus_units"])
            total_issue_packs = (
                item.quantity * ppc
                + item.packs_quantity
                + final_bonus_cartons * ppc
                + item.sample_quantity * ppc
                + item.sample_packs_quantity
            )
            if total_issue_packs > 0:
                outgoing_requests[item.product_variant_id] = (
                    outgoing_requests.get(item.product_variant_id, 0) + total_issue_packs
                )

            item_contexts.append(
                {
                    "line_index": line_index,
                    "item": item,
                    "variant": variant,
                    "invoice": invoice,
                    "bonus_cartons": final_bonus_cartons,
                    "total_issue_packs": total_issue_packs,
                }
            )
            total_final_amount += Decimal(str(invoice["final_amount"]))
            total_base_amount += Decimal(str(invoice["base_amount"]))
            total_discount += Decimal(str(invoice["discount_applied"]))
            total_tax += Decimal(str(invoice["tax_amount"]))

        # Workflow المرتجع محفوظ: استبدال 1:1، لكن الوارد التالف يحمل Batch صريحاً.
        for return_index, ret in enumerate(payload.returns):
            variant = variants_map[ret.product_variant_id]
            ppc = int(variant.packs_per_carton)
            total_return_packs = ret.quantity * ppc + ret.packs_quantity
            outgoing_requests[ret.product_variant_id] = (
                outgoing_requests.get(ret.product_variant_id, 0) + total_return_packs
            )
            return_contexts.append(
                {
                    "return_index": return_index,
                    "ret": ret,
                    "variant": variant,
                    "total_return_packs": total_return_packs,
                }
            )

        fefo_allocations = {}
        if outgoing_requests:
            fefo_allocations = await allocate_fefo_inventory_batch(
                db,
                company_id=company_id,
                location_id=veh_loc_id,
                requests=outgoing_requests,
                as_of_date=company_local_date,
                require_full=True,
            )

        allocation_state = {
            variant_id: [[int(batch_id), int(quantity)] for batch_id, quantity in allocations]
            for variant_id, allocations in fefo_allocations.items()
        }

        def consume_fefo(variant_id: int, quantity: int):
            if quantity <= 0:
                return []
            buckets = allocation_state.get(variant_id, [])
            remaining = quantity
            consumed = []
            for bucket in buckets:
                if remaining <= 0:
                    break
                batch_id, available = bucket
                if available <= 0:
                    continue
                take = min(available, remaining)
                consumed.append((batch_id, take))
                bucket[1] -= take
                remaining -= take
            if remaining != 0:
                raise RuntimeError(
                    f"FEFO allocation invariant violated for variant {variant_id}."
                )
            return consumed

        movement_specs = []
        request_token = str(payload.request_id)

        # البيع/البونص/العينات: شاشة المندوب لا ترى Batch؛ الخادم يستهلك FEFO تلقائياً.
        for ctx in item_contexts:
            item = ctx["item"]
            variant = ctx["variant"]
            for segment_index, (batch_id, qty) in enumerate(
                consume_fefo(item.product_variant_id, ctx["total_issue_packs"])
            ):
                movement_specs.append(
                    {
                        "product_variant_id": item.product_variant_id,
                        "batch_id": batch_id,
                        "quantity": qty,
                        "movement_kind": "PHYSICAL",
                        "reference_type": "VISIT_ITEM_OUT",
                        "reference_id": str(visit.id),
                        "idempotency_key": (
                            f"VIS-{visit.id}-{request_token}-I{ctx['line_index']}-"
                            f"B{batch_id}-S{segment_index}"
                        ),
                        "source_location_id": veh_loc_id,
                        "destination_location_id": None,
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": None,
                        "work_session_id": active_session.id,
                        "notes": (
                            f"صرف زيارة للمحل {shop.name}: "
                            f"بيع={item.quantity} كرتونة + {item.packs_quantity} حبة، "
                            f"بونص={ctx['bonus_cartons']} كرتونة، "
                            f"عينات={item.sample_quantity} كرتونة + {item.sample_packs_quantity} حبة."
                        ),
                    }
                )

            db.add(
                VisitItem(
                    company_id=company_id,
                    visit_id=visit.id,
                    product_variant_id=item.product_variant_id,
                    quantity=item.quantity,
                    packs_quantity=item.packs_quantity,
                    bonus_quantity=ctx["bonus_cartons"],
                    sample_quantity=item.sample_quantity,
                    sample_packs_quantity=item.sample_packs_quantity,
                    sample_reason=item.sample_reason,
                    price_per_unit_at_sale=variant.price_per_carton,
                    total_price=Decimal(str(ctx["invoice"]["final_amount"])),
                )
            )

        # المرتجع: البديل الصالح يخرج FEFO، والمرتجع نفسه يدخل DAMAGED على Batch الممسوح.
        for ctx in return_contexts:
            ret = ctx["ret"]
            total_return_packs = ctx["total_return_packs"]
            for segment_index, (batch_id, qty) in enumerate(
                consume_fefo(ret.product_variant_id, total_return_packs)
            ):
                movement_specs.append(
                    {
                        "product_variant_id": ret.product_variant_id,
                        "batch_id": batch_id,
                        "quantity": qty,
                        "movement_kind": "PHYSICAL",
                        "reference_type": "VISIT_EXCHANGE_OUT",
                        "reference_id": str(visit.id),
                        "idempotency_key": (
                            f"VIS-{visit.id}-{request_token}-X{ctx['return_index']}-"
                            f"B{batch_id}-S{segment_index}"
                        ),
                        "source_location_id": veh_loc_id,
                        "destination_location_id": None,
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": None,
                        "work_session_id": active_session.id,
                        "notes": (
                            f"استبدال 1:1 للمحل {shop.name}; "
                            f"إخراج بضاعة صالحة مقابل مرتجع {ret.return_type}."
                        ),
                    }
                )

            movement_specs.append(
                {
                    "product_variant_id": ret.product_variant_id,
                    "batch_id": ret.batch_id,
                    "quantity": total_return_packs,
                    "movement_kind": "PHYSICAL",
                    "reference_type": "VISIT_RETURN_IN",
                    "reference_id": str(visit.id),
                    "idempotency_key": (
                        f"VIS-{visit.id}-{request_token}-R{ctx['return_index']}-B{ret.batch_id}"
                    ),
                    "source_location_id": None,
                    "destination_location_id": veh_loc_id,
                    "source_stock_status": None,
                    "destination_stock_status": "DAMAGED",
                    "work_session_id": active_session.id,
                    "notes": (
                        f"استلام مرتجع {ret.return_type} من المحل {shop.name}; "
                        f"Batch={ret.batch_id}. "
                        f"{('السبب: ' + ret.reason) if ret.reason else ''}"
                    ).strip(),
                }
            )

            db.add(
                VisitReturn(
                    company_id=company_id,
                    visit_id=visit.id,
                    product_variant_id=ret.product_variant_id,
                    batch_id=ret.batch_id,
                    quantity=ret.quantity,
                    packs_quantity=ret.packs_quantity,
                    return_type=ret.return_type,
                    reason=ret.reason,
                )
            )

        if any(
            remaining_qty != 0
            for buckets in allocation_state.values()
            for _, remaining_qty in buckets
        ):
            raise RuntimeError("Unconsumed FEFO allocation detected.")

        if movement_specs:
            applied_movements = await apply_inventory_movements_batch(
                db,
                company_id=company_id,
                performed_by=driver_id,
                movements=movement_specs,
            )
            if len(applied_movements) != len(movement_specs):
                raise RuntimeError("Inventory movement batch result size mismatch.")

        if payload.outcome == "Sale":
            if cash_collected > total_final_amount:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"مرفوض: النقد المحصل ({cash_collected}) لا يمكن أن يتجاوز "
                        f"قيمة الفاتورة ({total_final_amount}). لسداد الديون السابقة "
                        "استخدم حقل التحصيل المخصص."
                    ),
                )
            new_debt = total_final_amount - cash_collected
            if new_debt > Decimal("0"):
                is_allowed, msg = await check_debt_limits(
                    db,
                    company_id,
                    driver_id,
                    shop.id,
                    new_debt,
                    pre_fetched_driver=current_driver,
                )
                if not is_allowed:
                    raise HTTPException(status_code=403, detail=msg)
        else:
            new_debt = Decimal("0.000")
            total_final_amount = Decimal("0.000")
            total_base_amount = Decimal("0.000")
            total_discount = Decimal("0.000")
            total_tax = Decimal("0.000")

        visit.amount_before_tax_and_discount = total_base_amount
        visit.discount_applied = total_discount
        visit.tax_percentage_applied = (
            current_tax_pct if payload.outcome == "Sale" else Decimal("0.000")
        )
        visit.tax_amount = total_tax
        visit.final_amount_due = total_final_amount
        visit.cash_collected = (
            cash_collected if payload.outcome == "Sale" else Decimal("0.000")
        )
        visit.debt_paid = (
            debt_paid_input if payload.outcome != "Postponed" else Decimal("0.000")
        )

        if payload.outcome == "NoSale":
            visit.no_sale_reason = payload.notes
        elif payload.outcome == "Sale":
            visit.no_sale_reason = None
        else:
            visit.no_sale_reason = payload.notes

        # منطق الذمم الحالي محفوظ كما هو؛ Patch المخزون لا يعيد تصميمه.
        if payload.outcome != "Postponed":
            new_balance = original_shop_balance + new_debt - debt_paid_input
            if new_balance < Decimal("0"):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "مرفوض محاسبياً: التحصيل أكبر من إجمالي الدين. "
                        f"الرصيد سيصبح بالسالب ({new_balance})."
                    ),
                )
            shop.current_balance = new_balance
            visit.shop_balance_after = new_balance

            if debt_paid_input > Decimal("0"):
                db.add(
                    SystemAuditLog(
                        company_id=company_id,
                        admin_id=driver_id,
                        target_id=f"Shop_{shop.id}_Visit_{visit.id}",
                        action_type="DEBT_COLLECTION",
                        old_value=f"Balance: {original_shop_balance}",
                        new_value=(
                            f"Collected: {debt_paid_input} | New Balance: {new_balance}"
                        ),
                    )
                )
        else:
            visit.shop_balance_after = original_shop_balance

        if payload.outcome in {"Sale", "NoSale"}:
            if has_active_shortage:
                await db.execute(
                    update(ShortageRequest)
                    .where(
                        ShortageRequest.company_id == company_id,
                        ShortageRequest.shop_id == shop.id,
                        ShortageRequest.status == "pending",
                    )
                    .values(status="fulfilled")
                )

            if shop.zone_id == current_route.zone_id:
                visit.is_emergency = False
                # نفس Workflow القديم لمنع ظهور المحل مرتين؛ أضفنا Tenant scope فقط.
                await db.execute(
                    delete(Visit).where(
                        Visit.company_id == company_id,
                        Visit.shop_id == shop.id,
                        Visit.driver_id == active_session.driver_id,
                        Visit.status == "Pending",
                        Visit.id != visit.id,
                    )
                )

        response_payload = {
            "message": "Visit updated successfully",
            "new_balance": str(shop.current_balance or "0.000"),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryReversalError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        logger.error(
            f"إعداد أو قيمة غير صالحة أثناء تحديث الزيارة: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=f"تعذر تنفيذ الزيارة بسبب إعداد غير صالح: {str(exc)}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(
            f"خطأ غير متوقع أثناء تحديث الزيارة: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء حفظ الزيارة.",
        ) from exc
'''

func_pattern = re.compile(
    r'@router\.put\("/visits/\{visit_id\}", status_code=200\)\n'
    r'async def update_visit\(.*?'
    r'(?=\n# =========================================\n# 5\.)',
    flags=re.S,
)
matches = list(func_pattern.finditer(driver))
if len(matches) != 1:
    raise SystemExit(
        f"PATCH_ABORT: update_visit replacement anchor expected 1 function, found {len(matches)}."
    )
old_update_visit = matches[0].group(0)
if "SessionInventory" not in old_update_visit or "InventoryLedger" not in old_update_visit:
    raise SystemExit(
        "PATCH_ABORT: update_visit لا يبدو النسخة Legacy المتوقعة أو تم تعديله جزئياً. راجع diff قبل المتابعة."
    )
driver = driver[:matches[0].start()] + NEW_UPDATE_VISIT + driver[matches[0].end():]

# -----------------------------------------------------------------------------
# Hard validation BEFORE writing anything.
# -----------------------------------------------------------------------------
checks = [
    ("models batch FK", "fk_visit_return_tenant_batch" in models),
    ("models batch_id", "batch_id           = Column(Integer, nullable=False, index=True)" in models),
    ("schemas request_id", "request_id: UUID" in schemas),
    ("schemas return batch", "class VisitReturnInput(RequestModel):\n    product_variant_id: PositiveDbInt\n    batch_id: PositiveDbInt" in schemas),
    ("driver patch marker", f"# PATCH: {PATCH_ID}" in driver),
    ("driver FEFO", "allocate_fefo_inventory_batch" in NEW_UPDATE_VISIT),
    ("driver unified movements", "apply_inventory_movements_batch" in NEW_UPDATE_VISIT),
    ("driver request idempotency", "begin_idempotent_operation" in NEW_UPDATE_VISIT),
]
failed = [name for name, ok in checks if not ok]
if failed:
    raise SystemExit(f"PATCH_ABORT: self-check failed: {failed}")

for label, text, path in (
    ("models.py", models, MODELS),
    ("schemas.py", schemas, SCHEMAS),
    ("driver.py", driver, DRIVER),
):
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(
            f"PATCH_ABORT: AST validation failed for {label}: line {exc.lineno}: {exc.msg}"
        ) from exc

# Ensure legacy live-stock engine is gone specifically from the replaced function.
new_match = func_pattern.search(driver)
if not new_match:
    raise SystemExit("PATCH_ABORT: update_visit disappeared after replacement.")
new_block = new_match.group(0)
for forbidden in ("SessionInventory", "InventoryLedger", "MainWarehouse", "VehicleLoad"):
    if re.search(rf"\b{forbidden}\b", new_block):
        raise SystemExit(f"PATCH_ABORT: legacy symbol remains inside update_visit: {forbidden}")

write_source(MODELS, models, models_nl)
write_source(SCHEMAS, schemas, schemas_nl)
write_source(DRIVER, driver, driver_nl)

print(f"{PATCH_ID}_OK")
print("MODELS_OK: VisitReturn is batch-aware and tenant-safe")
print("SCHEMAS_OK: return batch_id + visit request_id")
print("DRIVER_OK: update_visit -> Auto-FEFO + InventoryMovement + request idempotency")
print("WORKFLOW_OK: Sale/NoSale/Postponed/debt/samples/emergency/1:1 exchange preserved")
