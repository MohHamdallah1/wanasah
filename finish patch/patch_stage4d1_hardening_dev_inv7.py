from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
from pathlib import Path

PATCH_ID = "STAGE4D1_HARDENING"
EXPECTED_HEAD = "c3dcb1df3a43c8ed3dc18b8a6cf8d662b59b034f"
MIGRATION_REL = Path(
    "wa_backend/alembic/versions/"
    "19c740dc40e8_stage4d_batch_disposition_and_portion_.py"
)


def abort(message: str) -> None:
    raise SystemExit(f"PATCH_ABORT: {message}")


def root_dir() -> Path:
    root = Path.cwd()
    if not (root / ".git").is_dir():
        abort("شغّل الباتش من جذر المشروع الذي يحتوي .git.")
    if not (root / "wa_backend" / "services.py").is_file():
        abort("wa_backend/services.py غير موجود؛ لست في جذر مشروع wanasah الصحيح.")
    return root


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        abort(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def validate_baseline(root: Path) -> None:
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    if head != EXPECTED_HEAD:
        abort(
            "HEAD لا يطابق dev inv 7 المدقق. "
            f"expected={EXPECTED_HEAD}, actual={head}"
        )

    if git(root, "diff", "--quiet", check=False).returncode != 0:
        abort("tracked working tree ليس نظيفاً. لا تطبق الباتش فوق تعديلات غير محفوظة.")
    if git(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        abort("staged index ليس نظيفاً. لا تطبق الباتش فوق تعديلات staged.")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        abort(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def require(text: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        abort(f"{label}: missing expected tokens: {missing}")


def patch_services(src: str) -> str:
    old_portion = '''# Conservative transitions derived from the approved Stage 4 capability matrix.
# DAMAGE creation remains on the already-approved return/damage workflows;
# this administrative reclassification path does not invent a second damage workflow.
_PORTION_STATUS_TRANSITIONS = {
    "AVAILABLE": frozenset({
        "QUARANTINED", "BLOCKED", "RECALLED", "DISPOSAL_PENDING",
    }),
    "QUARANTINED": frozenset({
        "AVAILABLE", "BLOCKED", "RECALLED", "DISPOSAL_PENDING",
    }),
    "BLOCKED": frozenset({"RECALLED", "DISPOSAL_PENDING"}),
    "RECALLED": frozenset({"QUARANTINED", "DISPOSAL_PENDING"}),
    "DAMAGED": frozenset({"DISPOSAL_PENDING"}),
    "DISPOSAL_PENDING": frozenset(),
}
'''
    new_portion = '''# Stage 4D.1: keep the generic same-location reclassification command narrow.
# Transfer-purpose operations (return / recall-return / quarantine transfer /
# disposal) are NOT represented here; Stage 4E owns those directional workflows.
# This command supports only local safety escalation plus explicit quarantine release.
_PORTION_STATUS_TRANSITIONS = {
    "AVAILABLE": frozenset({"QUARANTINED", "BLOCKED", "RECALLED"}),
    "QUARANTINED": frozenset({"AVAILABLE", "BLOCKED", "RECALLED"}),
    "BLOCKED": frozenset({"RECALLED"}),
    "RECALLED": frozenset(),
    "DAMAGED": frozenset(),
    "DISPOSAL_PENDING": frozenset(),
}
'''
    src = replace_once(
        src, old_portion, new_portion,
        "services conservative portion transition matrix",
    )

    old_batch = '''# QUARANTINED -> RELEASED is the explicit Test/Release path.
# RECALL can move only to a safer quarantine state, never directly to RELEASED.
_BATCH_DISPOSITION_TRANSITIONS = {
    "RELEASED": frozenset({"QUARANTINED", "BLOCKED", "RECALLED"}),
    "QUARANTINED": frozenset({"RELEASED", "BLOCKED", "RECALLED"}),
    "BLOCKED": frozenset({"RECALLED"}),
    "RECALLED": frozenset({"QUARANTINED"}),
}
'''
    new_batch = '''# Explicit Batch disposition commands only.
# QUARANTINED -> RELEASED is the documented Test/Release path.
# RECALLED is terminal here; return/quarantine/disposal of recalled physical stock
# belongs to Stage 4E transfer-purpose workflows, not a generic disposition patch.
_BATCH_DISPOSITION_TRANSITIONS = {
    "RELEASED": frozenset({"QUARANTINED", "BLOCKED", "RECALLED"}),
    "QUARANTINED": frozenset({"RELEASED", "BLOCKED", "RECALLED"}),
    "BLOCKED": frozenset({"RECALLED"}),
    "RECALLED": frozenset(),
}
'''
    src = replace_once(
        src, old_batch, new_batch,
        "services conservative batch disposition matrix",
    )
    return src


def patch_warehouse(src: str) -> str:
    old_batch_id = '''    if batch_id <= 0:
        raise HTTPException(status_code=422, detail="batch_id يجب أن يكون موجباً.")
'''
    new_batch_id = '''    if batch_id <= 0:
        raise HTTPException(
            status_code=422,
            detail=inventory_business_error(
                "BATCH_ID_INVALID",
                "batch_id يجب أن يكون موجباً.",
                context={"batch_id": batch_id},
            ),
        )
'''
    src = replace_once(
        src, old_batch_id, new_batch_id,
        "warehouse batch_id stable envelope",
    )

    old_batch_errors = '''    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير disposition للدفعة", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء تغيير حالة الدفعة؛ أعد المحاولة.",
        ) from exc
'''
    new_batch_errors = '''    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "BATCH_DISPOSITION_REJECTED",
                str(exc),
                context={"batch_id": batch_id},
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير disposition للدفعة", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "BATCH_DISPOSITION_CONFLICT",
                "حدث تعارض متزامن أثناء تغيير حالة الدفعة؛ أعد المحاولة.",
                context={"batch_id": batch_id},
            ),
        ) from exc
'''
    src = replace_once(
        src, old_batch_errors, new_batch_errors,
        "warehouse batch disposition stable errors",
    )

    old_product_not_found = '''        if base_uom_id is None:
            raise HTTPException(
                status_code=404,
                detail="الصنف غير موجود أو لا يتبع الشركة.",
            )
'''
    new_product_not_found = '''        if base_uom_id is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "PRODUCT_NOT_FOUND",
                    "الصنف غير موجود أو لا يتبع الشركة.",
                    context={
                        "product_variant_id": int(payload.product_variant_id),
                    },
                ),
            )
'''
    src = replace_once(
        src, old_product_not_found, new_product_not_found,
        "warehouse status-change product not found envelope",
    )

    old_status_errors = '''    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير Bucket المخزون", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء تغيير حالة الرصيد؛ أعد المحاولة.",
        ) from exc
'''
    new_status_errors = '''    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INVENTORY_STATUS_CHANGE_REJECTED",
                str(exc),
                context={
                    "location_id": int(payload.location_id),
                    "product_variant_id": int(payload.product_variant_id),
                    "batch_id": int(payload.batch_id),
                },
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير Bucket المخزون", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INVENTORY_STATUS_CHANGE_CONFLICT",
                "حدث تعارض متزامن أثناء تغيير حالة الرصيد؛ أعد المحاولة.",
                context={
                    "location_id": int(payload.location_id),
                    "product_variant_id": int(payload.product_variant_id),
                    "batch_id": int(payload.batch_id),
                },
            ),
        ) from exc
'''
    src = replace_once(
        src, old_status_errors, new_status_errors,
        "warehouse status-change stable errors",
    )
    return src


def patch_reconciliation(src: str) -> str:
    src = replace_once(
        src,
        "from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator\n",
        "from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator\n"
        "from decimal import Decimal\n",
        "reconciliation Decimal import",
    )
    src = replace_once(
        src,
        "from api.dependencies import get_current_driver\n",
        "from api.dependencies import get_current_driver\n"
        "from schemas import NonNegativeQuantity\n"
        "from quantity import QUANTITY_MAX, QuantityError, validate_variant_quantity\n",
        "reconciliation quantity imports",
    )
    src = replace_once(
        src,
        '    actual_quantity: StrictInt = Field(ge=0, le=_DB_INT_MAX)\n',
        '    actual_quantity: NonNegativeQuantity\n',
        "reconciliation Decimal request contract",
    )

    old_variant_validation = '''        submitted_ids = sorted({item.product_variant_id for item in payload.counts})
        if submitted_ids:
            valid_ids = set((
                await db.execute(
                    select(ProductVariant.id).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(submitted_ids),
                    )
                )
            ).scalars().all())
            if valid_ids != set(submitted_ids):
                raise HTTPException(status_code=422, detail="أحد الأصناف المعدودة غير موجود أو لا يتبع شركتك.")
'''
    new_variant_validation = '''        submitted_ids = sorted({item.product_variant_id for item in payload.counts})
        variant_rows = []
        if submitted_ids:
            variant_rows = (
                await db.execute(
                    select(
                        ProductVariant.id,
                        ProductVariant.quantity_scale,
                        ProductVariant.quantity_step,
                    ).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(submitted_ids),
                    )
                )
            ).all()

        variant_rules = {
            int(row.id): (int(row.quantity_scale), row.quantity_step)
            for row in variant_rows
        }
        if set(variant_rules) != set(submitted_ids):
            raise HTTPException(
                status_code=422,
                detail="أحد الأصناف المعدودة غير موجود أو لا يتبع شركتك.",
            )

        try:
            actual_map = {
                int(item.product_variant_id): validate_variant_quantity(
                    item.actual_quantity,
                    quantity_scale=variant_rules[int(item.product_variant_id)][0],
                    quantity_step=variant_rules[int(item.product_variant_id)][1],
                    field_name="actual_quantity",
                    allow_zero=True,
                )
                for item in payload.counts
            }
        except QuantityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
'''
    src = replace_once(
        src, old_variant_validation, new_variant_validation,
        "reconciliation variant scale/step validation",
    )

    old_aggregate = '''        expected_map = {}
        reserved_total = 0
        for balance in balance_rows:
            reserved_total += int(balance.reserved_quantity or 0)
            if balance.on_hand_quantity <= 0:
                continue
            product_variant_id = int(balance.product_variant_id)
            next_total = expected_map.get(product_variant_id, 0) + int(balance.on_hand_quantity or 0)
            if next_total > _DB_INT_MAX:
                raise HTTPException(status_code=409, detail="إجمالي أحد أصناف السيارة يتجاوز سعة INTEGER.")
            expected_map[product_variant_id] = next_total

        if reserved_total != 0:
            raise HTTPException(
                status_code=409,
                detail="يوجد مخزون محجوز على السيارة بعد إنهاء الجلسة؛ يجب تحرير الحجز قبل التسوية.",
            )

        actual_map = {item.product_variant_id: item.actual_quantity for item in payload.counts}
'''
    new_aggregate = '''        expected_map: dict[int, Decimal] = {}
        reserved_total = Decimal("0")
        for balance in balance_rows:
            reserved_total += Decimal(balance.reserved_quantity or 0)
            if Decimal(balance.on_hand_quantity or 0) <= 0:
                continue
            product_variant_id = int(balance.product_variant_id)
            next_total = (
                expected_map.get(product_variant_id, Decimal("0"))
                + Decimal(balance.on_hand_quantity or 0)
            )
            if next_total > QUANTITY_MAX:
                raise HTTPException(
                    status_code=409,
                    detail="إجمالي أحد أصناف السيارة يتجاوز سعة NUMERIC(20,6).",
                )
            expected_map[product_variant_id] = next_total

        if reserved_total != Decimal("0"):
            raise HTTPException(
                status_code=409,
                detail="يوجد مخزون محجوز على السيارة بعد إنهاء الجلسة؛ يجب تحرير الحجز قبل التسوية.",
            )

'''
    src = replace_once(
        src, old_aggregate, new_aggregate,
        "reconciliation lossless Decimal aggregation",
    )

    old_variance = '''        variances = []
        for product_variant_id in sorted(set(expected_map) | set(actual_map)):
            expected = int(expected_map.get(product_variant_id, 0))
            actual = int(actual_map.get(product_variant_id, 0))
            if expected != actual:
                variances.append({
                    "product_variant_id": product_variant_id,
                    "expected": expected,
                    "actual": actual,
                    "variance": actual - expected,
                })
'''
    new_variance = '''        variances = []
        for product_variant_id in sorted(set(expected_map) | set(actual_map)):
            expected = expected_map.get(product_variant_id, Decimal("0"))
            actual = actual_map.get(product_variant_id, Decimal("0"))
            if expected != actual:
                variances.append({
                    "product_variant_id": product_variant_id,
                    "expected": expected,
                    "actual": actual,
                    "variance": actual - expected,
                })
'''
    src = replace_once(
        src, old_variance, new_variance,
        "reconciliation lossless Decimal variance",
    )
    return src


def patch_driver(src: str) -> str:
    src = replace_once(
        src,
        "from decimal import Decimal\n",
        "from decimal import Decimal\n"
        "from quantity import QUANTITY_MAX\n",
        "driver QUANTITY_MAX import",
    )

    old_snapshot = '''        for product_variant_id, stock_status, starting_quantity in opening_rows:
            qty = int(starting_quantity or 0)
            normalized_status = str(stock_status or "").upper()

            if normalized_status not in {
                "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED",
                "DAMAGED", "DISPOSAL_PENDING",
            }:
                raise RuntimeError("Vehicle opening inventory has unsupported stock_status.")
            if qty < 0 or qty > 2_147_483_647:
                raise RuntimeError(
                    "Vehicle opening inventory exceeds SessionInventorySnapshot INTEGER bounds."
                )

            db.add(
                SessionInventorySnapshot(
                    company_id=company_id,
                    work_session_id=new_session.id,
                    location_id=vehicle_location_id,
                    product_variant_id=product_variant_id,
                    stock_status=normalized_status,
                    starting_quantity=qty,
                )
            )
'''
    new_snapshot = '''        for product_variant_id, stock_status, starting_quantity in opening_rows:
            qty = Decimal(starting_quantity or 0)
            normalized_status = str(stock_status or "").upper()

            if normalized_status not in {
                "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED",
                "DAMAGED", "DISPOSAL_PENDING",
            }:
                raise RuntimeError("Vehicle opening inventory has unsupported stock_status.")
            if qty < Decimal("0") or qty > QUANTITY_MAX:
                raise RuntimeError(
                    "Vehicle opening inventory exceeds NUMERIC(20,6) quantity bounds."
                )

            db.add(
                SessionInventorySnapshot(
                    company_id=company_id,
                    work_session_id=new_session.id,
                    location_id=vehicle_location_id,
                    product_variant_id=product_variant_id,
                    stock_status=normalized_status,
                    starting_quantity=qty,
                )
            )
'''
    src = replace_once(
        src, old_snapshot, new_snapshot,
        "driver lossless opening snapshot",
    )
    return src


def patch_migration(src: str) -> str:
    old = """def downgrade() -> None:\n    op.execute(\n        \"\"\"\n        DELETE FROM permissions\n        WHERE code IN ('batch.disposition', 'inventory.status_change')\n        \"\"\"\n    )\n\n    op.drop_constraint(\n"""
    new = """def downgrade() -> None:\n    # Deliberately keep permission catalog rows on downgrade.\n    # They can be referenced by role_permissions, and deleting them would be\n    # destructive. Older application code safely ignores unknown permission codes.\n    op.drop_constraint(\n"""
    return replace_once(
        src, old, new,
        "migration non-destructive downgrade",
    )


def validate(files: dict[str, str]) -> None:
    for name, content in files.items():
        try:
            ast.parse(content)
        except SyntaxError as exc:
            abort(f"AST validation failed for {name}: {exc}")

    services = files["wa_backend/services.py"]
    warehouse = files["wa_backend/api/warehouse.py"]
    reconciliation = files["wa_backend/api/reconciliation.py"]
    driver = files["wa_backend/api/driver.py"]
    migration = files[str(MIGRATION_REL).replace("\\", "/")]

    require(
        services,
        [
            '"DISPOSAL_PENDING": frozenset()',
            '"RECALLED": frozenset()',
            "Stage 4E owns those directional workflows",
            "RECALLED is terminal here",
        ],
        "services hardening",
    )
    if '"RECALLED": frozenset({"QUARANTINED"' in services:
        abort("batch RECALLED still has a generic exit transition.")
    if '"DAMAGED": frozenset({"DISPOSAL_PENDING"})' in services:
        abort("generic status-change still owns DAMAGED -> DISPOSAL_PENDING.")
    if '"AVAILABLE": frozenset({\n        "QUARANTINED", "BLOCKED", "RECALLED", "DISPOSAL_PENDING"' in services:
        abort("generic status-change still owns AVAILABLE -> DISPOSAL_PENDING.")

    require(
        warehouse,
        [
            '"BATCH_ID_INVALID"',
            '"BATCH_DISPOSITION_REJECTED"',
            '"BATCH_DISPOSITION_CONFLICT"',
            '"PRODUCT_NOT_FOUND"',
            '"INVENTORY_STATUS_CHANGE_REJECTED"',
            '"INVENTORY_STATUS_CHANGE_CONFLICT"',
        ],
        "warehouse stable error envelopes",
    )

    require(
        reconciliation,
        [
            "actual_quantity: NonNegativeQuantity",
            "validate_variant_quantity(",
            'reserved_total = Decimal("0")',
            "next_total > QUANTITY_MAX",
            'expected = expected_map.get(product_variant_id, Decimal("0"))',
        ],
        "reconciliation Decimal invariants",
    )
    if "int(balance.on_hand_quantity or 0)" in reconciliation:
        abort("reconciliation still truncates on_hand quantity to int.")
    if "int(balance.reserved_quantity or 0)" in reconciliation:
        abort("reconciliation still truncates reserved quantity to int.")
    if "actual_quantity: StrictInt" in reconciliation:
        abort("reconciliation request still rejects fractional valid quantities.")

    require(
        driver,
        [
            "from quantity import QUANTITY_MAX",
            "qty = Decimal(starting_quantity or 0)",
            "qty > QUANTITY_MAX",
            "NUMERIC(20,6) quantity bounds",
        ],
        "driver Decimal opening snapshot",
    )
    if "qty = int(starting_quantity or 0)" in driver:
        abort("driver opening snapshot still truncates quantity to int.")

    require(
        migration,
        [
            "Deliberately keep permission catalog rows on downgrade.",
            'op.drop_constraint(\n        "chk_inv_bal_nonavailable_not_reserved"',
        ],
        "migration rollback safety",
    )
    if "DELETE FROM permissions" in migration:
        abort("migration downgrade still deletes permission catalog rows.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = root_dir()
    validate_baseline(root)

    paths = {
        "wa_backend/services.py": root / "wa_backend" / "services.py",
        "wa_backend/api/warehouse.py": root / "wa_backend" / "api" / "warehouse.py",
        "wa_backend/api/reconciliation.py": root / "wa_backend" / "api" / "reconciliation.py",
        "wa_backend/api/driver.py": root / "wa_backend" / "api" / "driver.py",
        str(MIGRATION_REL).replace("\\", "/"): root / MIGRATION_REL,
    }

    for name, path in paths.items():
        if not path.is_file():
            abort(f"required file missing: {name}")

    originals = {name: read(path) for name, path in paths.items()}

    if any(PATCH_ID in content for content in originals.values()):
        abort("Stage 4D.1 marker already exists; refusing partial/double application.")

    require(
        originals["wa_backend/services.py"],
        [
            "_PORTION_STATUS_TRANSITIONS = {",
            "_BATCH_DISPOSITION_TRANSITIONS = {",
            "STOCK_STATUS_TRANSITION_BLOCKED",
            "BATCH_DISPOSITION_TRANSITION_BLOCKED",
        ],
        "services preflight",
    )
    require(
        originals["wa_backend/api/warehouse.py"],
        [
            '"/warehouse/batches/{batch_id}/disposition"',
            '"/warehouse/inventory/status-change"',
            "InventoryRuleError",
        ],
        "warehouse preflight",
    )
    require(
        originals["wa_backend/api/reconciliation.py"],
        [
            "actual_quantity: StrictInt",
            "int(balance.on_hand_quantity or 0)",
            "int(balance.reserved_quantity or 0)",
        ],
        "reconciliation preflight",
    )
    require(
        originals["wa_backend/api/driver.py"],
        [
            "qty = int(starting_quantity or 0)",
            "SessionInventorySnapshot",
        ],
        "driver preflight",
    )
    require(
        originals[str(MIGRATION_REL).replace("\\", "/")],
        [
            'revision: str = "19c740dc40e8"',
            'down_revision: Union[str, Sequence[str], None] = "c3f4e5a6b7d8"',
            "DELETE FROM permissions",
        ],
        "migration preflight",
    )

    patched = dict(originals)
    patched["wa_backend/services.py"] = patch_services(
        patched["wa_backend/services.py"]
    )
    patched["wa_backend/api/warehouse.py"] = patch_warehouse(
        patched["wa_backend/api/warehouse.py"]
    )
    patched["wa_backend/api/reconciliation.py"] = patch_reconciliation(
        patched["wa_backend/api/reconciliation.py"]
    )
    patched["wa_backend/api/driver.py"] = patch_driver(
        patched["wa_backend/api/driver.py"]
    )
    migration_key = str(MIGRATION_REL).replace("\\", "/")
    patched[migration_key] = patch_migration(patched[migration_key])

    patched["wa_backend/services.py"] = patched["wa_backend/services.py"].replace(
        "# Stage 4D.1: keep the generic same-location reclassification command narrow.",
        f"# {PATCH_ID}\n"
        "# Stage 4D.1: keep the generic same-location reclassification command narrow.",
        1,
    )

    validate(patched)

    if args.check:
        print("STAGE4D1_PREFLIGHT_OK")
        print(f"BASELINE_HEAD: {EXPECTED_HEAD}")
        print(
            "FILES_TO_CHANGE: services.py + api/warehouse.py + "
            "api/reconciliation.py + api/driver.py + Stage4D migration downgrade"
        )
        print("DB_FORWARD_SCHEMA_CHANGE: NONE")
        return

    backup_dir = root / ".patch_backups" / PATCH_ID
    if backup_dir.exists():
        abort(f"backup directory already exists: {backup_dir}")
    backup_dir.mkdir(parents=True, exist_ok=False)

    for name, path in paths.items():
        backup_name = name.replace("/", "__")
        shutil.copy2(path, backup_dir / backup_name)

    for name, content in patched.items():
        paths[name].write_text(content, encoding="utf-8", newline="\n")

    print("STAGE4D1_HARDENING_OK")
    print("WORKFLOW_OK: generic status/disposition transitions narrowed; Stage4E retains directional return/disposal ownership")
    print("ERROR_CONTRACT_OK: new Stage4D business failures use stable machine-code envelopes")
    print("DECIMAL_OK: vehicle opening/reconciliation quantities remain Decimal/NUMERIC(20,6) without int truncation")
    print("UOM_STEP_OK: reconciliation actual quantities validate variant scale/step")
    print("DOWNGRADE_OK: Stage4D rollback no longer deletes permission catalog/grants")
    print("DB_FORWARD_SCHEMA_CHANGE: NONE")
    print("NOTE: no project files were deleted.")


if __name__ == "__main__":
    main()
