from __future__ import annotations
import ast, re, shutil
from pathlib import Path

PATCH_NAME = 'DRIVER_RECONCILIATION_FREEZE_GATE'

def locate_root():
    cwd = Path.cwd().resolve()
    here = Path(__file__).resolve().parent
    for root in (cwd, here, cwd.parent, here.parent):
        if (root/'wa_backend'/'models.py').is_file():
            return root
        if root.name == 'wa_backend' and (root/'models.py').is_file():
            return root.parent
    raise SystemExit('PATCH_ABORT: cannot locate wa_backend/models.py')

ROOT = locate_root()
PATHS = {
    'models': ROOT/'wa_backend'/'models.py',
    'services': ROOT/'wa_backend'/'services.py',
    'driver': ROOT/'wa_backend'/'api'/'driver.py',
    'recon': ROOT/'wa_backend'/'api'/'reconciliation.py',
}
BACKUP_DIR = ROOT/'.patch_backups'/PATCH_NAME

def read_source(path):
    raw=path.read_bytes()
    nl='\r\n' if b'\r\n' in raw else '\n'
    return raw.decode('utf-8').replace('\r\n','\n'), nl

def write_source(path,text,nl):
    if nl=='\r\n':
        text=text.replace('\n','\r\n')
    path.write_bytes(text.encode('utf-8'))

def replace_once(text,old,new,label):
    c=text.count(old)
    if c != 1:
        raise SystemExit(f'PATCH_ABORT: {label}: expected 1 anchor, found {c}')
    return text.replace(old,new,1)

def func_span(text,name):
    tree=ast.parse(text)
    node=next((n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name),None)
    if node is None:
        raise SystemExit(f'PATCH_ABORT: function {name} not found')
    lines=text.splitlines(keepends=True)
    s=sum(len(x) for x in lines[:node.lineno-1])
    e=sum(len(x) for x in lines[:node.end_lineno])
    return s,e,text[s:e]

def replace_in_func(text,name,old,new,label):
    s,e,b=func_span(text,name)
    c=b.count(old)
    if c != 1:
        raise SystemExit(f'PATCH_ABORT: {label}: expected 1 anchor in {name}, found {c}')
    return text[:s]+b.replace(old,new,1)+text[e:]

