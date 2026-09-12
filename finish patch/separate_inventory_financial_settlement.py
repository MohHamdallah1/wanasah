from pathlib import Path
import ast, hashlib, shutil, sys

ROOT = Path.cwd()
MODELS = ROOT / 'wa_backend' / 'models.py'
SERVICES = ROOT / 'wa_backend' / 'services.py'
RECON = ROOT / 'wa_backend' / 'api' / 'reconciliation.py'
BACKUP = ROOT / '.patch_backups' / 'INVENTORY_FINANCIAL_SETTLEMENT_SEPARATION'

for p in (MODELS, SERVICES, RECON):
    if not p.exists():
        raise SystemExit(f'PATCH_ABORT: missing {p}')

texts = {p: p.read_text(encoding='utf-8') for p in (MODELS, SERVICES, RECON)}

already = (
    'inventory_reconciled_at' in texts[MODELS]
    and 'async def finalize_vehicle_inventory_reconciliation(' in texts[SERVICES]
    and 'already_reconciled' in texts[RECON]
    and 'work_session.is_settled = True' not in texts[SERVICES]
)
if already:
    print('INVENTORY_FINANCIAL_SETTLEMENT_SEPARATION_OK_ALREADY')
    sys.exit(0)

# Strict preconditions: this patch targets the exact unified reconciliation state.
required = {
    MODELS: [
        "CheckConstraint(\n            'is_settled IS FALSE OR end_time IS NOT NULL',\n            name='chk_work_session_settlement_requires_end'\n        ),",
        "is_settled            = Column(Boolean, nullable=False, default=False, server_default='false', index=True)",
        "stock_status       = Column(String(50), nullable=False, index=True)",
    ],
    SERVICES: [
        'async def finalize_vehicle_reconciliation_settlement(',
        'work_session.is_settled = True',
        'if work_session.is_settled:\n        raise InventoryMutationError(',
        '# VEHICLE_RECON لا يكتمل فعلياً قبل تثبيت Ending Snapshot وإغلاق WorkSession مخزنياً.',
    ],
    RECON: [
        'finalize_vehicle_reconciliation_settlement,',
        'if work_session.is_settled:',
        'old_value="is_settled=false"',
        '"is_settled": True,',
        '"already_settled": True,',
        'existing_status = str(existing_recon.status)',
    ],
}
for path, needles in required.items():
    for needle in needles:
        if needle not in texts[path]:
            raise SystemExit(f'PATCH_ABORT: unexpected {path}: missing precondition {needle!r}')

m = texts[MODELS]
old = """        CheckConstraint(\n            'is_settled IS FALSE OR end_time IS NOT NULL',\n            name='chk_work_session_settlement_requires_end'\n        ),\n"""
new = """        CheckConstraint(\n            'is_settled IS FALSE OR end_time IS NOT NULL',\n            name='chk_work_session_settlement_requires_end'\n        ),\n        ForeignKeyConstraint(\n            ['company_id', 'inventory_reconciled_by'],\n            ['drivers.company_id', 'drivers.id'],\n            ondelete='RESTRICT',\n            name='fk_work_session_inventory_reconciler'\n        ),\n        CheckConstraint(\n            \"((inventory_reconciled_at IS NULL AND inventory_reconciled_by IS NULL) OR \"\n            \"(inventory_reconciled_at IS NOT NULL AND inventory_reconciled_by IS NOT NULL \"\n            \"AND end_time IS NOT NULL))\",\n            name='chk_work_session_inventory_reconciliation_pair'\n        ),\n        CheckConstraint(\n            'inventory_reconciled_at IS NULL OR inventory_reconciled_at >= end_time',\n            name='chk_work_session_inventory_reconciliation_after_end'\n        ),\n        CheckConstraint(\n            'is_settled IS FALSE OR inventory_reconciled_at IS NOT NULL',\n            name='chk_work_session_financial_settlement_requires_inventory_reconciliation'\n        ),\n"""
if m.count(old) != 1:
    raise SystemExit('PATCH_ABORT: WorkSession constraint anchor not unique')
