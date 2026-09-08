from __future__ import annotations

import ast
import os
import py_compile
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

FILES = {
    "models": BACKEND / "models.py",
    "schemas": BACKEND / "schemas.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
}

def norm(data: bytes) -> str:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)

def patch_models(text: str) -> str:
    if "ix_inv_movement_company_created_id" in text:
        raise RuntimeError("models.py: Cursor indexes موجودة مسبقاً.")
    return replace_once(text, "        Index('ix_inv_movement_locations', 'company_id', 'source_location_id', 'destination_location_id'),\n        Index('ix_inv_movement_item_created', 'company_id', 'product_variant_id', 'batch_id', 'created_at'),\n        Index('ix_inv_movement_stocktake_attempt', 'company_id', 'stocktake_count_attempt_id'),\n", "        Index('ix_inv_movement_locations', 'company_id', 'source_location_id', 'destination_location_id'),\n        Index('ix_inv_movement_item_created', 'company_id', 'product_variant_id', 'batch_id', 'created_at'),\n        Index('ix_inv_movement_stocktake_attempt', 'company_id', 'stocktake_count_attempt_id'),\n        # Keyset pagination / exact-reference paths for the append-only ledger.\n        Index('ix_inv_movement_company_created_id', 'company_id', 'created_at', 'id'),\n        Index('ix_inv_movement_company_source_created_id', 'company_id', 'source_location_id', 'created_at', 'id'),\n        Index('ix_inv_movement_company_destination_created_id', 'company_id', 'destination_location_id', 'created_at', 'id'),\n        Index('ix_inv_movement_company_reference', 'company_id', 'reference_id'),\n", "models cursor indexes")

def patch_schemas(text: str) -> str:
    if "    blocked_packs: int\n" not in text:
        text = replace_once(
            text,
            "    available_packs: int\n    reserved_packs: int\n    total_packs: int\n",
            "    available_packs: int\n    reserved_packs: int\n    blocked_packs: int\n    total_packs: int\n",
            "schemas blocked_packs",
        )
    if "class WarehouseLedgerCursorPage(BaseModel):" in text:
        raise RuntimeError("schemas.py: WarehouseLedgerCursorPage موجود مسبقاً.")
    return replace_once(text, 'class WarehouseStatusResponse(BaseModel):\n    status: str\n', 'class WarehouseLedgerCursorPage(BaseModel):\n    items: List[WarehouseLedgerItem]\n    next_cursor: Optional[str] = None\n    has_more: bool\n    total: Optional[int] = None\n    available_types: List[str] = Field(default_factory=list)\n\n\nclass WarehouseStatusResponse(BaseModel):\n    status: str\n', "schemas ledger page")

