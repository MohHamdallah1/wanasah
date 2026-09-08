from pathlib import Path
import ast
import shutil
import sys


def abort(msg: str):
    print(f"PATCH_ABORT: {msg}")
    sys.exit(1)

root = Path.cwd()
driver_path = root / "wa_backend" / "api" / "driver.py"
if not driver_path.is_file():
    abort("لم أجد wa_backend/api/driver.py. شغّل الباتش من جذر المشروع.")

src = driver_path.read_text(encoding="utf-8")
original = src

# Guard: final hardening patch must already exist.
required = [
    'SessionInventorySnapshot.stock_status == "AVAILABLE"',
    'InventoryMovement.reference_type == "VISIT_REVERSAL"',
    'DispatchRoute.dispatch_date == company_local_date',
    'async def _validate_incoming_handshake_batches(',
]
missing = [token for token in required if token not in src]
if missing:
    abort("الملف لا يطابق نسخة التدقيق النهائية المطلوبة. المفقود: " + ", ".join(missing))

# 1) Remove only proven-unused imports.
src = src.replace(
    "from datetime import datetime, timezone, timedelta\n",
    "from datetime import datetime, timezone\n",
    1,
)
src = src.replace(
    "    SessionInventorySnapshot, InventoryDamageEvent,\n",
    "    SessionInventorySnapshot,\n",
    1,
)

# 2) Before a session exists, the UI preview's starting stock is the current physical AVAILABLE load.
# Once a session exists, immutable SessionInventorySnapshot is authoritative.
old = '''    starting_map = {}\n    issued_map = {}\n    if work_session_id is not None:\n'''
new = '''    # قبل بدء الجلسة لا توجد Snapshot بعد؛ للعرض التمهيدي فقط تكون البداية هي الرصيد الحالي.\n    # بعد بدء الجلسة تصبح SessionInventorySnapshot المصدر التاريخي الوحيد لبداية اليوم.\n    starting_map = dict(current_map) if work_session_id is None else {}\n    issued_map = {}\n    if work_session_id is not None:\n'''
if old in src:
    src = src.replace(old, new, 1)
elif new not in src:
    abort("لم أجد كتلة projection المتوقعة؛ لن أعدل ملفاً غير مطابق.")

# Parse before writing.
try:
    tree = ast.parse(src)
except SyntaxError as exc:
    abort(f"الناتج غير صالح نحوياً: {exc}")

# Static import-use check: no imported name should remain unused.
imports = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            local = alias.asname or alias.name.split('.')[0]
            imports.append((local, node.lineno))
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            local = alias.asname or alias.name
            imports.append((local, node.lineno))
used = {
    node.id for node in ast.walk(tree)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
}
unused = [(name, line) for name, line in imports if name not in used]
if unused:
    abort("بقيت imports غير مستخدمة: " + ", ".join(f"{name}@{line}" for name, line in unused))

# Safety invariants.
checks = {
    "pre-session projection": "starting_map = dict(current_map) if work_session_id is None else {}" in src,
    "session snapshot": 'SessionInventorySnapshot.stock_status == "AVAILABLE"' in src,
    "reversal netting": 'InventoryMovement.reference_type == "VISIT_REVERSAL"' in src,
    "no timedelta": "timedelta" not in src,
    "no InventoryDamageEvent import": "InventoryDamageEvent" not in src,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    abort("فشل تحقق داخلي: " + ", ".join(failed))

if src == original:
    print("DRIVER_PROJECTION_IMPORTS_ALREADY_OK")
    sys.exit(0)

backup = driver_path.with_suffix(driver_path.suffix + ".before_projection_import_cleanup")
shutil.copy2(driver_path, backup)
driver_path.write_text(src, encoding="utf-8", newline="\n")

print("DRIVER_PROJECTION_IMPORTS_OK")
print("PRE_SESSION_OK: starting=current AVAILABLE only before a WorkSession exists")
print("ACTIVE_SESSION_OK: starting remains immutable SessionInventorySnapshot[AVAILABLE]")
print("REVERSAL_OK: net VISIT issue still subtracts VISIT_REVERSAL")
print("IMPORTS_OK: all remaining imports are actually used")
print("REMOVED_UNUSED: timedelta + InventoryDamageEvent")
print("FILE_CHANGED: wa_backend/api/driver.py only")