m = m.replace(old, new, 1)
old = """    is_authorized_to_sell = Column(Boolean, nullable=False, default=False, server_default='false')\n    break_start_time      = Column(DateTime, nullable=True)\n    break_end_time        = Column(DateTime, nullable=True)\n    is_settled            = Column(Boolean, nullable=False, default=False, server_default='false', index=True)\n"""
new = """    is_authorized_to_sell = Column(Boolean, nullable=False, default=False, server_default='false')\n    break_start_time      = Column(DateTime, nullable=True)\n    break_end_time        = Column(DateTime, nullable=True)\n\n    # مرحلتان مستقلتان عمداً:\n    # inventory_reconciled_* = إغلاق عهدة المخزون فقط.\n    # is_settled = التسوية المالية النهائية لدى المحاسب فقط.\n    inventory_reconciled_at = Column(DateTime, nullable=True, index=True)\n    inventory_reconciled_by = Column(Integer, nullable=True, index=True)\n    is_settled              = Column(Boolean, nullable=False, default=False, server_default='false', index=True)\n"""
if m.count(old) != 1:
    raise SystemExit('PATCH_ABORT: WorkSession columns anchor not unique')
m = m.replace(old, new, 1)
texts[MODELS] = m

s = texts[SERVICES]
old_validate = """    if work_session.is_settled:\n        raise InventoryMutationError(\n            \"جلسة العمل تمت تسويتها مسبقاً ولا تقبل VEHICLE_RECON جديداً.\"\n        )\n"""
new_validate = """    if work_session.is_settled:\n        raise InventoryMutationError(\n            \"جلسة العمل تمت تسويتها مالياً مسبقاً ولا تقبل VEHICLE_RECON جديداً.\"\n        )\n\n    if work_session.inventory_reconciled_at is not None:\n        raise InventoryMutationError(\n            \"عهدة مخزون جلسة العمل تمت مطابقتها مسبقاً ولا تقبل VEHICLE_RECON جديداً.\"\n        )\n"""
if s.count(old_validate) != 1:
    raise SystemExit('PATCH_ABORT: VEHICLE_RECON validation settlement block not unique')
s = s.replace(old_validate, new_validate, 1)
s = s.replace('async def finalize_vehicle_reconciliation_settlement(', 'async def finalize_vehicle_inventory_reconciliation(', 1)
s = s.replace(
    '# تثبيت عهدة نهاية الجلسة من الرصيد الحي بعد المطابقة/ترحيل VEHICLE_RECON.\n# هذه الدالة لا تخمّن Batch ولا تغيّر InventoryBalance؛ فقط تجمّد Ending Snapshot وتغلق WorkSession مخزنياً.',
    '# تثبيت عهدة نهاية الجلسة من الرصيد الحي بعد المطابقة/ترحيل VEHICLE_RECON.\n# هذه الدالة لا تخمّن Batch ولا تغيّر InventoryBalance ولا تنفذ التسوية المالية؛\n# فقط تجمّد Ending Snapshot وتختم inventory_reconciled_* على WorkSession.',
    1,
)
old = """    if work_session.is_settled:\n        if any(\n            row.ending_quantity is None\n            or row.settled_by is None\n            or row.settled_at is None\n            for row in snapshots\n        ):\n            raise InventoryMutationError(\"جلسة معلّمة كمسواة لكن Ending Snapshot ناقص.\")\n        return work_session\n\n    if any(\n        row.ending_quantity is not None\n        or row.settled_by is not None\n        or row.settled_at is not None\n        for row in snapshots\n    ):\n        raise InventoryMutationError(\"تم اكتشاف تسوية جزئية في SessionInventorySnapshot.\")\n"""
new = """    if work_session.is_settled and work_session.inventory_reconciled_at is None:\n        raise InventoryMutationError(\n            \"جلسة مسواة مالياً بدون ختم تسوية مخزنية؛ البيانات غير متسقة.\"\n        )\n\n    if work_session.inventory_reconciled_at is not None:\n        if work_session.inventory_reconciled_by is None:\n            raise InventoryMutationError(\"ختم التسوية المخزنية ناقص هوية المنفذ.\")\n        if any(\n            row.ending_quantity is None\n            or row.settled_by is None\n            or row.settled_at is None\n            for row in snapshots\n        ):\n            raise InventoryMutationError(\"جلسة مخزون معلّمة كمطابقة لكن Ending Snapshot ناقص.\")\n        return work_session\n\n    if work_session.inventory_reconciled_by is not None:\n        raise InventoryMutationError(\"تم اكتشاف ختم تسوية مخزنية جزئي على WorkSession.\")\n\n    if any(\n        row.ending_quantity is not None\n        or row.settled_by is not None\n        or row.settled_at is not None\n        for row in snapshots\n    ):\n        raise InventoryMutationError(\"تم اكتشاف تسوية مخزنية جزئية في SessionInventorySnapshot.\")\n"""
if s.count(old) != 1:
    raise SystemExit('PATCH_ABORT: service idempotency block not found uniquely')
