from __future__ import annotations

import ast
import os
import py_compile
from pathlib import Path

TARGET = Path.cwd() / "wa_backend" / "models.py"

START = """        CheckConstraint(
            "((movement_kind = 'PHYSICAL' AND (source_location_id IS NULL OR destination_location_id IS NULL OR source_location_id <> destination_location_id)) "
            "OR (movement_kind = 'RESERVATION' AND source_location_id IS NOT NULL AND destination_location_id = source_location_id AND destination_stock_status = source_stock_status) "
            "OR (movement_kind = 'STATUS_CHANGE' AND source_location_id IS NOT NULL AND destination_location_id = source_location_id AND destination_stock_status <> source_stock_status))",
"""

END = """    id                       = Column(Integer, primary_key=True)"""

REPLACEMENT = """        CheckConstraint(
            "((movement_kind = 'PHYSICAL' AND (source_location_id IS NULL OR destination_location_id IS NULL OR source_location_id <> destination_location_id)) "
            "OR (movement_kind = 'RESERVATION' AND source_location_id IS NOT NULL AND destination_location_id = source_location_id AND destination_stock_status = source_stock_status) "
            "OR (movement_kind = 'STATUS_CHANGE' AND source_location_id IS NOT NULL AND destination_location_id = source_location_id AND destination_stock_status <> source_stock_status))",
            name='chk_inv_movement_shape'
        ),
        CheckConstraint(
            "movement_kind <> 'PHYSICAL' OR source_location_id IS NULL OR destination_location_id IS NULL "
            "OR source_stock_status = destination_stock_status",
            name='chk_inv_movement_physical_preserves_status'
        ),
        CheckConstraint(
            'stocktake_count_attempt_id IS NULL OR stocktake_session_id IS NOT NULL',
            name='chk_inv_movement_attempt_requires_stocktake'
        ),
        CheckConstraint('quantity > 0', name='chk_inv_movement_qty_positive'),
        CheckConstraint("length(trim(reference_type)) > 0", name='chk_inv_movement_reference_type'),
        CheckConstraint("length(trim(reference_id)) > 0", name='chk_inv_movement_reference_id'),
        CheckConstraint("length(trim(idempotency_key)) > 0", name='chk_inv_movement_idempotency_key'),
        Index('ix_inv_movement_locations', 'company_id', 'source_location_id', 'destination_location_id'),
        Index('ix_inv_movement_item_created', 'company_id', 'product_variant_id', 'batch_id', 'created_at'),
        Index('ix_inv_movement_stocktake_attempt', 'company_id', 'stocktake_count_attempt_id'),
        # Keyset pagination / exact-reference paths for the append-only ledger.
        Index('ix_inv_movement_company_created_id', 'company_id', 'created_at', 'id'),
        Index('ix_inv_movement_company_source_created_id', 'company_id', 'source_location_id', 'created_at', 'id'),
        Index('ix_inv_movement_company_destination_created_id', 'company_id', 'destination_location_id', 'created_at', 'id'),
        Index('ix_inv_movement_company_reference', 'company_id', 'reference_id'),
    )
"""

REQUIRED_ONCE = [
    "chk_inv_movement_shape",
    "chk_inv_movement_physical_preserves_status",
    "chk_inv_movement_attempt_requires_stocktake",
    "chk_inv_movement_qty_positive",
    "chk_inv_movement_reference_type",
    "chk_inv_movement_reference_id",
    "chk_inv_movement_idempotency_key",
    "ix_inv_movement_locations",
    "ix_inv_movement_item_created",
    "ix_inv_movement_stocktake_attempt",
    "ix_inv_movement_company_created_id",
    "ix_inv_movement_company_source_created_id",
    "ix_inv_movement_company_destination_created_id",
    "ix_inv_movement_company_reference",
    "chk_work_session_settlement_requires_end",
    "uq_vehicle_recon_work_session",
    "chk_stocktake_work_session_scope",
    "class OperationIdempotency(Base):",
]

CORRUPTION_MARKERS = [
    "name='chk_inv_movem        # Keyset pagination",
    "Index('ix_inv    )",
]

def normalize(data: bytes) -> str:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")

def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f"ERROR: missing {TARGET}")

    original = TARGET.read_bytes()
    text = normalize(original)

    # If already healthy, refuse to touch it.
    try:
        ast.parse(text, filename=str(TARGET))
        healthy_syntax = True
    except SyntaxError:
        healthy_syntax = False

    if healthy_syntax and all(text.count(token) == 1 for token in REQUIRED_ONCE):
        raise SystemExit(
            "REFUSED: models.py already appears healthy; no repair was applied."
        )

    if not any(marker in text for marker in CORRUPTION_MARKERS):
        raise RuntimeError(
            "REFUSED: expected Cursor corruption signature was not found. "
            "This script will not guess or rewrite an unknown models.py state."
        )

    start = text.find(START)
    if start < 0:
        raise RuntimeError("Repair start anchor not found.")

    end = text.find(END, start)
    if end < 0:
        raise RuntimeError("Repair end anchor not found.")

    if text.find(START, start + 1) != -1:
        raise RuntimeError("Repair start anchor is not unique.")

    repaired = text[:start] + REPLACEMENT + text[end:]

    # Syntax validation before writing.
    ast.parse(repaired, filename=str(TARGET))

    for token in REQUIRED_ONCE:
        count = repaired.count(token)
        if count != 1:
            raise RuntimeError(
                f"Post-repair invariant failed: {token!r} count={count}"
            )

    for marker in CORRUPTION_MARKERS:
        if marker in repaired:
            raise RuntimeError(
                f"Post-repair corruption marker still present: {marker!r}"
            )

    tmp = TARGET.with_suffix(".py.models-repair.tmp")
    tmp.write_text(repaired, encoding="utf-8", newline="\n")

    try:
        py_compile.compile(str(tmp), doraise=True)
        os.replace(tmp, TARGET)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            TARGET.write_bytes(original)
        raise

    print("MODELS_CURSOR_CORRUPTION_REPAIRED_OK")
    print("PY_COMPILE=OK")
    print("INVENTORY_MOVEMENT_CONSTRAINTS=RESTORED")
    print("CURSOR_INDEXES=EXACTLY_ONCE")
    print("STAGE5_LIFECYCLE_MARKERS=PRESENT")
    print("OPERATION_IDEMPOTENCY=PRESENT")

if __name__ == "__main__":
    main()