OPS = {'models': [('global', None, 'from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Float, Text, JSON, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData, text, Table, ForeignKeyConstraint', 'from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Text, JSON, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData, text, Table, ForeignKeyConstraint', 'remove dead Float'), ('global', None, "        UniqueConstraint('company_id', 'id', name='uq_dispatch_routes_company_id'),\n", "        UniqueConstraint('company_id', 'id', name='uq_dispatch_routes_company_id'),\n        UniqueConstraint('company_id', 'work_session_id', name='uq_dispatch_routes_work_session'),\n", 'route/work-session unique'), ('global', None, "        CheckConstraint('work_session_id IS NULL OR driver_id IS NOT NULL',\n                        name='chk_dispatch_route_session_requires_driver'),\n", "        CheckConstraint('work_session_id IS NULL OR driver_id IS NOT NULL',\n                        name='chk_dispatch_route_session_requires_driver'),\n        CheckConstraint('work_session_id IS NULL OR vehicle_id IS NOT NULL',\n                        name='chk_dispatch_route_session_requires_vehicle'),\n", 'route session requires vehicle'), ('global', None, "        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],\n                             ondelete='RESTRICT', name='fk_shortage_tenant_variant'),\n", '        ForeignKeyConstraint([\'company_id\', \'product_variant_id\'], [\'product_variants.company_id\', \'product_variants.id\'],\n                             ondelete=\'RESTRICT\', name=\'fk_shortage_tenant_variant\'),\n        ForeignKeyConstraint([\'company_id\', \'fulfilled_by_visit_id\'], [\'visits.company_id\', \'visits.id\'],\n                             ondelete=\'RESTRICT\', name=\'fk_shortage_tenant_fulfilled_visit\'),\n        CheckConstraint(\n            "((fulfilled_by_visit_id IS NULL AND fulfilled_at IS NULL) OR "\n            "(fulfilled_by_visit_id IS NOT NULL AND fulfilled_at IS NOT NULL))",\n            name=\'chk_shortage_fulfillment_pair\'\n        ),\n', 'shortage fulfillment provenance constraints'), ('global', None, '    notes      = Column(Text,       nullable=True)   # بدل product_name - لو في ملاحظات إضافية\n    created_at = Column(DateTime,   nullable=False,  default=utc_now)  # FIX ①\n', '    notes      = Column(Text,       nullable=True)   # بدل product_name - لو في ملاحظات إضافية\n    fulfilled_by_visit_id = Column(Integer, nullable=True, index=True)\n    fulfilled_at          = Column(DateTime, nullable=True, index=True)\n    created_at = Column(DateTime,   nullable=False,  default=utc_now)  # FIX ①\n', 'shortage fulfillment provenance fields')], 'services': [('global', None, '    Driver,\n    Shop,\n    WorkSession,\n', '    Driver,\n    Shop,\n    ShortageRequest,\n    WorkSession,\n', 'ShortageRequest import'), ('func', 'reverse_previous_visit_state', '        if locked_session.is_settled:\n            raise InventoryReversalError(\n                "مرفوض: لا يمكن عكس زيارة تابعة لجلسة تمت تسويتها واعتمادها."\n            )\n', '        if locked_session.inventory_reconciled_at is not None:\n            raise InventoryReversalError(\n                "مرفوض: لا يمكن عكس زيارة بعد ختم التسوية المخزنية لجلسة العمل."\n            )\n        if locked_session.is_settled:\n            raise InventoryReversalError(\n                "مرفوض: لا يمكن عكس زيارة تابعة لجلسة تمت تسويتها واعتمادها."\n            )\n', 'reverse freeze'), ('func', 'reverse_previous_visit_state', '    locked_shop.current_balance = new_balance\n    locked_visit.amount_before_tax_and_discount = Decimal("0.0")\n', '    await db_session.execute(\n        update(ShortageRequest)\n        .where(\n            ShortageRequest.company_id == company_id,\n            ShortageRequest.fulfilled_by_visit_id == locked_visit.id,\n            ShortageRequest.status == "fulfilled",\n        )\n        .values(\n            status="pending",\n            fulfilled_by_visit_id=None,\n            fulfilled_at=None,\n        )\n    )\n\n    locked_shop.current_balance = new_balance\n    locked_visit.amount_before_tax_and_discount = Decimal("0.0")\n', 'shortage reversal provenance'), ('func', 'finalize_vehicle_inventory_reconciliation', '    actor_id = (\n        await db_session.execute(\n            select(Driver.id).filter_by(\n                company_id=company_id,\n                id=settled_by,\n                is_active=True,\n            ).with_for_update(read=True)\n        )\n    ).scalar_one_or_none()\n    if actor_id is None:\n        raise InventoryMutationError("منفذ التسوية غير موجود/غير فعال أو خارج الشركة.")\n\n    await acquire_inventory_location_guard(\n        db_session,\n        company_id,\n        vehicle_location_id,\n        exclusive=True,\n    )\n\n    work_session = (\n', '    actor = (\n        await db_session.execute(\n            select(Driver.id, Driver.is_admin).filter_by(\n                company_id=company_id,\n                id=settled_by,\n                is_active=True,\n            ).with_for_update(read=True)\n        )\n    ).one_or_none()\n    if actor is None:\n        raise InventoryMutationError("منفذ التسوية غير موجود/غير فعال أو خارج الشركة.")\n\n    work_session = (\n', 'finalizer actor'), ('func', 'finalize_vehicle_inventory_reconciliation', '    if work_session.end_time is None:\n        raise InventoryMutationError("لا يمكن تسوية عهدة جلسة عمل لم تنتهِ بعد.")\n\n    location = (\n', '    if work_session.end_time is None:\n        raise InventoryMutationError("لا يمكن تسوية عهدة جلسة عمل لم تنتهِ بعد.")\n    if settled_by != work_session.driver_id and not bool(actor.is_admin):\n        raise InventoryMutationError("تثبيت عهدة الجلسة مسموح لصاحب الجلسة أو لمشرف فعال من نفس الشركة فقط.")\n\n    # ترتيب الأقفال الرسمي لـ VEHICLE_RECON: WorkSession -> inventory-location guard.\n    await acquire_inventory_location_guard(\n        db_session,\n        company_id,\n        vehicle_location_id,\n        exclusive=True,\n    )\n\n    location = (\n', 'finalizer authorization and guard'), ('func', 'finalize_vehicle_inventory_reconciliation', '                InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),\n                InventoryBalance.on_hand_quantity > 0,\n', '                InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),\n                or_(\n                    InventoryBalance.on_hand_quantity > 0,\n                    InventoryBalance.reserved_quantity > 0,\n                ),\n', 'finalizer sees reservations'), ('func', 'finalize_vehicle_inventory_reconciliation', '    if len(final_rows) > _MAX_STOCKTAKE_POST_LINES:\n        raise InventoryMutationError("رصيد السيارة يتجاوز الحد الآمن لتثبيت Ending Snapshot.")\n\n    final_map: Dict[Tuple[int, str], int] = {}\n', '    if len(final_rows) > _MAX_STOCKTAKE_POST_LINES:\n        raise InventoryMutationError("رصيد السيارة يتجاوز الحد الآمن لتثبيت Ending Snapshot.")\n    if any(int(row.reserved_quantity or 0) != 0 for row in final_rows):\n        raise InventoryMutationError(\n            "لا يمكن ختم عهدة السيارة بوجود مخزون محجوز؛ يجب تحرير جميع الحجوزات أولاً."\n        )\n\n    final_map: Dict[Tuple[int, str], int] = {}\n', 'finalizer reservation invariant'), ('func', 'post_approved_stocktake_adjustments', '    probe = (\n        await db_session.execute(\n            select(StocktakeSession.location_id).filter_by(\n                company_id=company_id,\n                id=stocktake_session_id,\n            )\n        )\n    ).scalar_one_or_none()\n    if probe is None:\n        raise InventoryMutationError("جلسة الجرد غير موجودة أو لا تتبع الشركة.")\n\n    # الترحيل عملية حصرية على الموقع؛ يمنع أي حركة متزامنة أثناء تثبيت جميع الفروقات.\n    await acquire_inventory_location_guard(\n        db_session,\n        company_id,\n        int(probe),\n        exclusive=True,\n    )\n\n    session = (\n', '    probe = (\n        await db_session.execute(\n            select(\n                StocktakeSession.location_id,\n                StocktakeSession.stocktake_type,\n                StocktakeSession.related_work_session_id,\n            ).filter_by(\n                company_id=company_id,\n                id=stocktake_session_id,\n            )\n        )\n    ).one_or_none()\n    if probe is None:\n        raise InventoryMutationError("جلسة الجرد غير موجودة أو لا تتبع الشركة.")\n\n    probe_location_id, probe_type, probe_work_session_id = probe\n    # VEHICLE_RECON يلتزم ترتيب أقفال موحد: WorkSession -> inventory-location guard.\n    if probe_type == "VEHICLE_RECON":\n        if probe_work_session_id is None:\n            raise InventoryMutationError("VEHICLE_RECON بدون WorkSession مرتبط.")\n        locked_probe_session = (\n            await db_session.execute(\n                select(WorkSession.id).filter_by(\n                    company_id=company_id,\n                    id=probe_work_session_id,\n                ).with_for_update()\n            )\n        ).scalar_one_or_none()\n        if locked_probe_session is None:\n            raise InventoryMutationError("جلسة العمل المرتبطة بـ VEHICLE_RECON غير موجودة أو خارج الشركة.")\n\n    # الترحيل عملية حصرية على الموقع؛ يمنع أي حركة متزامنة أثناء تثبيت جميع الفروقات.\n    await acquire_inventory_location_guard(\n        db_session,\n        company_id,\n        int(probe_location_id),\n        exclusive=True,\n    )\n\n    session = (\n', 'post lock order'), ('func', 'post_approved_stocktake_adjustments', '    if session is None or session.location_id != probe:\n        raise InventoryMutationError("جلسة الجرد تغيرت أو لم تعد صالحة للترحيل.")\n', '    if (\n        session is None\n        or session.location_id != probe_location_id\n        or session.stocktake_type != probe_type\n        or session.related_work_session_id != probe_work_session_id\n    ):\n        raise InventoryMutationError("جلسة الجرد تغيرت أو لم تعد صالحة للترحيل.")\n', 'post probe revalidate'), ('func', 'post_approved_stocktake_adjustments', '        if session.stocktake_type == "VEHICLE_RECON":\n            settled_state = (\n                await db_session.execute(\n                    select(WorkSession.is_settled).filter_by(\n                        company_id=company_id,\n                        id=session.related_work_session_id,\n                    )\n                )\n            ).scalar_one_or_none()\n            if settled_state is not True:\n                raise InventoryMutationError(\n                    "VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ الحالة غير متسقة."\n                )\n        return ordered_existing\n', '        if session.stocktake_type == "VEHICLE_RECON":\n            recon_state = (\n                await db_session.execute(\n                    select(\n                        WorkSession.inventory_reconciled_at,\n                        WorkSession.inventory_reconciled_by,\n                    ).filter_by(\n                        company_id=company_id,\n                        id=session.related_work_session_id,\n                    )\n                )\n            ).one_or_none()\n            if (\n                recon_state is None\n                or recon_state.inventory_reconciled_at is None\n                or recon_state.inventory_reconciled_by is None\n            ):\n                raise InventoryMutationError(\n                    "VEHICLE_RECON بحالة POSTED لكن WorkSession بلا ختم تسوية مخزنية مكتمل."\n                )\n            incomplete_snapshot_id = (\n                await db_session.execute(\n                    select(SessionInventorySnapshot.id)\n                    .filter(\n                        SessionInventorySnapshot.company_id == company_id,\n                        SessionInventorySnapshot.work_session_id == session.related_work_session_id,\n                        or_(\n                            SessionInventorySnapshot.ending_quantity.is_(None),\n                            SessionInventorySnapshot.settled_by.is_(None),\n                            SessionInventorySnapshot.settled_at.is_(None),\n                        ),\n                    )\n                    .limit(1)\n                )\n            ).scalar_one_or_none()\n            if incomplete_snapshot_id is not None:\n                raise InventoryMutationError(\n                    "VEHICLE_RECON بحالة POSTED لكن Ending Snapshot غير مكتمل."\n                )\n        return ordered_existing\n', 'POSTED replay uses inventory settlement')], 'driver': [('func', 'update_visit', '        if active_session is None:\n            raise HTTPException(\n                status_code=403,\n                detail="لا يمكنك تنفيذ العملية. الرجاء بدء يوم العمل أولاً.",\n            )\n', '        if active_session is None:\n            raise HTTPException(\n                status_code=403,\n                detail="لا يمكنك تنفيذ العملية. الرجاء بدء يوم العمل أولاً.",\n            )\n        if active_session.inventory_reconciled_at is not None:\n            raise HTTPException(\n                status_code=409,\n                detail="مرفوض: عهدة مخزون هذه الجلسة تم ختمها ولا تقبل أي تعديل ميداني جديد.",\n            )\n', 'visit active inventory freeze'), ('func', 'update_visit', '        if visit.work_session and visit.work_session.is_settled:\n            raise HTTPException(\n                status_code=403,\n                detail="مرفوض: لا يمكن تعديل زيارة تم تسويتها ماليًا واعتمادها من الإدارة.",\n            )\n', '        if visit.work_session and visit.work_session.inventory_reconciled_at is not None:\n            raise HTTPException(\n                status_code=409,\n                detail="مرفوض: لا يمكن تعديل زيارة بعد ختم التسوية المخزنية لجلسة العمل.",\n            )\n        if visit.work_session and visit.work_session.is_settled:\n            raise HTTPException(\n                status_code=403,\n                detail="مرفوض: لا يمكن تعديل زيارة تم تسويتها ماليًا واعتمادها من الإدارة.",\n            )\n', 'visit bound inventory freeze'), ('func', 'update_visit', '                .order_by(DispatchRoute.id.asc())\n                .limit(1)\n            )\n        ).scalars().first()\n', '                .order_by(DispatchRoute.id.asc())\n                .limit(1)\n                .with_for_update(read=True)\n            )\n        ).scalars().first()\n', 'visit route stability'), ('func', 'update_visit', '        if payload.outcome in {"Sale", "NoSale"}:\n            if has_active_shortage:\n                await db.execute(\n                    update(ShortageRequest)\n                    .where(\n                        ShortageRequest.company_id == company_id,\n                        ShortageRequest.shop_id == shop.id,\n                        ShortageRequest.status == "pending",\n                    )\n                    .values(status="fulfilled")\n                )\n\n            if shop.zone_id == current_route.zone_id:\n', '        sold_variant_ids = sorted({\n            item.product_variant_id\n            for item in payload.cart_items\n            if item.quantity > 0 or item.packs_quantity > 0\n        })\n        if payload.outcome == "Sale" and sold_variant_ids:\n            await db.execute(\n                update(ShortageRequest)\n                .where(\n                    ShortageRequest.company_id == company_id,\n                    ShortageRequest.shop_id == shop.id,\n                    ShortageRequest.status == "pending",\n                    ShortageRequest.product_variant_id.in_(sold_variant_ids),\n                )\n                .values(\n                    status="fulfilled",\n                    fulfilled_by_visit_id=visit.id,\n                    fulfilled_at=get_utc_now(),\n                )\n            )\n\n        if payload.outcome in {"Sale", "NoSale"}:\n            if shop.zone_id == current_route.zone_id:\n', 'shortage sold-product scope'), ('func', 'add_new_shop', '    stmt_session = select(WorkSession).filter_by(company_id=current_driver.company_id, driver_id=driver_id, end_time=None).order_by(WorkSession.id.desc()).limit(1)\n    active_session = (await db.execute(stmt_session)).scalars().first()\n', '    stmt_session = (\n        select(WorkSession)\n        .filter_by(company_id=current_driver.company_id, driver_id=driver_id, end_time=None)\n        .order_by(WorkSession.id.desc())\n        .limit(1)\n        .with_for_update()\n    )\n    active_session = (await db.execute(stmt_session)).scalars().first()\n', 'add-shop session lock'), ('func', 'add_new_shop', '    if not active_session:\n        raise HTTPException(status_code=403, detail="مرفوض: الرجاء بدء يوم العمل أولاً.")\n', '    if not active_session:\n        raise HTTPException(status_code=403, detail="مرفوض: الرجاء بدء يوم العمل أولاً.")\n    if active_session.inventory_reconciled_at is not None:\n        raise HTTPException(status_code=409, detail="مرفوض: عهدة مخزون هذه الجلسة مختومة ولا تقبل إضافة محلات.")\n', 'add-shop inventory freeze'), ('func', 'add_new_shop', "    stmt_route = select(DispatchRoute).filter_by(company_id=current_driver.company_id, work_session_id=active_session.id, driver_id=driver_id, status='active')\n    active_route = (await db.execute(stmt_route)).scalars().first()\n", "    stmt_route = (\n        select(DispatchRoute)\n        .filter_by(\n            company_id=current_driver.company_id,\n            work_session_id=active_session.id,\n            driver_id=driver_id,\n            status='active',\n        )\n        .order_by(DispatchRoute.id.asc())\n        .limit(1)\n        .with_for_update(read=True)\n    )\n    active_route = (await db.execute(stmt_route)).scalars().first()\n", 'add-shop route stability')], 'recon': [('func', 'reconcile_driver_end_of_day', '    company_id = int(current_driver.company_id)\n    driver_id = int(current_driver.id)\n\n    try:\n', '    company_id = int(current_driver.company_id)\n    driver_id = int(current_driver.id)\n    if session_id <= 0 or session_id > _DB_INT_MAX:\n        raise HTTPException(status_code=422, detail="session_id خارج النطاق الصحيح لقاعدة البيانات.")\n\n    try:\n', 'session id bound'), ('func', 'reconcile_driver_end_of_day', '            if existing_status == "POSTED":\n                raise HTTPException(\n                    status_code=409,\n                    detail="VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ البيانات غير متسقة وتحتاج مراجعة.",\n                )\n', '            if existing_status == "POSTED":\n                raise HTTPException(\n                    status_code=409,\n                    detail="VEHICLE_RECON بحالة POSTED لكن WorkSession بلا ختم تسوية مخزنية؛ البيانات غير متسقة وتحتاج مراجعة.",\n                )\n', 'posted wording')]}