s = s.replace(old, new, 1)
old = """    work_session.is_settled = True\n    await db_session.flush()\n    return work_session\n"""
new = """    work_session.inventory_reconciled_at = settled_at\n    work_session.inventory_reconciled_by = settled_by\n    # is_settled يبقى False هنا عمداً: هذا حق التسوية المالية لدى المحاسب فقط.\n    await db_session.flush()\n    return work_session\n"""
if s.count(old) != 1:
    raise SystemExit('PATCH_ABORT: service financial-settlement write anchor not unique')
s = s.replace(old, new, 1)
s = s.replace(
    '# VEHICLE_RECON لا يكتمل فعلياً قبل تثبيت Ending Snapshot وإغلاق WorkSession مخزنياً.\n    if session.stocktake_type == "VEHICLE_RECON":\n        await finalize_vehicle_reconciliation_settlement(',
    '# VEHICLE_RECON لا يكتمل مخزنياً قبل تثبيت Ending Snapshot وختم inventory_reconciled_*.\n    # التسوية المالية (WorkSession.is_settled) لا تتم هنا.\n    if session.stocktake_type == "VEHICLE_RECON":\n        await finalize_vehicle_inventory_reconciliation(',
    1,
)
# Defensive: no old helper call may remain.
if 'finalize_vehicle_reconciliation_settlement' in s:
    raise SystemExit('PATCH_ABORT: old finalize helper name still present in services.py')
texts[SERVICES] = s

r = texts[RECON]
r = r.replace('finalize_vehicle_reconciliation_settlement,', 'finalize_vehicle_inventory_reconciliation,', 1)
r = r.replace(
    '- المطابقة التامة: يثبت Ending Snapshot ويغلق WorkSession مخزنياً.',
    '- المطابقة التامة: يثبت Ending Snapshot ويختم التسوية المخزنية فقط؛ التسوية المالية تبقى للمحاسب.',
    1,
)
old = """        # State-idempotency: retry بعد نجاح المطابقة لا يعيد أي حركة أو يفتح جرداً جديداً.\n        if work_session.is_settled:\n            await db.rollback()\n            return {\n                \"message\": \"تمت تسوية عهدة هذه الجلسة مسبقاً.\",\n                \"requires_audit\": False,\n                \"already_settled\": True,\n            }\n"""
new = """        # التسوية المالية مستقلة عن التسوية المخزنية.\n        if work_session.is_settled and work_session.inventory_reconciled_at is None:\n            raise HTTPException(\n                status_code=409,\n                detail=\"الجلسة مسواة مالياً دون ختم تسوية مخزنية؛ البيانات غير متسقة.\",\n            )\n\n        # State-idempotency: retry بعد نجاح المطابقة المخزنية لا يعيد أي حركة أو يفتح جرداً جديداً.\n        if work_session.inventory_reconciled_at is not None:\n            if work_session.inventory_reconciled_by is None:\n                raise HTTPException(status_code=409, detail=\"ختم التسوية المخزنية ناقص هوية المنفذ.\")\n            await db.rollback()\n            return {\n                \"message\": \"تمت مطابقة عهدة المخزون لهذه الجلسة مسبقاً؛ التسوية المالية مستقلة.\",\n                \"requires_audit\": False,\n                \"already_reconciled\": True,\n            }\n"""
if r.count(old) != 1:
    raise SystemExit('PATCH_ABORT: reconciliation early idempotency block not unique')