def patch_warehouse(text: str) -> str:
    if '@router.get(\n    "/warehouse/ledger/cursor"' in text:
        raise RuntimeError("warehouse.py: cursor endpoint موجود مسبقاً.")
    text = replace_once(
        text,
        "from fastapi import APIRouter, Depends, HTTPException, Body\n",
        "from fastapi import APIRouter, Depends, HTTPException, Body, Query\n",
        "warehouse Query import",
    )
    if "import base64\n" not in text:
        text = replace_once(text, "import json\n", "import json\nimport base64\n", "warehouse base64 import")
    text = replace_once(
        text,
        "WarehouseInventoryItem, WarehouseLedgerItem, WarehouseStatusResponse, SimpleProductVariantItem,\n",
        "WarehouseInventoryItem, WarehouseLedgerItem, WarehouseLedgerCursorPage, WarehouseStatusResponse, SimpleProductVariantItem,\n",
        "warehouse schema import",
    )
    text = replace_once(text, '    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()\n\n\n', '    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()\n\n\ndef _encode_ledger_cursor(created_at: datetime, movement_id: int) -> str:\n    raw = json.dumps(\n        {\n            "v": 1,\n            "kind": "warehouse-ledger",\n            "created_at": created_at.isoformat(),\n            "id": int(movement_id),\n        },\n        sort_keys=True,\n        separators=(",", ":"),\n    ).encode("utf-8")\n    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")\n\n\ndef _decode_ledger_cursor(cursor: str) -> tuple[datetime, int]:\n    try:\n        padding = "=" * (-len(cursor) % 4)\n        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))\n        payload = json.loads(raw.decode("utf-8"))\n\n        if (\n            not isinstance(payload, dict)\n            or payload.get("v") != 1\n            or payload.get("kind") != "warehouse-ledger"\n        ):\n            raise ValueError\n\n        movement_id = payload.get("id")\n        if type(movement_id) is not int or movement_id <= 0:\n            raise ValueError\n\n        created_at = datetime.fromisoformat(str(payload.get("created_at")))\n        if created_at.tzinfo is not None:\n            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)\n\n        return created_at, movement_id\n    except Exception as exc:\n        raise HTTPException(\n            status_code=400,\n            detail="Cursor سجل الحركات غير صالح أو تالف.",\n        ) from exc\n\n\ndef _escape_like(value: str) -> str:\n    return (\n        value\n        .replace("\\\\", "\\\\\\\\")\n        .replace("%", "\\\\%")\n        .replace("_", "\\\\_")\n    )\n\n\n', "warehouse cursor helpers")
    return replace_once(text, '# =================================================================================\n# 5. جلب حالة قفل المستودع\n# =================================================================================\n', '# Cursor API الجديد لسجل الحركات.\n# يبقى /warehouse/ledger القديم مؤقتاً فقط حتى تحويل الواجهة في الخطوة التالية،\n# ثم يُحذف قبل تجميد warehouse.py.\n@router.get(\n    "/warehouse/ledger/cursor",\n    response_model=WarehouseLedgerCursorPage,\n    status_code=200,\n)\nasync def get_warehouse_ledger_cursor(\n    location_id: Optional[int] = None,\n    cursor: Optional[str] = Query(default=None, max_length=512),\n    limit: int = Query(default=50, ge=1, le=200),\n    search: Optional[str] = Query(default=None, min_length=2, max_length=100),\n    reference_type: Optional[str] = Query(default=None, max_length=50),\n    reference_id: Optional[str] = Query(default=None, max_length=100),\n    db: AsyncSession = Depends(get_db),\n    current_admin: Driver = Depends(get_current_admin),\n):\n    company_id = current_admin.company_id\n\n    try:\n        if location_id is not None:\n            stmt_location = select(InventoryLocation.id).filter_by(\n                id=location_id,\n                company_id=company_id,\n                location_type=\'WAREHOUSE\',\n            )\n            if (await db.execute(stmt_location)).scalar_one_or_none() is None:\n                raise HTTPException(\n                    status_code=404,\n                    detail="المستودع غير موجود أو لا يتبع شركتك.",\n                )\n\n        stmt = select(\n            InventoryMovement,\n            ProductVariant.variant_name,\n            ProductVariant.packs_per_carton,\n            Driver.full_name,\n        ).join(\n            ProductVariant,\n            and_(\n                ProductVariant.company_id == InventoryMovement.company_id,\n                ProductVariant.id == InventoryMovement.product_variant_id,\n            ),\n        ).join(\n            Driver,\n            and_(\n                Driver.company_id == InventoryMovement.company_id,\n                Driver.id == InventoryMovement.performed_by,\n            ),\n        ).filter(\n            InventoryMovement.company_id == company_id,\n        )\n\n        if location_id is not None:\n            stmt = stmt.filter(\n                or_(\n                    InventoryMovement.source_location_id == location_id,\n                    InventoryMovement.destination_location_id == location_id,\n                )\n            )\n\n        if reference_type:\n            clean_type = reference_type.strip()\n            if clean_type:\n                stmt = stmt.filter(\n                    InventoryMovement.reference_type == clean_type,\n                )\n\n        if reference_id:\n            normalized_reference = reference_id.strip().lower()\n            if normalized_reference:\n                stmt = stmt.filter(\n                    func.lower(func.trim(InventoryMovement.reference_id))\n                    == normalized_reference\n                )\n\n        if search:\n            clean_search = search.strip().lower()\n            if len(clean_search) < 2:\n                raise HTTPException(\n                    status_code=400,\n                    detail="البحث في السجل يتطلب حرفين على الأقل.",\n                )\n            like_pattern = f"%{_escape_like(clean_search)}%"\n            stmt = stmt.filter(\n                or_(\n                    func.lower(ProductVariant.variant_name).like(\n                        like_pattern, escape="\\\\"\n                    ),\n                    func.lower(InventoryMovement.reference_id).like(\n                        like_pattern, escape="\\\\"\n                    ),\n                    func.lower(Driver.full_name).like(\n                        like_pattern, escape="\\\\"\n                    ),\n                    func.lower(\n                        func.coalesce(InventoryMovement.notes, "")\n                    ).like(\n                        like_pattern, escape="\\\\"\n                    ),\n                )\n            )\n\n        total = None\n        if cursor is None:\n            count_stmt = select(func.count()).select_from(\n                stmt.with_only_columns(\n                    InventoryMovement.id,\n                    maintain_column_froms=True,\n                ).order_by(None).subquery()\n            )\n            total = int((await db.execute(count_stmt)).scalar_one())\n\n        if cursor is not None:\n            cursor_created_at, cursor_id = _decode_ledger_cursor(cursor)\n            stmt = stmt.filter(\n                or_(\n                    InventoryMovement.created_at < cursor_created_at,\n                    and_(\n                        InventoryMovement.created_at == cursor_created_at,\n                        InventoryMovement.id < cursor_id,\n                    ),\n                )\n            )\n\n        stmt = stmt.order_by(\n            InventoryMovement.created_at.desc(),\n            InventoryMovement.id.desc(),\n        ).limit(limit + 1)\n\n        rows = (await db.execute(stmt)).all()\n        has_more = len(rows) > limit\n        rows = rows[:limit]\n\n        type_stmt = select(\n            InventoryMovement.reference_type\n        ).filter(\n            InventoryMovement.company_id == company_id,\n        )\n\n        if location_id is not None:\n            type_stmt = type_stmt.filter(\n                or_(\n                    InventoryMovement.source_location_id == location_id,\n                    InventoryMovement.destination_location_id == location_id,\n                )\n            )\n\n        available_types = list(\n            (\n                await db.execute(\n                    type_stmt.distinct().order_by(\n                        InventoryMovement.reference_type.asc()\n                    )\n                )\n            ).scalars().all()\n        )\n\n        if not rows:\n            return {\n                "items": [],\n                "next_cursor": None,\n                "has_more": False,\n                "total": total,\n                "available_types": available_types,\n            }\n\n        movement_ids = [row[0].id for row in rows]\n\n        stmt_impacts = select(\n            InventoryMovementImpact,\n            InventoryBalance,\n        ).join(\n            InventoryBalance,\n            and_(\n                InventoryBalance.company_id\n                == InventoryMovementImpact.company_id,\n                InventoryBalance.id\n                == InventoryMovementImpact.inventory_balance_id,\n            ),\n        ).filter(\n            InventoryMovementImpact.company_id == company_id,\n            InventoryMovementImpact.movement_id.in_(movement_ids),\n            InventoryBalance.company_id == company_id,\n        )\n\n        if location_id is not None:\n            stmt_impacts = stmt_impacts.filter(\n                InventoryBalance.location_id == location_id\n            )\n\n        impacts_by_movement: dict[\n            int,\n            list[tuple[InventoryMovementImpact, InventoryBalance]],\n        ] = {}\n\n        for impact, balance in (await db.execute(stmt_impacts)).all():\n            impacts_by_movement.setdefault(\n                impact.movement_id,\n                [],\n            ).append((impact, balance))\n\n        result = []\n\n        for movement, product_name, packs_per_carton, admin_name in rows:\n            candidates = impacts_by_movement.get(movement.id, [])\n            chosen = None\n\n            def _find_impact(target_location_id, target_status):\n                if target_location_id is None or target_status is None:\n                    return None\n                for impact_row, balance_row in candidates:\n                    if (\n                        balance_row.location_id == target_location_id\n                        and balance_row.stock_status == target_status\n                    ):\n                        return impact_row, balance_row\n                return None\n\n            if movement.movement_kind == \'STATUS_CHANGE\':\n                chosen = _find_impact(\n                    movement.source_location_id,\n                    \'AVAILABLE\',\n                )\n            elif location_id is not None:\n                if movement.source_location_id == location_id:\n                    chosen = _find_impact(\n                        location_id,\n                        movement.source_stock_status,\n                    )\n                if (\n                    chosen is None\n                    and movement.destination_location_id == location_id\n                ):\n                    chosen = _find_impact(\n                        location_id,\n                        movement.destination_stock_status,\n                    )\n            else:\n                chosen = _find_impact(\n                    movement.source_location_id,\n                    movement.source_stock_status,\n                )\n                if chosen is None:\n                    chosen = _find_impact(\n                        movement.destination_location_id,\n                        movement.destination_stock_status,\n                    )\n\n            balance_before = None\n            balance_after = None\n            quantity_packs = None\n\n            if chosen is not None:\n                impact, _balance = chosen\n\n                if movement.movement_kind == \'RESERVATION\':\n                    balance_before = (\n                        int(impact.on_hand_before)\n                        - int(impact.reserved_before)\n                    )\n                    balance_after = (\n                        int(impact.on_hand_after)\n                        - int(impact.reserved_after)\n                    )\n                else:\n                    balance_before = int(impact.on_hand_before)\n                    balance_after = int(impact.on_hand_after)\n\n                quantity_packs = balance_after - balance_before\n\n            if quantity_packs is None:\n                quantity = int(movement.quantity)\n\n                if movement.movement_kind == \'RESERVATION\':\n                    quantity_packs = (\n                        -quantity\n                        if movement.reservation_action == \'RESERVE\'\n                        else quantity\n                    )\n                elif movement.movement_kind == \'STATUS_CHANGE\':\n                    quantity_packs = (\n                        -quantity\n                        if movement.source_stock_status == \'AVAILABLE\'\n                        else quantity\n                    )\n                elif location_id is not None:\n                    quantity_packs = (\n                        -quantity\n                        if movement.source_location_id == location_id\n                        else quantity\n                    )\n                else:\n                    quantity_packs = (\n                        -quantity\n                        if movement.source_location_id is not None\n                        else quantity\n                    )\n\n            created_at = movement.created_at\n            if created_at is not None:\n                if created_at.tzinfo is None:\n                    response_created_at = created_at.replace(\n                        tzinfo=timezone.utc\n                    )\n                else:\n                    response_created_at = created_at.astimezone(\n                        timezone.utc\n                    )\n            else:\n                response_created_at = None\n\n            result.append({\n                "id": movement.id,\n                "product_name": product_name,\n                "packs_per_carton": int(packs_per_carton or 1),\n                "type": movement.reference_type,\n                "quantity_packs": int(quantity_packs),\n                "balance_before": balance_before,\n                "balance_after": balance_after,\n                "admin_name": admin_name or "غير معروف",\n                "reference": movement.reference_id,\n                "notes": movement.notes,\n                "date": (\n                    response_created_at.isoformat()\n                    if response_created_at\n                    else ""\n                ),\n            })\n\n        next_cursor = None\n        if has_more and rows:\n            last_movement = rows[-1][0]\n            if last_movement.created_at is None:\n                raise RuntimeError(\n                    "Ledger invariant violated: movement without created_at."\n                )\n            next_cursor = _encode_ledger_cursor(\n                last_movement.created_at,\n                last_movement.id,\n            )\n\n        return {\n            "items": result,\n            "next_cursor": next_cursor,\n            "has_more": has_more,\n            "total": total,\n            "available_types": available_types,\n        }\n\n    except HTTPException:\n        raise\n    except Exception as e:\n        logger.error(\n            f"خطأ في Cursor سجل المستودع: {str(e)}",\n            exc_info=True,\n        )\n        raise HTTPException(\n            status_code=500,\n            detail="حدث خطأ داخلي أثناء جلب صفحة سجل الحركات.",\n        )\n\n\n# =================================================================================\n# 5. جلب حالة قفل المستودع\n# =================================================================================\n', "warehouse cursor endpoint")

