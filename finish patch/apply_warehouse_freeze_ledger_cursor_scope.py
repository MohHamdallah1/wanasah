from __future__ import annotations

import ast
import py_compile
from pathlib import Path

TARGET = Path("wa_backend/api/warehouse.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f"ERROR: missing {TARGET}")

    original = TARGET.read_bytes()
    text = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")

    if "def _ledger_cursor_scope_hash(" in text:
        raise RuntimeError("Ledger cursor scope hardening appears already applied.")

    old_helpers = '''def _encode_ledger_cursor(created_at: datetime, movement_id: int) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "warehouse-ledger",
            "created_at": created_at.isoformat(),
            "id": int(movement_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_ledger_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "warehouse-ledger"
        ):
            raise ValueError

        movement_id = payload.get("id")
        if type(movement_id) is not int or movement_id <= 0:
            raise ValueError

        created_at = datetime.fromisoformat(str(payload.get("created_at")))
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

        return created_at, movement_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor سجل الحركات غير صالح أو تالف.",
        ) from exc
'''

    new_helpers = '''def _ledger_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_ledger_cursor(
    created_at: datetime,
    movement_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 2,
            "kind": "warehouse-ledger",
            "scope": _ledger_cursor_scope_hash(scope),
            "created_at": created_at.isoformat(),
            "id": int(movement_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_ledger_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> tuple[datetime, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 2
            or payload.get("kind") != "warehouse-ledger"
            or payload.get("scope")
            != _ledger_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        movement_id = payload.get("id")
        if type(movement_id) is not int or movement_id <= 0:
            raise ValueError

        created_at = datetime.fromisoformat(str(payload.get("created_at")))
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

        return created_at, movement_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor سجل الحركات غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc
'''
    text = replace_once(text, old_helpers, new_helpers, "ledger cursor helpers")

    old_start = '''    company_id = current_admin.company_id

    try:
        if location_id is not None:
'''
    new_start = '''    company_id = current_admin.company_id

    clean_search = (search or "").strip().lower()
    clean_type = (reference_type or "").strip()
    clean_reference = (reference_id or "").strip()

    if clean_search and len(clean_search) < 2:
        raise HTTPException(
            status_code=400,
            detail="البحث في السجل يتطلب حرفين على الأقل.",
        )

    ledger_scope = (
        f"ledger|{company_id}|{location_id or 0}|"
        f"{clean_search}|{clean_type}|{clean_reference}"
    )

    try:
        if location_id is not None:
'''
    # Limit this replacement to ledger function region only.
    fn_start = text.index("async def get_warehouse_ledger_cursor(")
    fn_end = text.index("\n\n# =================================================================================\n# 5.", fn_start)
    before, region, after = text[:fn_start], text[fn_start:fn_end], text[fn_end:]
    region = replace_once(region, old_start, new_start, "ledger scope setup")

    old_filters = '''        if reference_type:
            clean_type = reference_type.strip()
            if clean_type:
                stmt = stmt.filter(
                    InventoryMovement.reference_type == clean_type,
                )

        if reference_id:
            clean_reference = reference_id.strip()
            if clean_reference:
                stmt = stmt.filter(
                    InventoryMovement.reference_id == clean_reference
                )

        if search:
            clean_search = search.strip().lower()
            if len(clean_search) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="البحث في السجل يتطلب حرفين على الأقل.",
                )
            like_pattern = f"%{_escape_like(clean_search)}%"
            stmt = stmt.filter(
'''
    new_filters = '''        if clean_type:
            stmt = stmt.filter(
                InventoryMovement.reference_type == clean_type,
            )

        if clean_reference:
            stmt = stmt.filter(
                InventoryMovement.reference_id == clean_reference
            )

        if clean_search:
            like_pattern = f"%{_escape_like(clean_search)}%"
            stmt = stmt.filter(
'''
    region = replace_once(region, old_filters, new_filters, "ledger normalized filters")

    region = replace_once(
        region,
        "            cursor_created_at, cursor_id = _decode_ledger_cursor(cursor)\n",
        '''            cursor_created_at, cursor_id = _decode_ledger_cursor(
                cursor,
                expected_scope=ledger_scope,
            )
''',
        "ledger decode scope",
    )

    region = replace_once(
        region,
        '''            next_cursor = _encode_ledger_cursor(
                last_movement.created_at,
                last_movement.id,
            )
''',
        '''            next_cursor = _encode_ledger_cursor(
                last_movement.created_at,
                last_movement.id,
                scope=ledger_scope,
            )
''',
        "ledger encode scope",
    )

    text = before + region + after
    text = text.replace(
        '''# Cursor API الجديد لسجل الحركات.
# يبقى /warehouse/ledger القديم مؤقتاً فقط حتى تحويل الواجهة في الخطوة التالية،
# ثم يُحذف قبل تجميد warehouse.py.
''',
        '''# Cursor API لسجل الحركات؛ الـCursor مربوط بالـTenant والفلاتر الحالية.
''',
        1,
    )

    ast.parse(text, filename=str(TARGET))

    required = (
        'payload.get("v") != 2',
        "_ledger_cursor_scope_hash(expected_scope)",
        'f"ledger|{company_id}|{location_id or 0}|"',
        "expected_scope=ledger_scope",
        "scope=ledger_scope",
        "InventoryMovement.company_id == company_id",
    )
    for token in required:
        if token not in text:
            raise RuntimeError(f"Missing hardened ledger invariant: {token}")

    tmp = TARGET.with_suffix(".py.freeze.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        py_compile.compile(str(tmp), doraise=True)
        tmp.replace(TARGET)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        TARGET.write_bytes(original)
        raise

    print("WAREHOUSE_LEDGER_CURSOR_SCOPE_HARDENING_OK")
    print("PY_COMPILE=OK")
    print("LEDGER_CURSOR_TENANT_SCOPE=BOUND")
    print("LEDGER_CURSOR_FILTER_SCOPE=BOUND")
    print("LEGACY_LEDGER_CURSOR_V1=REJECTED_BY_DESIGN")


if __name__ == "__main__":
    main()