r = r.replace(old, new, 1)
old = """        if not variances:\n            await finalize_vehicle_reconciliation_settlement(\n                db,\n                company_id=company_id,\n                work_session_id=work_session.id,\n                vehicle_location_id=vehicle_location_id,\n                settled_by=driver_id,\n            )\n            db.add(SystemAuditLog(\n                company_id=company_id,\n                admin_id=driver_id,\n                target_id=f\"WorkSession_{work_session.id}\",\n                action_type=\"VEHICLE_RECON_MATCHED\",\n                old_value=\"is_settled=false\",\n                new_value=json.dumps({\n                    \"is_settled\": True,\n                    \"product_count\": len(expected_map),\n                    \"vehicle_location_id\": vehicle_location_id,\n                }, ensure_ascii=False),\n            ))\n            await db.commit()\n            return {\n                \"message\": \"التسوية المخزنية مطابقة 100% وتم تثبيت عهدة نهاية الجلسة.\",\n                \"requires_audit\": False,\n                \"already_settled\": False,\n            }\n"""
new = """        if not variances:\n            reconciled_session = await finalize_vehicle_inventory_reconciliation(\n                db,\n                company_id=company_id,\n                work_session_id=work_session.id,\n                vehicle_location_id=vehicle_location_id,\n                settled_by=driver_id,\n            )\n            reconciled_at = reconciled_session.inventory_reconciled_at\n            if reconciled_at is None:\n                raise RuntimeError(\"Inventory reconciliation finalized without inventory_reconciled_at.\")\n            db.add(SystemAuditLog(\n                company_id=company_id,\n                admin_id=driver_id,\n                target_id=f\"WorkSession_{work_session.id}\",\n                action_type=\"VEHICLE_INVENTORY_RECONCILED\",\n                old_value=\"inventory_reconciled_at=null\",\n                new_value=json.dumps({\n                    \"inventory_reconciled\": True,\n                    \"inventory_reconciled_at\": reconciled_at.isoformat(),\n                    \"inventory_reconciled_by\": driver_id,\n                    \"financial_is_settled\": False,\n                    \"product_count\": len(expected_map),\n                    \"vehicle_location_id\": vehicle_location_id,\n                }, ensure_ascii=False),\n            ))\n            await db.commit()\n            return {\n                \"message\": \"التسوية المخزنية مطابقة 100% وتم تثبيت عهدة نهاية الجلسة؛ التسوية المالية ما زالت بانتظار المحاسب.\",\n                \"requires_audit\": False,\n                \"already_reconciled\": False,\n            }\n"""
if r.count(old) != 1:
    raise SystemExit('PATCH_ABORT: exact-match settlement block not unique')
r = r.replace(old, new, 1)
if 'finalize_vehicle_reconciliation_settlement' in r:
    raise SystemExit('PATCH_ABORT: old finalize helper name still present in reconciliation.py')
if 'old_value="is_settled=false"' in r or '"is_settled": True' in r:
    raise SystemExit('PATCH_ABORT: financial settlement audit semantics still present')
texts[RECON] = r

# Static validation before writing.
for path, text in texts.items():
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f'PATCH_ABORT: AST failed for {path}: {exc}')

# Cross-file semantic guards.
if 'inventory_reconciled_at' not in texts[MODELS] or 'inventory_reconciled_by' not in texts[MODELS]:
    raise SystemExit('PATCH_ABORT: model reconciliation markers missing after patch')
if 'work_session.is_settled = True' in texts[SERVICES]:
    raise SystemExit('PATCH_ABORT: services still financially settles WorkSession')
if 'async def finalize_vehicle_inventory_reconciliation(' not in texts[SERVICES]:
    raise SystemExit('PATCH_ABORT: renamed inventory finalizer missing')
if 'if work_session.inventory_reconciled_at is not None:' not in texts[SERVICES]:
    raise SystemExit('PATCH_ABORT: VEHICLE_RECON reopen guard missing')
if 'already_settled' in texts[RECON]:
    raise SystemExit('PATCH_ABORT: stale already_settled reconciliation API wording remains')

BACKUP.mkdir(parents=True, exist_ok=True)
for path in (MODELS, SERVICES, RECON):
    shutil.copy2(path, BACKUP / path.name)
for path, text in texts.items():
    path.write_text(text, encoding='utf-8', newline='\n')

print('INVENTORY_FINANCIAL_SETTLEMENT_SEPARATION_OK')
print('MODEL_OK: WorkSession has inventory_reconciled_at/by distinct from financial is_settled')
print('DB_GUARD_OK: financial is_settled requires completed inventory reconciliation')
print('SERVICE_OK: inventory finalizer freezes Ending Snapshot only; never sets is_settled=True')
print('RECON_OK: driver reconciliation stamps inventory state and audit only')
print('WORKFLOW_OK: driver remains blocked from next day until accountant completes financial settlement')
print('FILES_CHANGED: wa_backend/models.py + wa_backend/services.py + wa_backend/api/reconciliation.py')
