from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
from pathlib import Path

MARKER = "STAGE4D_BATCH_DISPOSITION_PORTION_STATUS"
EXPECTED_HEAD = "5eb9608e9dd2c49b64be3686c5f3ec58b293f357"
EXPECTED_DOWN_REVISION = "c3f4e5a6b7d8"
MIGRATION_SLUG = "stage4d_batch_disposition_and_portion_statuses"


def abort(message: str) -> None:
    raise SystemExit(f"PATCH_ABORT: {message}")


def locate_root() -> Path:
    root = Path.cwd()
    if not (root / ".git").exists() or not (root / "wa_backend" / "models.py").exists():
        abort("شغّل الباتش من جذر المشروع الذي يحتوي .git و wa_backend.")
    return root


def git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        abort(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def validate_git_baseline(root: Path) -> None:
    head = git_output(root, "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        abort(
            f"HEAD لا يطابق dev inv 6 المدقق. expected={EXPECTED_HEAD}, actual={head}"
        )

    for args, label in [
        (("diff", "--quiet"), "tracked working tree"),
        (("diff", "--cached", "--quiet"), "staged index"),
    ]:
        proc = subprocess.run(["git", *args], cwd=root, check=False)
        if proc.returncode != 0:
            abort(f"{label} ليس نظيفاً. اعمل commit/stash للتعديلات المقصودة أولاً.")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        abort(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def replace_exact_count(
    text: str, old: str, new: str, expected: int, label: str
) -> str:
    count = text.count(old)
    if count != expected:
        abort(f"{label}: expected {expected} matches, found {count}")
    return text.replace(old, new)


def require_tokens(text: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        abort(f"{label}: required markers missing: {missing}")


def find_generated_migration(root: Path) -> Path:
    versions = root / "wa_backend" / "alembic" / "versions"
    matches = sorted(versions.glob(f"*_{MIGRATION_SLUG}.py"))
    if len(matches) != 1:
        abort(
            "أنشئ migration أولاً بالأمر المحدد. "
            f"Expected exactly one *_{MIGRATION_SLUG}.py, found {len(matches)}."
        )
    return matches[0]


def parse_revision(text: str) -> tuple[str, str]:
    rev_match = re.search(
        r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]",
        text,
        re.MULTILINE,
    )
    down_match = re.search(
        r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]",
        text,
        re.MULTILINE,
    )
    if not rev_match or not down_match:
        abort("تعذر قراءة revision/down_revision من migration المولد.")
    return rev_match.group(1), down_match.group(1)


def build_migration(revision: str) -> str:
    return f'''\"\"\"stage4d batch disposition and portion statuses

Revision ID: {revision}
Revises: {EXPECTED_DOWN_REVISION}
\"\"\"

from typing import Sequence, Union

from alembic import op


revision: str = "{revision}"
down_revision: Union[str, Sequence[str], None] = "{EXPECTED_DOWN_REVISION}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # لا نصحح أي بيانات بصمت. إذا وجدت Reservation في Bucket غير AVAILABLE
    # فهذا فساد يجب كشفه قبل فرض القيد الجديد.
    op.execute(
        \"\"\"
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_balances
                WHERE stock_status <> 'AVAILABLE'
                  AND reserved_quantity <> 0
            ) THEN
                RAISE EXCEPTION
                    'Stage4D invariant violation: non-AVAILABLE balance has reserved quantity';
            END IF;
        END
        $$;
        \"\"\"
    )

    op.drop_constraint(
        "chk_inv_bal_damaged_not_reserved",
        "inventory_balances",
        type_="check",
    )
    op.create_check_constraint(
        "chk_inv_bal_nonavailable_not_reserved",
        "inventory_balances",
        "stock_status = 'AVAILABLE' OR reserved_quantity = 0",
    )

    # Permission catalog عالمي؛ Admin الحالي يبقى bypass كامل،
    # والمستخدم المحدود لا يحصل على شيء حتى يُمنح Role صريحاً.
    op.execute(
        \"\"\"
        INSERT INTO permissions (code)
        VALUES ('batch.disposition'), ('inventory.status_change')
        ON CONFLICT (code) DO NOTHING
        \"\"\"
    )


def downgrade() -> None:
    op.execute(
        \"\"\"
        DELETE FROM permissions
        WHERE code IN ('batch.disposition', 'inventory.status_change')
        \"\"\"
    )

    op.drop_constraint(
        "chk_inv_bal_nonavailable_not_reserved",
        "inventory_balances",
        type_="check",
    )
    op.create_check_constraint(
        "chk_inv_bal_damaged_not_reserved",
        "inventory_balances",
        "stock_status <> 'DAMAGED' OR reserved_quantity = 0",
    )
'''


SERVICES_DOMAIN_BLOCK = r'''
# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS

_INVENTORY_STOCK_STATUSES = frozenset({
    "AVAILABLE",
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
    "DAMAGED",
    "DISPOSAL_PENDING",
})

# Conservative transitions derived from the approved Stage 4 capability matrix.
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

_BATCH_DISPOSITIONS = frozenset({
    "RELEASED", "QUARANTINED", "BLOCKED", "RECALLED",
})

# QUARANTINED -> RELEASED is the explicit Test/Release path.
# RECALL can move only to a safer quarantine state, never directly to RELEASED.
_BATCH_DISPOSITION_TRANSITIONS = {
    "RELEASED": frozenset({"QUARANTINED", "BLOCKED", "RECALLED"}),
    "QUARANTINED": frozenset({"RELEASED", "BLOCKED", "RECALLED"}),
    "BLOCKED": frozenset({"RECALLED"}),
    "RECALLED": frozenset({"QUARANTINED"}),
}


class InventoryRuleError(InventoryMutationError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = str(code)
        self.context = dict(context or {})
        super().__init__(message)

    def as_detail(self) -> Dict[str, Any]:
        return inventory_business_error(
            self.code,
            str(self),
            context=self.context,
        )


async def change_product_batch_disposition(
    db_session: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    batch_id: int,
    expected_revision: int,
    target_disposition: str,
    reason: str,
    request_id: UUID,
) -> ProductBatch:
    """Batch-wide safety overlay; never rewrites portion stock_status implicitly."""
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        actor_id = _strict_int(actor_id, "actor_id", minimum=1)
        batch_id = _strict_int(batch_id, "batch_id", minimum=1)
        expected_revision = _strict_int(
            expected_revision,
            "expected_revision",
            minimum=1,
        )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    target = str(target_disposition or "").strip().upper()
    if target not in _BATCH_DISPOSITIONS:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_INVALID",
            "حالة الدفعة المطلوبة غير صالحة.",
            context={"batch_id": batch_id, "target_disposition": target},
        )

    if not isinstance(reason, str):
        raise InventoryMutationError("سبب تغيير حالة الدفعة يجب أن يكون نصاً.")
    reason = reason.strip()
    if not reason or "\x00" in reason or len(reason) > 2000:
        raise InventoryMutationError(
            "سبب تغيير حالة الدفعة مطلوب ويجب ألا يتجاوز 2000 حرف."
        )
    if not isinstance(request_id, UUID):
        raise InventoryMutationError("request_id يجب أن يكون UUID صالحاً.")

    # قراءة الهوية فقط قبل الحارس؛ القرار نفسه يعاد تحت shared lifecycle guard
    # ثم Row Lock على ProductBatch، وهو نفس الصف الذي تقفله FEFO في Stage 4C.
    variant_id = (
        await db_session.execute(
            select(ProductBatch.product_variant_id).filter(
                ProductBatch.company_id == company_id,
                ProductBatch.id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if variant_id is None:
        raise InventoryRuleError(
            "BATCH_NOT_FOUND",
            "الدفعة غير موجودة أو لا تتبع الشركة.",
            context={"batch_id": batch_id},
        )
    variant_id = int(variant_id)

    await acquire_product_lifecycle_guards(
        db_session,
        company_id,
        [variant_id],
        exclusive=False,
    )

    batch = (
        await db_session.execute(
            select(ProductBatch)
            .execution_options(populate_existing=True)
            .filter(
                ProductBatch.company_id == company_id,
                ProductBatch.id == batch_id,
                ProductBatch.product_variant_id == variant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise InventoryRuleError(
            "BATCH_NOT_FOUND",
            "الدفعة تغيرت أو لم تعد متاحة داخل الشركة.",
            context={"batch_id": batch_id},
        )

    variant_state = (
        await db_session.execute(
            select(
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
            ).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id == variant_id,
            )
        )
    ).one_or_none()
    if variant_state is None:
        raise InventoryMutationError("الصنف المرتبط بالدفعة غير موجود داخل الشركة.")

    if not bool(batch.is_active):
        raise InventoryRuleError(
            "BATCH_INACTIVE",
            "الدفعة متوقفة إدارياً ولا تقبل تغيير disposition جديداً.",
            context={"batch_id": batch_id},
        )

    current_revision = int(batch.disposition_revision)
    if current_revision != expected_revision:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_REVISION_CONFLICT",
            "تغيرت حالة الدفعة منذ فتحها. حدّث البيانات ثم أعد المحاولة.",
            context={
                "batch_id": batch_id,
                "expected_revision": expected_revision,
                "current_revision": current_revision,
            },
        )

    current = str(batch.disposition or "").strip().upper()
    if current not in _BATCH_DISPOSITIONS:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_INVALID",
            "الدفعة تحمل disposition غير معروف.",
            context={"batch_id": batch_id, "current_disposition": current},
        )
    if current == target:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_NO_CHANGE",
            "الدفعة موجودة بالفعل بالحالة المطلوبة.",
            context={"batch_id": batch_id, "disposition": current},
        )
    if target not in _BATCH_DISPOSITION_TRANSITIONS[current]:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_TRANSITION_BLOCKED",
            "انتقال disposition المطلوب غير مسموح حسب مصفوفة Stage 4.",
            context={
                "batch_id": batch_id,
                "from": current,
                "to": target,
            },
        )

    lifecycle_status = str(variant_state.lifecycle_status or "").upper()
    operational_hold = str(variant_state.operational_hold or "").upper()
    if lifecycle_status in {"DRAFT", "ARCHIVED"}:
        raise InventoryRuleError(
            "PRODUCT_NOT_OPERATIONAL",
            "حالة الصنف لا تسمح بأمر disposition تشغيلي جديد.",
            context={
                "product_variant_id": variant_id,
                "lifecycle_status": lifecycle_status,
            },
        )
    if target == "RELEASED" and operational_hold != "NONE":
        hold_code = (
            "PRODUCT_RECALLED"
            if operational_hold == "RECALL"
            else "PRODUCT_SALES_HOLD"
        )
        raise InventoryRuleError(
            hold_code,
            "لا يمكن تحرير الدفعة إلى RELEASED أثناء وجود Hold تشغيلي على الصنف.",
            context={
                "product_variant_id": variant_id,
                "batch_id": batch_id,
                "operational_hold": operational_hold,
            },
        )

    before = {
        "id": int(batch.id),
        "product_variant_id": variant_id,
        "disposition": current,
        "disposition_reason": batch.disposition_reason,
        "disposition_revision": current_revision,
    }

    batch.disposition = target
    batch.disposition_reason = reason
    batch.disposition_revision = current_revision + 1
    batch.updated_at = utc_now()

    after = {
        "id": int(batch.id),
        "product_variant_id": variant_id,
        "disposition": target,
        "disposition_reason": reason,
        "disposition_revision": current_revision + 1,
    }

    record_domain_event(
        db_session,
        company_id=company_id,
        actor_id=actor_id,
        request_id=request_id,
        event_type="BatchDispositionChanged",
        entity_type="ProductBatch",
        entity_id=batch_id,
        reason=reason,
        before=before,
        after=after,
        emit_outbox=True,
    )
    await db_session.flush()
    return batch
'''


SCHEMAS_BLOCK = r'''
# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS

InventoryStockStatus = Literal[
    "AVAILABLE",
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
    "DAMAGED",
    "DISPOSAL_PENDING",
]


class BatchDispositionChangeRequest(RequestModel):
    request_id: UUID
    expected_revision: PositiveDbInt
    disposition: Literal["RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"]
    reason: str = Field(..., min_length=1, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> str:
        return _required_text(v)


class BatchDispositionMutationResponse(BaseModel):
    message: str
    batch_id: PositiveDbInt
    product_variant_id: PositiveDbInt
    batch_number: str
    disposition: Literal["RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"]
    disposition_reason: Optional[str] = None
    disposition_revision: PositiveDbInt
    updated_at: datetime


class InventoryStatusChangeRequest(RequestModel):
    request_id: UUID
    location_id: PositiveDbInt
    product_variant_id: PositiveDbInt
    batch_id: PositiveDbInt
    uom_id: PositiveDbInt
    source_status: InventoryStockStatus
    destination_status: InventoryStockStatus
    quantity: PositiveQuantity
    reason: str = Field(..., min_length=1, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> str:
        return _required_text(v)

    @model_validator(mode="after")
    def reject_same_status(self) -> "InventoryStatusChangeRequest":
        if self.source_status == self.destination_status:
            raise ValueError("source_status و destination_status يجب أن يكونا مختلفين.")
        return self


class InventoryStatusChangeResponse(BaseModel):
    message: str
    movement_id: PositiveDbInt
    source_status: InventoryStockStatus
    destination_status: InventoryStockStatus
'''


WAREHOUSE_ENDPOINTS = r'''
# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS

@router.post(
    "/warehouse/batches/{batch_id}/disposition",
    response_model=BatchDispositionMutationResponse,
    status_code=200,
)
async def change_batch_disposition(
    batch_id: int,
    payload: BatchDispositionChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("batch.disposition")

    if batch_id <= 0:
        raise HTTPException(status_code=422, detail="batch_id يجب أن يكون موجباً.")

    company_id = current_admin.company_id
    try:
        request_hash = _stable_request_hash(
            payload,
            context={"batch_id": int(batch_id)},
        )
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="BATCH_DISPOSITION_CHANGE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        batch = await change_product_batch_disposition(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            batch_id=batch_id,
            expected_revision=payload.expected_revision,
            target_disposition=payload.disposition,
            reason=payload.reason,
            request_id=payload.request_id,
        )

        response_payload = {
            "message": "تم تحديث disposition للدفعة دون تغيير Bucket الرصيد تلقائياً.",
            "batch_id": int(batch.id),
            "product_variant_id": int(batch.product_variant_id),
            "batch_number": str(batch.batch_number),
            "disposition": str(batch.disposition),
            "disposition_reason": batch.disposition_reason,
            "disposition_revision": int(batch.disposition_revision),
            "updated_at": batch.updated_at.isoformat(),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except InventoryRuleError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير disposition للدفعة", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء تغيير حالة الدفعة؛ أعد المحاولة.",
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("خطأ داخلي أثناء تغيير disposition للدفعة", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء تحديث حالة الدفعة.",
        ) from exc


@router.post(
    "/warehouse/inventory/status-change",
    response_model=InventoryStatusChangeResponse,
    status_code=200,
)
async def change_inventory_status(
    payload: InventoryStatusChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.status_change", payload.location_id)

    company_id = current_admin.company_id
    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="INVENTORY_STATUS_CHANGE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        base_uom_id = (
            await db.execute(
                select(ProductVariant.base_uom_id).filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id == payload.product_variant_id,
                )
            )
        ).scalar_one_or_none()
        if base_uom_id is None:
            raise HTTPException(
                status_code=404,
                detail="الصنف غير موجود أو لا يتبع الشركة.",
            )
        if int(base_uom_id) != int(payload.uom_id):
            raise HTTPException(
                status_code=422,
                detail=inventory_business_error(
                    "UOM_MISMATCH",
                    "تغيير حالة المخزون يجب أن يستخدم وحدة أساس الصنف.",
                    context={
                        "product_variant_id": int(payload.product_variant_id),
                        "expected_uom_id": int(base_uom_id),
                    },
                ),
            )

        movement = await apply_inventory_movement(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            product_variant_id=payload.product_variant_id,
            batch_id=payload.batch_id,
            quantity=payload.quantity,
            movement_kind="STATUS_CHANGE",
            reference_type="STATUS_RECLASSIFICATION",
            reference_id=str(payload.request_id),
            idempotency_key=f"STATUS-{payload.request_id}",
            source_location_id=payload.location_id,
            destination_location_id=payload.location_id,
            source_stock_status=payload.source_status,
            destination_stock_status=payload.destination_status,
            notes=payload.reason,
        )

        response_payload = {
            "message": "تم تغيير Bucket الرصيد عبر Unified Inventory Movement Engine.",
            "movement_id": int(movement.id),
            "source_status": str(movement.source_stock_status),
            "destination_status": str(movement.destination_stock_status),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except InventoryRuleError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير Bucket المخزون", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء تغيير حالة الرصيد؛ أعد المحاولة.",
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("خطأ داخلي أثناء تغيير Bucket المخزون", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء تغيير حالة الرصيد.",
        ) from exc


'''


BLOCKED_STATUS_SUBQUERY = r'''
        warehouse_blocked_status_subq = (
            select(
                InventoryBalance.product_variant_id,
                func.sum(
                    InventoryBalance.on_hand_quantity
                ).label('blocked_status_packs'),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.stock_status.in_([
                    'QUARANTINED',
                    'BLOCKED',
                    'RECALLED',
                    'DISPOSAL_PENDING',
                ]),
                InventoryBalance.product_variant_id.in_(
                    page_variant_ids
                ),
            )
            .group_by(InventoryBalance.product_variant_id)
            .subquery()
        )

'''


def patch_models(src: str) -> str:
    return replace_once(
        src,
        '        CheckConstraint("stock_status <> \'DAMAGED\' OR reserved_quantity = 0", name=\'chk_inv_bal_damaged_not_reserved\'),\n',
        '        CheckConstraint("stock_status = \'AVAILABLE\' OR reserved_quantity = 0", name=\'chk_inv_bal_nonavailable_not_reserved\'),\n',
        "models non-AVAILABLE reservation invariant",
    )


def patch_inventory_access(src: str) -> str:
    src = replace_once(
        src,
        "    'inventory.read', 'inbound.create', 'ledger.read', 'ledger.adjust',\n",
        "    'inventory.read', 'inbound.create', 'ledger.read', 'ledger.adjust',\n"
        "    'batch.disposition', 'inventory.status_change',\n",
        "inventory_access permission catalog",
    )
    src = replace_once(
        src,
        "    'catalog.restore', 'catalog.archive', 'catalog.hold',\n",
        "    'catalog.restore', 'catalog.archive', 'catalog.hold',\n"
        "    'batch.disposition',\n",
        "inventory_access company-only batch permission",
    )
    return src


def patch_schemas(src: str) -> str:
    src = replace_once(
        src,
        "\n\nclass UnifiedTransferItem(RequestModel):\n",
        "\n\n" + SCHEMAS_BLOCK + "\n\nclass UnifiedTransferItem(RequestModel):\n",
        "schemas disposition/status contracts",
    )
    src = replace_once(
        src,
        '    stock_status: Literal["AVAILABLE", "DAMAGED"]\n',
        "    stock_status: InventoryStockStatus\n",
        "schemas stocktake all portion statuses",
    )
    return src


def patch_services(src: str) -> str:
    src = replace_once(
        src,
        "from product_lifecycle import acquire_product_lifecycle_guards\n",
        "from product_lifecycle import acquire_product_lifecycle_guards, record_domain_event\n",
        "services domain event import",
    )

    old_error = '''class InventoryMutationError(Exception):
    pass


def inventory_business_error(
'''
    new_error = '''class InventoryMutationError(Exception):
    pass


''' + SERVICES_DOMAIN_BLOCK + '''


def inventory_business_error(
'''
    src = replace_once(src, old_error, new_error, "services Stage4D domain block")

    src = replace_once(
        src,
        '    allowed_statuses = {"AVAILABLE", "DAMAGED"}\n',
        '    allowed_statuses = _INVENTORY_STOCK_STATUSES\n',
        "services movement status catalog",
    )

    old_status_shape = '''    if movement_kind == "STATUS_CHANGE" and (
        source_location_id is None
        or destination_location_id != source_location_id
        or source_stock_status == destination_stock_status
    ):
        raise InventoryMutationError("شكل تغيير حالة المخزون غير صالح.")
'''
    new_status_shape = '''    if movement_kind == "STATUS_CHANGE":
        if (
            source_location_id is None
            or destination_location_id != source_location_id
            or source_stock_status == destination_stock_status
        ):
            raise InventoryMutationError("شكل تغيير حالة المخزون غير صالح.")
        allowed_destinations = _PORTION_STATUS_TRANSITIONS.get(
            source_stock_status,
            frozenset(),
        )
        if destination_stock_status not in allowed_destinations:
            raise InventoryRuleError(
                "STOCK_STATUS_TRANSITION_BLOCKED",
                "انتقال حالة الرصيد المطلوب غير مسموح حسب مصفوفة Stage 4.",
                context={
                    "from": source_stock_status,
                    "to": destination_stock_status,
                },
            )
'''
    src = replace_once(
        src,
        old_status_shape,
        new_status_shape,
        "services status transition matrix",
    )

    old_variant = '''            select(
                ProductVariant.id,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                ProductVariant.lifecycle_status,
            ).filter(
'''
    new_variant = '''            select(
                ProductVariant.id,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
                ProductVariant.expiry_control_mode,
            ).filter(
'''
    src = replace_once(src, old_variant, new_variant, "services variant rules select")

    old_rules = '''    variant_rules = {
        int(row.id): (int(row.quantity_scale), row.quantity_step, row.lifecycle_status)
        for row in variant_rows
    }
'''
    new_rules = '''    variant_rules = {
        int(row.id): (
            int(row.quantity_scale),
            row.quantity_step,
            row.lifecycle_status,
            row.operational_hold,
            row.expiry_control_mode,
        )
        for row in variant_rows
    }
'''
    src = replace_once(src, old_rules, new_rules, "services variant rules map")

    src = replace_once(
        src,
        '            scale, step, lifecycle_status = variant_rules[spec["product_variant_id"]]\n',
        '            scale, step, lifecycle_status, _operational_hold, _expiry_mode = variant_rules[spec["product_variant_id"]]\n',
        "services variant rules unpack",
    )

    old_batch_validation = '''    batch_keys = sorted({
        (spec["product_variant_id"], spec["batch_id"])
        for spec in new_specs
    })
    valid_batch_keys = set(
        (
            await db_session.execute(
                select(
                    ProductBatch.product_variant_id,
                    ProductBatch.id,
                ).filter(
                    ProductBatch.company_id == company_id,
                    tuple_(
                        ProductBatch.product_variant_id,
                        ProductBatch.id,
                    ).in_(batch_keys),
                )
            )
        ).all()
    )
    if valid_batch_keys != set(batch_keys):
        raise InventoryMutationError(
            "إحدى الدفعات لا تنتمي للصنف أو الشركة المحددة."
        )
'''
    new_batch_validation = '''    batch_keys = sorted({
        (spec["product_variant_id"], spec["batch_id"])
        for spec in new_specs
    })
    locked_batches = (
        await db_session.execute(
            select(ProductBatch)
            .execution_options(populate_existing=True)
            .filter(
                ProductBatch.company_id == company_id,
                tuple_(
                    ProductBatch.product_variant_id,
                    ProductBatch.id,
                ).in_(batch_keys),
            )
            .order_by(
                ProductBatch.product_variant_id.asc(),
                ProductBatch.id.asc(),
            )
            .with_for_update()
        )
    ).scalars().all()
    batch_map = {
        (int(batch.product_variant_id), int(batch.id)): batch
        for batch in locked_batches
    }
    if set(batch_map) != set(batch_keys):
        raise InventoryMutationError(
            "إحدى الدفعات لا تنتمي للصنف أو الشركة المحددة."
        )

    # تحرير Portion إلى AVAILABLE قرار correctness لحظي، وليس مجرد تغيير Label.
    # يتم بعد location guards وتحت Row Lock على ProductBatch كي لا يسبق Recall/Expiry race.
    release_specs = [
        spec
        for spec in new_specs
        if spec["movement_kind"] == "STATUS_CHANGE"
        and spec["destination_stock_status"] == "AVAILABLE"
    ]
    if release_specs:
        as_of_date = await get_company_local_date(db_session, company_id)
        policy_keys = sorted({
            (int(spec["destination_location_id"]), int(spec["product_variant_id"]))
            for spec in release_specs
        })
        policy_rows = (
            await db_session.execute(
                select(
                    InventoryStockPolicy.location_id,
                    InventoryStockPolicy.product_variant_id,
                    InventoryStockPolicy.minimum_remaining_shelf_life_days,
                ).filter(
                    InventoryStockPolicy.company_id == company_id,
                    InventoryStockPolicy.is_active.is_(True),
                    tuple_(
                        InventoryStockPolicy.location_id,
                        InventoryStockPolicy.product_variant_id,
                    ).in_(policy_keys),
                )
            )
        ).all()
        min_shelf_life = {
            (int(row.location_id), int(row.product_variant_id)):
                int(row.minimum_remaining_shelf_life_days or 0)
            for row in policy_rows
        }

        for spec in release_specs:
            variant_id = int(spec["product_variant_id"])
            location_id = int(spec["destination_location_id"])
            batch = batch_map[(variant_id, int(spec["batch_id"]))]
            (
                _scale,
                _step,
                _lifecycle_status,
                operational_hold,
                expiry_control_mode,
            ) = variant_rules[variant_id]

            normalized_hold = str(operational_hold or "").upper()
            if normalized_hold != "NONE":
                hold_code = (
                    "PRODUCT_RECALLED"
                    if normalized_hold == "RECALL"
                    else "PRODUCT_SALES_HOLD"
                )
                raise InventoryRuleError(
                    hold_code,
                    "لا يمكن تحرير الرصيد إلى AVAILABLE أثناء وجود Hold تشغيلي على الصنف.",
                    context={
                        "product_variant_id": variant_id,
                        "batch_id": int(batch.id),
                        "operational_hold": normalized_hold,
                    },
                )
            if not bool(batch.is_active):
                raise InventoryRuleError(
                    "BATCH_NOT_ELIGIBLE",
                    "الدفعة متوقفة إدارياً ولا يمكن تحرير رصيدها إلى AVAILABLE.",
                    context={"batch_id": int(batch.id)},
                )
            if str(batch.disposition or "").upper() != "RELEASED":
                raise InventoryRuleError(
                    "BATCH_NOT_RELEASED",
                    "الدفعة ليست RELEASED ولا يمكن تحرير رصيدها إلى AVAILABLE.",
                    context={
                        "batch_id": int(batch.id),
                        "disposition": str(batch.disposition),
                    },
                )
            if (
                batch.production_date is not None
                and batch.production_date > as_of_date
            ):
                raise InventoryRuleError(
                    "BATCH_NOT_ELIGIBLE",
                    "تاريخ إنتاج الدفعة يقع في المستقبل.",
                    context={"batch_id": int(batch.id)},
                )
            if batch.expiry_date is not None and batch.expiry_date < as_of_date:
                raise InventoryRuleError(
                    "BATCH_EXPIRED",
                    "الدفعة منتهية الصلاحية ولا يمكن تحريرها إلى AVAILABLE.",
                    context={
                        "batch_id": int(batch.id),
                        "expiry_date": batch.expiry_date.isoformat(),
                    },
                )

            minimum_days = min_shelf_life.get((location_id, variant_id), 0)
            if not _batch_metadata_is_sellable(
                as_of_date=as_of_date,
                expiry_control_mode=str(expiry_control_mode),
                production_date=batch.production_date,
                expiry_date=batch.expiry_date,
                minimum_remaining_shelf_life_days=minimum_days,
            ):
                raise InventoryRuleError(
                    "SHELF_LIFE_POLICY_BLOCKED",
                    "الدفعة لا تحقق سياسة الصلاحية/العمر المتبقي للموقع.",
                    context={
                        "location_id": location_id,
                        "product_variant_id": variant_id,
                        "batch_id": int(batch.id),
                        "minimum_remaining_shelf_life_days": minimum_days,
                    },
                )
'''
    src = replace_once(
        src,
        old_batch_validation,
        new_batch_validation,
        "services locked batch validation + AVAILABLE release gate",
    )

    src = replace_exact_count(
        src,
        '                InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),\n',
        "",
        2,
        "services vehicle reconciliation all statuses",
    )

    src = replace_once(
        src,
        '        if stock_status not in {"AVAILABLE", "DAMAGED"}:\n'
        '            raise InventoryMutationError("حالة مخزون غير صالحة في سطر الجرد.")\n',
        '        if stock_status not in _INVENTORY_STOCK_STATUSES:\n'
        '            raise InventoryMutationError("حالة مخزون غير صالحة في سطر الجرد.")\n',
        "services stocktake status validation",
    )

    return src


def patch_warehouse(src: str) -> str:
    src = replace_once(
        src,
        "    InventoryMutationError,\n)",
        "    InventoryMutationError,\n"
        "    InventoryRuleError,\n"
        "    change_product_batch_disposition,\n)",
        "warehouse service imports",
    )

    src = replace_once(
        src,
        "UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )\n",
        "UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest,\n"
        "BatchDispositionChangeRequest, BatchDispositionMutationResponse,\n"
        "InventoryStatusChangeRequest, InventoryStatusChangeResponse )\n",
        "warehouse schema imports",
    )

    transfer_anchor = '''@router.get(
    "/warehouse/unified/transfer/locations",
'''
    src = replace_once(
        src,
        transfer_anchor,
        WAREHOUSE_ENDPOINTS + transfer_anchor,
        "warehouse Stage4D endpoints",
    )

    src = replace_once(
        src,
        "                InventoryBalance.stock_status == 'AVAILABLE',\n"
        "                InventoryBalance.on_hand_quantity > 0,\n"
        "                InventoryLocation.company_id == company_id,\n"
        "                InventoryLocation.location_type == 'VEHICLE',\n",
        "                InventoryBalance.stock_status != 'DAMAGED',\n"
        "                InventoryBalance.on_hand_quantity > 0,\n"
        "                InventoryLocation.company_id == company_id,\n"
        "                InventoryLocation.location_type == 'VEHICLE',\n",
        "warehouse vehicle visibility includes safety buckets",
    )

    src = replace_once(
        src,
        "        warehouse_damaged_subq = (\n",
        BLOCKED_STATUS_SUBQUERY + "        warehouse_damaged_subq = (\n",
        "warehouse blocked portion subquery",
    )

    src = replace_once(
        src,
        "                warehouse_available_subq.c.warehouse_sellable_reserved,\n"
        "                warehouse_damaged_subq.c.damaged_packs,\n",
        "                warehouse_available_subq.c.warehouse_sellable_reserved,\n"
        "                warehouse_blocked_status_subq.c.blocked_status_packs,\n"
        "                warehouse_damaged_subq.c.damaged_packs,\n",
        "warehouse select blocked portion quantity",
    )

    src = replace_once(
        src,
        "            .outerjoin(\n"
        "                warehouse_damaged_subq,\n"
        "                warehouse_damaged_subq.c.product_variant_id\n"
        "                == ProductVariant.id,\n"
        "            )\n",
        "            .outerjoin(\n"
        "                warehouse_blocked_status_subq,\n"
        "                warehouse_blocked_status_subq.c.product_variant_id\n"
        "                == ProductVariant.id,\n"
        "            )\n"
        "            .outerjoin(\n"
        "                warehouse_damaged_subq,\n"
        "                warehouse_damaged_subq.c.product_variant_id\n"
        "                == ProductVariant.id,\n"
        "            )\n",
        "warehouse join blocked portion quantity",
    )

    src = replace_once(
        src,
        "            warehouse_sellable_reserved,\n"
        "            damaged_packs,\n",
        "            warehouse_sellable_reserved,\n"
        "            blocked_status_packs,\n"
        "            damaged_packs,\n",
        "warehouse row unpack blocked portion quantity",
    )

    src = replace_once(
        src,
        "            blocked_quantity = on_hand - sellable_on_hand\n"
        "            vehicle_total = Decimal(vehicle_packs or 0)\n",
        "            explicit_blocked = Decimal(blocked_status_packs or 0)\n"
        "            blocked_quantity = (on_hand - sellable_on_hand) + explicit_blocked\n"
        "            vehicle_total = Decimal(vehicle_packs or 0)\n",
        "warehouse blocked quantity formula",
    )

    src = replace_once(
        src,
        "            total_physical_available = on_hand + vehicle_total\n",
        "            total_physical_available = on_hand + explicit_blocked + vehicle_total\n",
        "warehouse total preserves non-damaged physical safety buckets",
    )

    vehicle_inventory_old = '''                InventoryBalance.company_id == company_id,
                InventoryBalance.stock_status == 'AVAILABLE',
                InventoryBalance.product_variant_id.in_(
                    page_variant_ids
                ),
                InventoryLocation.company_id == company_id,
'''
    vehicle_inventory_new = '''                InventoryBalance.company_id == company_id,
                InventoryBalance.stock_status != 'DAMAGED',
                InventoryBalance.product_variant_id.in_(
                    page_variant_ids
                ),
                InventoryLocation.company_id == company_id,
'''
    src = replace_once(
        src,
        vehicle_inventory_old,
        vehicle_inventory_new,
        "warehouse vehicle total includes safety buckets",
    )

    src = replace_once(
        src,
        '        InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),\n',
        "",
        "warehouse stocktake batch candidate all statuses",
    )
    src = replace_once(
        src,
        "            InventoryBalance.stock_status.in_(['AVAILABLE', 'DAMAGED']),\n",
        "",
        "warehouse stocktake snapshot all statuses",
    )

    expiry_discovered_block = '''                    if expiry_date < as_of_date:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "الدفعة المنتهية لا يجوز تسجيلها DISCOVERED "
                                "بحالة AVAILABLE؛ استخدم DAMAGED."
                            ),
                        )

'''
    src = replace_once(
        src,
        expiry_discovered_block,
        "",
        "warehouse discovered expired stock remains countable",
    )

    return src


def patch_driver(src: str) -> str:
    return replace_once(
        src,
        '            if normalized_status not in {"AVAILABLE", "DAMAGED"}:\n'
        '                raise RuntimeError("Vehicle opening inventory has unsupported stock_status.")\n',
        '            if normalized_status not in {\n'
        '                "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED",\n'
        '                "DAMAGED", "DISPOSAL_PENDING",\n'
        '            }:\n'
        '                raise RuntimeError("Vehicle opening inventory has unsupported stock_status.")\n',
        "driver opening snapshot all statuses",
    )


def patch_reconciliation(src: str) -> str:
    src = replace_once(
        src,
        "- يقارن العد الفعلي التجميعي مع إجمالي on_hand (AVAILABLE + DAMAGED) للسيارة.\n",
        "- يقارن العد الفعلي التجميعي مع إجمالي on_hand لكل Portion stock statuses في السيارة.\n",
        "reconciliation doc contract",
    )
    src = replace_once(
        src,
        '                    InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),\n',
        "",
        "reconciliation counts all physical statuses",
    )
    return src


def validate_semantics(files: dict[str, str], migration: str) -> None:
    for name, content in files.items():
        try:
            ast.parse(content)
        except SyntaxError as exc:
            abort(f"AST failed for {name}: {exc}")

    try:
        ast.parse(migration)
    except SyntaxError as exc:
        abort(f"AST failed for generated migration: {exc}")

    services = files["wa_backend/services.py"]
    warehouse = files["wa_backend/api/warehouse.py"]
    models = files["wa_backend/models.py"]
    schemas = files["wa_backend/schemas.py"]
    access = files["wa_backend/inventory_access.py"]
    driver = files["wa_backend/api/driver.py"]
    recon = files["wa_backend/api/reconciliation.py"]

    require_tokens(
        services,
        [
            "_INVENTORY_STOCK_STATUSES",
            "_PORTION_STATUS_TRANSITIONS",
            "_BATCH_DISPOSITION_TRANSITIONS",
            "class InventoryRuleError",
            "async def change_product_batch_disposition(",
            "BATCH_NOT_RELEASED",
            "SHELF_LIFE_POLICY_BLOCKED",
            "record_domain_event(",
        ],
        "services post-validation",
    )
    require_tokens(
        warehouse,
        [
            "/warehouse/batches/{batch_id}/disposition",
            "/warehouse/inventory/status-change",
            "warehouse_blocked_status_subq",
            "explicit_blocked",
            "BatchDispositionChangeRequest",
            "InventoryStatusChangeRequest",
        ],
        "warehouse post-validation",
    )
    require_tokens(
        models,
        ["chk_inv_bal_nonavailable_not_reserved"],
        "models post-validation",
    )
    if "chk_inv_bal_damaged_not_reserved" in models:
        abort("models still contains legacy damaged-only reservation constraint")

    require_tokens(
        schemas,
        [
            "InventoryStockStatus = Literal[",
            "class BatchDispositionChangeRequest",
            "class InventoryStatusChangeRequest",
            "stock_status: InventoryStockStatus",
        ],
        "schemas post-validation",
    )
    require_tokens(
        access,
        ["'batch.disposition'", "'inventory.status_change'"],
        "inventory_access post-validation",
    )
    require_tokens(
        driver,
        ['"QUARANTINED", "BLOCKED", "RECALLED"'],
        "driver post-validation",
    )
    if 'InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"])' in recon:
        abort("reconciliation still filters custody to AVAILABLE/DAMAGED only")

    require_tokens(
        migration,
        [
            "chk_inv_bal_nonavailable_not_reserved",
            "batch.disposition",
            "inventory.status_change",
            "non-AVAILABLE balance has reserved quantity",
        ],
        "migration post-validation",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = locate_root()
    validate_git_baseline(root)

    paths = {
        "wa_backend/models.py": root / "wa_backend" / "models.py",
        "wa_backend/schemas.py": root / "wa_backend" / "schemas.py",
        "wa_backend/services.py": root / "wa_backend" / "services.py",
        "wa_backend/api/warehouse.py": root / "wa_backend" / "api" / "warehouse.py",
        "wa_backend/inventory_access.py": root / "wa_backend" / "inventory_access.py",
        "wa_backend/api/driver.py": root / "wa_backend" / "api" / "driver.py",
        "wa_backend/api/reconciliation.py": root / "wa_backend" / "api" / "reconciliation.py",
    }
    originals = {name: read(path) for name, path in paths.items()}

    marker_count = sum(MARKER in content for content in originals.values())
    if marker_count:
        abort(
            f"Stage4D marker موجود في {marker_count} ملف/ملفات. "
            "لا تعيد تشغيل نسخة الباتش فوق تطبيق جزئي."
        )

    migration_path = find_generated_migration(root)
    migration_original = read(migration_path)
    revision, down_revision = parse_revision(migration_original)
    if down_revision != EXPECTED_DOWN_REVISION:
        abort(
            f"migration down_revision غير متوقع: {down_revision} "
            f"(expected {EXPECTED_DOWN_REVISION})"
        )
    if "def upgrade" not in migration_original or "def downgrade" not in migration_original:
        abort("migration المولد لا يحتوي upgrade/downgrade.")
    if migration_original.count("pass") < 2:
        abort("migration المولد ليس Skeleton فارغاً؛ لن أكتب فوق migration معدل.")

    patched = dict(originals)
    patched["wa_backend/models.py"] = patch_models(patched["wa_backend/models.py"])
    patched["wa_backend/inventory_access.py"] = patch_inventory_access(
        patched["wa_backend/inventory_access.py"]
    )
    patched["wa_backend/schemas.py"] = patch_schemas(patched["wa_backend/schemas.py"])
    patched["wa_backend/services.py"] = patch_services(patched["wa_backend/services.py"])
    patched["wa_backend/api/warehouse.py"] = patch_warehouse(
        patched["wa_backend/api/warehouse.py"]
    )
    patched["wa_backend/api/driver.py"] = patch_driver(
        patched["wa_backend/api/driver.py"]
    )
    patched["wa_backend/api/reconciliation.py"] = patch_reconciliation(
        patched["wa_backend/api/reconciliation.py"]
    )

    migration_new = build_migration(revision)
    validate_semantics(patched, migration_new)

    if args.check:
        print("STAGE4D_PREFLIGHT_OK")
        print(f"BASELINE_HEAD: {EXPECTED_HEAD}")
        print(f"MIGRATION: {migration_path.relative_to(root)}")
        print(
            "FILES_TO_CHANGE: models.py + schemas.py + services.py + "
            "api/warehouse.py + inventory_access.py + api/driver.py + "
            "api/reconciliation.py + generated migration"
        )
        return

    backup_dir = root / ".patch_backups" / MARKER
    if backup_dir.exists():
        abort(f"backup directory already exists: {backup_dir}")
    backup_dir.mkdir(parents=True, exist_ok=False)

    for name, path in paths.items():
        target = backup_dir / name.replace("/", "__")
        shutil.copy2(path, target)
    shutil.copy2(
        migration_path,
        backup_dir / f"migration__{migration_path.name}.before",
    )

    for name, content in patched.items():
        paths[name].write_text(content, encoding="utf-8", newline="\n")
    migration_path.write_text(migration_new, encoding="utf-8", newline="\n")

    print("STAGE4D_BATCH_DISPOSITION_PORTION_STATUS_OK")
    print("BATCH_DISPOSITION_OK: revisioned + audited + outbox + row-lock + conservative transitions")
    print("PORTION_STATUS_OK: all six statuses flow through Unified Inventory Movement Engine")
    print("RELEASE_GATE_OK: AVAILABLE release rechecks Recall + disposition + expiry + shelf-life synchronously")
    print("RESERVATION_OK: non-AVAILABLE buckets are DB-enforced at reserved_quantity=0")
    print("STOCKTAKE_OK: all physical buckets remain countable; expiry is not rewritten to DAMAGED")
    print("VEHICLE_RECON_OK: opening/reconciliation snapshots include every portion status")
    print("LIVE_STOCK_OK: quarantine/blocked/recalled/disposal-pending remain physically visible")
    print("PERMISSIONS_OK: company-wide batch.disposition + location-scoped inventory.status_change")
    print(f"MIGRATION_READY: {migration_path.relative_to(root)}")
    print("NEXT: run py_compile, then alembic upgrade head; do not commit yet.")


if __name__ == "__main__":
    main()