texts={}
newlines={}
for key,path in PATHS.items():
    texts[key],newlines[key]=read_source(path)

already = all([
    'uq_dispatch_routes_work_session' in texts['models'],
    'fulfilled_by_visit_id = Column(Integer, nullable=True, index=True)' in texts['models'],
    'fulfilled_by_visit_id=visit.id' in texts['driver'],
    'ShortageRequest.fulfilled_by_visit_id == locked_visit.id' in texts['services'],
    'VEHICLE_RECON بحالة POSTED لكن WorkSession بلا ختم تسوية مخزنية مكتمل.' in texts['services'],
    'session_id خارج النطاق الصحيح لقاعدة البيانات.' in texts['recon'],
])
if already:
    print('DRIVER_RECONCILIATION_FREEZE_GATE_ALREADY_OK')
    raise SystemExit(0)

for key,file_ops in OPS.items():
    text=texts[key]
    for kind,func,old,new,label in file_ops:
        if kind=='global':
            text=replace_once(text,old,new,label)
        else:
            text=replace_in_func(text,func,old,new,label)
    try:
        ast.parse(text, filename=str(PATHS[key]))
    except SyntaxError as exc:
        raise SystemExit(f'PATCH_ABORT: AST {key}: line {exc.lineno}: {exc.msg}') from exc
    texts[key]=text