def validate(prepared):
    for token in [
        "ix_inv_movement_company_created_id",
        "ix_inv_movement_company_source_created_id",
        "ix_inv_movement_company_destination_created_id",
        "ix_inv_movement_company_reference",
    ]:
        if token not in prepared["models"]:
            raise RuntimeError(f"models missing {token}")
    for token in ["class WarehouseLedgerCursorPage(BaseModel):", "blocked_packs: int"]:
        if token not in prepared["schemas"]:
            raise RuntimeError(f"schemas missing {token}")
    for token in [
        '"/warehouse/ledger/cursor"',
        "def _decode_ledger_cursor(",
        "InventoryMovement.created_at < cursor_created_at",
        ".limit(limit + 1)",
    ]:
        if token not in prepared["warehouse"]:
            raise RuntimeError(f"warehouse missing {token}")

def main():
    for path in FILES.values():
        if not path.is_file():
            raise SystemExit(f"ERROR: missing {path}")

    originals = {name: path.read_bytes() for name, path in FILES.items()}
    prepared = {}

    for name, path in FILES.items():
        text = norm(originals[name])
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
        for name, path in FILES.items():
            tmp = path.with_suffix(path.suffix + ".cursor.tmp")
            tmp.write_text(prepared[name], encoding="utf-8", newline="\n")
            py_compile.compile(str(tmp), doraise=True)
            os.replace(tmp, path)
            written.append(name)
    except Exception:
        for name in written:
            FILES[name].write_bytes(originals[name])
        raise

    print("WAREHOUSE_LEDGER_CURSOR_BACKEND_OK")
    print("models.py: keyset indexes added")
    print("schemas.py: WarehouseLedgerCursorPage added")
    print("warehouse.py: /warehouse/ledger/cursor added")
    print("LEGACY_LEDGER_ENDPOINT=KEPT_TEMPORARILY_FOR_UI_MIGRATION")

if __name__ == "__main__":
    main()
