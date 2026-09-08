from __future__ import annotations

import ast
from pathlib import Path

TARGET = Path('wa_backend/api/reconciliation.py')
if not TARGET.exists():
    TARGET = Path('api/reconciliation.py')
if not TARGET.exists():
    raise SystemExit('PATCH_ABORT: reconciliation.py not found. Run from project root or wa_backend.')

text = TARGET.read_text(encoding='utf-8')

old = '''        if existing_recon is not None:\n            if existing_recon.status == "POSTED":\n                raise HTTPException(\n                    status_code=409,\n                    detail="VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ البيانات غير متسقة وتحتاج مراجعة.",\n                )\n            await db.rollback()\n            return {\n                "message": "يوجد VEHICLE_RECON مفتوح لهذه الجلسة؛ استخدم نفس جلسة المراجعة.",\n                "requires_audit": True,\n                "stocktake_reference": existing_recon.reference_number,\n                "stocktake_session_id": existing_recon.id,\n                "stocktake_status": existing_recon.status,\n            }\n'''

new = '''        if existing_recon is not None:\n            # SQLAlchemy expires ORM state on rollback. Capture primitive values first so\n            # the idempotent replay never triggers implicit async I/O after rollback.\n            existing_status = str(existing_recon.status)\n            existing_reference = str(existing_recon.reference_number)\n            existing_id = int(existing_recon.id)\n\n            if existing_status == "POSTED":\n                raise HTTPException(\n                    status_code=409,\n                    detail="VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ البيانات غير متسقة وتحتاج مراجعة.",\n                )\n            await db.rollback()\n            return {\n                "message": "يوجد VEHICLE_RECON مفتوح لهذه الجلسة؛ استخدم نفس جلسة المراجعة.",\n                "requires_audit": True,\n                "stocktake_reference": existing_reference,\n                "stocktake_session_id": existing_id,\n                "stocktake_status": existing_status,\n            }\n'''

if new in text:
    print('RECONCILIATION_EXISTING_RECON_REPLAY_ALREADY_OK')
    raise SystemExit(0)

count = text.count(old)
if count != 1:
    raise SystemExit(f'PATCH_ABORT: expected exact existing_recon replay block once, found {count}.')

patched = text.replace(old, new, 1)
ast.parse(patched)

# Guard against the exact MissingGreenlet pattern returning in this replay branch.
branch_start = patched.index('        if existing_recon is not None:')
branch_end = patched.index('        conflicting_lock =', branch_start)
branch = patched[branch_start:branch_end]
rollback_pos = branch.index('            await db.rollback()')
after_rollback = branch[rollback_pos:]
for forbidden in (
    'existing_recon.reference_number',
    'existing_recon.id',
    'existing_recon.status',
):
    if forbidden in after_rollback:
        raise SystemExit(f'PATCH_ABORT: ORM access remains after rollback: {forbidden}')

TARGET.write_text(patched, encoding='utf-8', newline='\n')
print('RECONCILIATION_EXISTING_RECON_REPLAY_OK')
print('FIX_OK: capture id/reference/status before rollback; no implicit ORM I/O after rollback')
print(f'FILE_CHANGED: {TARGET.as_posix()} only')