checks = [
    ('route unique', 'uq_dispatch_routes_work_session' in texts['models']),
    ('route vehicle check', 'chk_dispatch_route_session_requires_vehicle' in texts['models']),
    ('shortage provenance FK', 'fk_shortage_tenant_fulfilled_visit' in texts['models']),
    ('shortage product scope', 'ShortageRequest.product_variant_id.in_(sold_variant_ids)' in texts['driver']),
    ('visit freeze', 'visit.work_session.inventory_reconciled_at is not None' in texts['driver']),
    ('shortage reversal', 'ShortageRequest.fulfilled_by_visit_id == locked_visit.id' in texts['services']),
    ('reservation invariant', 'لا يمكن ختم عهدة السيارة بوجود مخزون محجوز' in texts['services']),
    ('actor invariant', 'مسموح لصاحب الجلسة أو لمشرف فعال' in texts['services']),
    ('posted replay', 'VEHICLE_RECON بحالة POSTED لكن WorkSession بلا ختم تسوية مخزنية مكتمل.' in texts['services']),
    ('id bound', 'session_id خارج النطاق الصحيح' in texts['recon']),
]
failed=[name for name,ok in checks if not ok]
if failed:
    raise SystemExit(f'PATCH_ABORT: self-check failed: {failed}')

for key in ('driver','services','recon'):
    for forbidden in ('SessionInventory','VehicleLoad','MainWarehouse','WarehouseLedger','InventoryLedger','InventoryTransfer'):
        if re.search(rf'\b{forbidden}\b', texts[key]):
            raise SystemExit(f'PATCH_ABORT: legacy symbol {forbidden} remains in {key}')

for key in ('driver','recon'):
    for marker in ('InventoryBalance(', 'update(InventoryBalance', 'delete(InventoryBalance', '.on_hand_quantity =', '.reserved_quantity ='):
        if marker in texts[key]:
            raise SystemExit(f'PATCH_ABORT: direct InventoryBalance write in {key}: {marker}')

BACKUP_DIR.mkdir(parents=True,exist_ok=True)
for key,path in PATHS.items():
    backup=BACKUP_DIR/path.name
    if not backup.exists():
        shutil.copy2(path,backup)

for key,path in PATHS.items():
    write_source(path,texts[key],newlines[key])

print('DRIVER_RECONCILIATION_FREEZE_GATE_OK')
print('VISIT_FREEZE_OK: inventory-reconciled sessions cannot be mutated or reversed')
print('SHORTAGE_OK: only sold variants fulfilled; reversal reopens only requests fulfilled by that Visit')
print('POSTED_REPLAY_OK: replay depends on inventory reconciliation, not financial is_settled')
print('LOCK_ORDER_OK: VEHICLE_RECON uses WorkSession -> inventory-location guard')
print('FINALIZER_OK: owner/admin actor + zero reservations required')
print('ROUTE_INVARIANTS_OK: one Route per WorkSession + bound session requires vehicle')
print('SHOP_RACE_OK: add-shop locks active WorkSession and stabilizes Route')
print('TENANT_ENGINE_OK: legacy live-stock symbols absent; endpoint direct InventoryBalance writes absent')
print('FILES_CHANGED: wa_backend/models.py + wa_backend/services.py + wa_backend/api/driver.py + wa_backend/api/reconciliation.py')
print('NEXT: rebuild empty dev schema, py_compile, git diff --check, then hostile PostgreSQL freeze-gate test')
