from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
from pathlib import Path

PATCH_ID = "STAGE4E_CORE_PURPOSE_INFLIGHT"
EXPECTED_HEAD = "da8e18e900f33911f538705e0af617e1407aafc6"
EXPECTED_DOWN_REVISION = "19c740dc40e8"

TARGET_FILES = (
    "wa_backend/models.py",
    "wa_backend/schemas.py",
    "wa_backend/services.py",
    "wa_backend/api/warehouse.py",
    "wa_backend/api/dispatch.py",
    "wa_backend/api/driver.py",
)


def abort(message: str) -> None:
    raise SystemExit(f"PATCH_ABORT: {message}")


def root_dir() -> Path:
    root = Path.cwd()
    if not (root / ".git").is_dir():
        abort("شغّل الباتش من جذر المشروع الذي يحتوي .git.")
    if not (root / "wa_backend" / "models.py").is_file():
        abort("wa_backend/models.py غير موجود؛ لست في جذر مشروع wanasah الصحيح.")
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


def validate_git_baseline(root: Path) -> None:
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    if head != EXPECTED_HEAD:
        abort(
            "HEAD لا يطابق dev inv 8 المدقق. "
            f"expected={EXPECTED_HEAD}, actual={head}"
        )
    if git(root, "diff", "--quiet", check=False).returncode != 0:
        abort("tracked working tree ليس نظيفاً. لا تطبق 4E فوق تعديلات tracked أخرى.")
    if git(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        abort("staged index ليس نظيفاً. لا تطبق 4E فوق تعديلات staged.")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        abort(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def replace_between(
    text: str,
    start: str,
    end: str,
    replacement: str,
    label: str,
) -> str:
    if text.count(start) != 1:
        abort(f"{label}: start anchor count={text.count(start)}")
    if text.count(end) != 1:
        abort(f"{label}: end anchor count={text.count(end)}")
    start_at = text.index(start)
    end_at = text.index(end, start_at)
    return text[:start_at] + replacement + text[end_at:]


def require(text: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        abort(f"{label}: missing expected markers: {missing}")


def find_empty_migration(root: Path) -> Path:
    versions = root / "wa_backend" / "alembic" / "versions"
    candidates = []
    for path in versions.glob("*.py"):
        text = read(path)
        if not re.search(
            rf"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']{EXPECTED_DOWN_REVISION}[\"']",
            text,
            re.MULTILINE,
        ):
            continue
        revision_match = re.search(
            r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']",
            text,
            re.MULTILINE,
        )
        if not revision_match:
            continue
        # Only an untouched Alembic skeleton is accepted.
        if text.count("pass") < 2:
            continue
        candidates.append(path)

    if len(candidates) != 1:
        abort(
            "أنشئ Alembic migration فارغة لـ Stage 4E أولاً. "
            f"Expected exactly one empty migration with down_revision={EXPECTED_DOWN_REVISION}; "
            f"found {len(candidates)}."
        )
    return candidates[0]


def parse_revision(path: Path) -> str:
    text = read(path)
    match = re.search(
        r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']",
        text,
        re.MULTILINE,
    )
    if not match:
        abort("تعذر استخراج revision من migration الجديدة.")
    return match.group(1)


def validate_constructor_surface(root: Path) -> None:
    header_hits = []
    line_hits = []
    for path in (root / "wa_backend").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        text = read(path)
        if "alembic/versions/" in rel:
            continue
        count_h = text.count("InventoryTransferHeader(")
        count_l = text.count("InventoryTransferLine(")
        if count_h:
            header_hits.append((rel, count_h))
        if count_l:
            line_hits.append((rel, count_l))

    expected_headers = [
        ("wa_backend/api/dispatch.py", 1),
        ("wa_backend/api/warehouse.py", 1),
    ]
    expected_lines = [
        ("wa_backend/api/dispatch.py", 1),
        ("wa_backend/api/warehouse.py", 1),
    ]
    if sorted(header_hits) != sorted(expected_headers):
        abort(
            "تم اكتشاف InventoryTransferHeader constructor غير مدقق. "
            f"actual={header_hits}"
        )
    if sorted(line_hits) != sorted(expected_lines):
        abort(
            "تم اكتشاف InventoryTransferLine constructor غير مدقق. "
            f"actual={line_hits}"
        )


def build_migration(revision: str) -> str:
    return f'''"""stage4e explicit transfer purpose and in-flight context

Revision ID: {revision}
Revises: {EXPECTED_DOWN_REVISION}
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "{revision}"
down_revision: Union[str, Sequence[str], None] = "{EXPECTED_DOWN_REVISION}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Development baseline is intentionally strict: creation-time lifecycle evidence
    # cannot be reconstructed truthfully for historical transfer rows.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM inventory_transfer_headers LIMIT 1) THEN
                RAISE EXCEPTION
                    'Stage4E requires empty transfer tables; reset development/demo transfer data before migration';
            END IF;
        END
        $$;
        """
    )

    op.alter_column(
        "inventory_transfer_headers",
        "transfer_purpose",
        existing_type=sa.String(length=50),
        nullable=False,
        server_default=None,
    )
    op.add_column(
        "inventory_transfer_headers",
        sa.Column(
            "commercial_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )

    op.add_column(
        "inventory_transfer_lines",
        sa.Column("source_stock_status", sa.String(length=50), nullable=False),
    )
    op.add_column(
        "inventory_transfer_lines",
        sa.Column("lifecycle_revision_snapshot", sa.Integer(), nullable=False),
    )
    op.add_column(
        "inventory_transfer_lines",
        sa.Column("lifecycle_status_snapshot", sa.String(length=20), nullable=False),
    )
    op.add_column(
        "inventory_transfer_lines",
        sa.Column("operational_hold_snapshot", sa.String(length=20), nullable=False),
    )

    op.create_check_constraint(
        "chk_transfer_line_source_status",
        "inventory_transfer_lines",
        "source_stock_status IN "
        "('AVAILABLE','QUARANTINED','BLOCKED','RECALLED','DAMAGED','DISPOSAL_PENDING')",
    )
    op.create_check_constraint(
        "chk_transfer_line_lifecycle_revision_snapshot",
        "inventory_transfer_lines",
        "lifecycle_revision_snapshot > 0",
    )
    op.create_check_constraint(
        "chk_transfer_line_lifecycle_status_snapshot",
        "inventory_transfer_lines",
        "lifecycle_status_snapshot IN ('DRAFT','ACTIVE','RETIRING','ARCHIVED')",
    )
    op.create_check_constraint(
        "chk_transfer_line_operational_hold_snapshot",
        "inventory_transfer_lines",
        "operational_hold_snapshot IN ('NONE','SALES_HOLD','RECALL')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_transfer_line_operational_hold_snapshot",
        "inventory_transfer_lines",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_line_lifecycle_status_snapshot",
        "inventory_transfer_lines",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_line_lifecycle_revision_snapshot",
        "inventory_transfer_lines",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_line_source_status",
        "inventory_transfer_lines",
        type_="check",
    )

    op.drop_column("inventory_transfer_lines", "operational_hold_snapshot")
    op.drop_column("inventory_transfer_lines", "lifecycle_status_snapshot")
    op.drop_column("inventory_transfer_lines", "lifecycle_revision_snapshot")
    op.drop_column("inventory_transfer_lines", "source_stock_status")
    op.drop_column("inventory_transfer_headers", "commercial_context")

    op.alter_column(
        "inventory_transfer_headers",
        "transfer_purpose",
        existing_type=sa.String(length=50),
        nullable=False,
        server_default=sa.text("'WAREHOUSE_BALANCING'"),
    )
'''


def patch_models(src: str) -> str:
    old = """    workflow_type           = Column(String(30), nullable=False, default='TRANSIT', server_default='TRANSIT', index=True)
    status                  = Column(String(50), nullable=False, default='DRAFT', server_default='DRAFT', index=True)
    transfer_purpose        = Column(String(50), nullable=False, default='WAREHOUSE_BALANCING', server_default='WAREHOUSE_BALANCING', index=True)

    work_session_id      = Column(Integer, nullable=True, index=True)
"""
    new = """    workflow_type           = Column(String(30), nullable=False, default='TRANSIT', server_default='TRANSIT', index=True)
    status                  = Column(String(50), nullable=False, default='DRAFT', server_default='DRAFT', index=True)
    # STAGE4E_CORE_PURPOSE_INFLIGHT: purpose is mandatory at every constructor; no silent fallback.
    transfer_purpose        = Column(String(50), nullable=False, index=True)
    commercial_context      = Column(JSONB, nullable=False)

    work_session_id      = Column(Integer, nullable=True, index=True)
"""
    src = replace_once(src, old, new, "models explicit purpose + context")

    old_args = """        CheckConstraint('quantity > 0', name='chk_transfer_line_qty'),
        CheckConstraint("((fefo_override_reason_id IS NULL AND fefo_overridden_by IS NULL) OR (fefo_override_reason_id IS NOT NULL AND fefo_overridden_by IS NOT NULL))", name='chk_transfer_line_fefo_override_pair'),
    )
"""
    new_args = """        CheckConstraint('quantity > 0', name='chk_transfer_line_qty'),
        CheckConstraint("((fefo_override_reason_id IS NULL AND fefo_overridden_by IS NULL) OR (fefo_override_reason_id IS NOT NULL AND fefo_overridden_by IS NOT NULL))", name='chk_transfer_line_fefo_override_pair'),
        CheckConstraint(
            "source_stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')",
            name='chk_transfer_line_source_status'
        ),
        CheckConstraint(
            'lifecycle_revision_snapshot > 0',
            name='chk_transfer_line_lifecycle_revision_snapshot'
        ),
        CheckConstraint(
            "lifecycle_status_snapshot IN ('DRAFT', 'ACTIVE', 'RETIRING', 'ARCHIVED')",
            name='chk_transfer_line_lifecycle_status_snapshot'
        ),
        CheckConstraint(
            "operational_hold_snapshot IN ('NONE', 'SALES_HOLD', 'RECALL')",
            name='chk_transfer_line_operational_hold_snapshot'
        ),
    )
"""
    src = replace_once(src, old_args, new_args, "models transfer line checks")

    old_cols = """    batch_id                = Column(Integer, nullable=False, index=True)
    quantity                = Column(Numeric(20, 6), nullable=False)
    fefo_override_reason_id = Column(Integer, nullable=True)
"""
    new_cols = """    batch_id                = Column(Integer, nullable=False, index=True)
    quantity                = Column(Numeric(20, 6), nullable=False)
    source_stock_status     = Column(String(50), nullable=False)
    lifecycle_revision_snapshot = Column(Integer, nullable=False)
    lifecycle_status_snapshot   = Column(String(20), nullable=False)
    operational_hold_snapshot   = Column(String(20), nullable=False)
    fefo_override_reason_id = Column(Integer, nullable=True)
"""
    return replace_once(src, old_cols, new_cols, "models transfer line snapshots")


def patch_schemas(src: str) -> str:
    stock_alias = """InventoryStockStatus = Literal[
    "AVAILABLE",
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
    "DAMAGED",
    "DISPOSAL_PENDING",
]
"""
    purpose_alias = stock_alias + """

TransferPurpose = Literal[
    "REPLENISHMENT",
    "ROUTE_LOAD",
    "ROUTE_RETURN",
    "WAREHOUSE_BALANCING",
    "RETURN_TO_VENDOR",
    "QUARANTINE",
    "RECALL_RETURN",
    "DISPOSAL",
]
"""
    src = replace_once(
        src, stock_alias, purpose_alias,
        "schemas TransferPurpose alias",
    )

    src = replace_once(
        src,
        """class UnifiedDispatchRequest(RequestModel):
    request_id: UUID
    source_location_id: PositiveDbInt
    destination_location_id: PositiveDbInt
    items: List[UnifiedTransferItem] = Field(..., min_length=1, max_length=5000)
""",
        """class UnifiedDispatchRequest(RequestModel):
    request_id: UUID
    source_location_id: PositiveDbInt
    destination_location_id: PositiveDbInt
    transfer_purpose: TransferPurpose
    items: List[UnifiedTransferItem] = Field(..., min_length=1, max_length=5000)
""",
        "schemas dispatch purpose required",
    )

    src = replace_once(
        src,
        """    destination_location_id: int
    destination_location_name: str
    status: str
    dispatched_by: int
""",
        """    destination_location_id: int
    destination_location_name: str
    transfer_purpose: TransferPurpose
    status: str
    dispatched_by: int
""",
        "schemas transfer list purpose",
    )

    src = replace_once(
        src,
        """class UnifiedTransferSourceBatchItem(BaseModel):
    id: int
    batch_number: str
    production_date: Optional[date] = None
    expiry_date: date
""",
        """class UnifiedTransferSourceBatchItem(BaseModel):
    id: int
    batch_number: str
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
""",
        "schemas nullable override expiry",
    )
    src = replace_once(
        src,
        """class WarehouseTransferLineItem(BaseModel):
    id: int
    product_variant_id: int
    product_name: str
    batch_id: int
    batch_number: str
    expiry_date: date
""",
        """class WarehouseTransferLineItem(BaseModel):
    id: int
    product_variant_id: int
    product_name: str
    batch_id: int
    batch_number: str
    expiry_date: Optional[date] = None
""",
        "schemas nullable transfer expiry",
    )
    src = replace_once(
        src,
        """class StocktakeCycleBatchItem(BaseModel):
    id: int
    product_variant_id: int
    batch_number: str
    production_date: Optional[date] = None
    expiry_date: date
""",
        """class StocktakeCycleBatchItem(BaseModel):
    id: int
    product_variant_id: int
    batch_number: str
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
""",
        "schemas nullable stocktake expiry",
    )
    return src


SERVICE_RESOLVER = r'''
# STAGE4E_CORE_PURPOSE_INFLIGHT
_TRANSFER_TERMINAL_REFERENCE_TYPES = frozenset({
    "TRANSFER_RECEIPT",
    "TRANSFER_CANCELLED",
    "TRANSFER_REJECTED",
    "TRANSFER_TERMINAL_STATUS",
    "HANDSHAKE_POST",
    "HANDSHAKE_RELEASE",
    "HANDSHAKE_TERMINAL_STATUS",
})

_TRANSFER_PURPOSES = frozenset({
    "REPLENISHMENT",
    "ROUTE_LOAD",
    "ROUTE_RETURN",
    "WAREHOUSE_BALANCING",
    "RETURN_TO_VENDOR",
    "QUARANTINE",
    "RECALL_RETURN",
    "DISPOSAL",
})


async def resolve_inflight_transfer_destination_statuses(
    db_session: AsyncSession,
    *,
    company_id: int,
    destination_location_id: int,
    transfer_purpose: str,
    lines: List[Any],
) -> Dict[int, str]:
    """Resolve safe terminal portion status from creation evidence + current state.

    This never chooses a warehouse and never mutates InventoryBalance.  It only
    returns the destination bucket for each immutable transfer line.  Physical
    and status movements remain the responsibility of the Unified Engine.
    """
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        destination_location_id = _strict_int(
            destination_location_id,
            "destination_location_id",
            minimum=1,
        )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    purpose = str(transfer_purpose or "").strip().upper()
    if purpose not in _TRANSFER_PURPOSES:
        raise InventoryRuleError(
            "TRANSFER_PURPOSE_INVALID",
            "غرض الحوالة غير صالح.",
            context={"transfer_purpose": purpose},
        )
    if not lines:
        raise InventoryMutationError("الحوالة لا تحتوي أسطر مخزون.")

    line_ids = set()
    batch_keys = set()
    variant_ids = set()
    for line in lines:
        line_id = _strict_int(getattr(line, "id", None), "transfer_line_id", minimum=1)
        if line_id in line_ids:
            raise InventoryMutationError("تكرار transfer line داخل قرار الإكمال.")
        line_ids.add(line_id)

        variant_id = _strict_int(
            getattr(line, "product_variant_id", None),
            "product_variant_id",
            minimum=1,
        )
        batch_id = _strict_int(getattr(line, "batch_id", None), "batch_id", minimum=1)
        revision = _strict_int(
            getattr(line, "lifecycle_revision_snapshot", None),
            "lifecycle_revision_snapshot",
            minimum=1,
        )
        _ = revision

        source_status = str(
            getattr(line, "source_stock_status", "") or ""
        ).strip().upper()
        creation_lifecycle = str(
            getattr(line, "lifecycle_status_snapshot", "") or ""
        ).strip().upper()
        creation_hold = str(
            getattr(line, "operational_hold_snapshot", "") or ""
        ).strip().upper()

        if source_status not in _INVENTORY_STOCK_STATUSES:
            raise InventoryMutationError("transfer line يحمل source_stock_status غير صالح.")
        if creation_lifecycle not in {"DRAFT", "ACTIVE", "RETIRING", "ARCHIVED"}:
            raise InventoryMutationError("transfer line يحمل lifecycle snapshot غير صالح.")
        if creation_hold not in {"NONE", "SALES_HOLD", "RECALL"}:
            raise InventoryMutationError("transfer line يحمل hold snapshot غير صالح.")
        # Valid new documents cannot start in DRAFT/ARCHIVED.  Do not fabricate
        # creation evidence if corrupted rows somehow appear.
        if creation_lifecycle in {"DRAFT", "ARCHIVED"}:
            raise InventoryMutationError(
                "Creation lifecycle snapshot غير صالح لمستند تحويل بدأ تشغيلياً."
            )

        variant_ids.add(variant_id)
        batch_keys.add((variant_id, batch_id))

    await acquire_product_lifecycle_guards(
        db_session,
        company_id,
        sorted(variant_ids),
        exclusive=False,
    )
    as_of_date = await get_company_local_date(db_session, company_id)

    rows = (
        await db_session.execute(
            select(
                ProductBatch.product_variant_id.label("variant_id"),
                ProductBatch.id.label("batch_id"),
                ProductBatch.is_active.label("batch_is_active"),
                ProductBatch.disposition.label("batch_disposition"),
                ProductBatch.production_date,
                ProductBatch.expiry_date,
                ProductVariant.lifecycle_status.label("current_lifecycle_status"),
                ProductVariant.operational_hold.label("current_operational_hold"),
                ProductVariant.lifecycle_revision.label("current_lifecycle_revision"),
                ProductVariant.expiry_control_mode,
                InventoryStockPolicy.minimum_remaining_shelf_life_days,
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == ProductBatch.company_id,
                    ProductVariant.id == ProductBatch.product_variant_id,
                ),
            )
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id == ProductBatch.company_id,
                    InventoryStockPolicy.location_id == destination_location_id,
                    InventoryStockPolicy.product_variant_id
                    == ProductBatch.product_variant_id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .filter(
                ProductBatch.company_id == company_id,
                tuple_(
                    ProductBatch.product_variant_id,
                    ProductBatch.id,
                ).in_(sorted(batch_keys)),
            )
            .order_by(
                ProductBatch.product_variant_id.asc(),
                ProductBatch.id.asc(),
            )
            .with_for_update(read=True, of=ProductBatch)
        )
    ).all()

    current = {
        (int(row.variant_id), int(row.batch_id)): row
        for row in rows
    }
    if set(current) != set(batch_keys):
        raise InventoryMutationError(
            "إحدى دفعات مستند التحويل مفقودة أو لا تتبع الشركة/الصنف."
        )

    result: Dict[int, str] = {}
    for line in lines:
        variant_id = int(line.product_variant_id)
        batch_id = int(line.batch_id)
        row = current[(variant_id, batch_id)]

        current_revision = int(row.current_lifecycle_revision)
        creation_revision = int(line.lifecycle_revision_snapshot)
        if current_revision < creation_revision:
            raise InventoryMutationError(
                "lifecycle_revision الحالي أقدم من Snapshot إنشاء الحوالة."
            )

        lifecycle = str(row.current_lifecycle_status or "").upper()
        hold = str(row.current_operational_hold or "").upper()
        disposition = str(row.batch_disposition or "").upper()

        if lifecycle not in {"DRAFT", "ACTIVE", "RETIRING", "ARCHIVED"}:
            raise InventoryMutationError("حالة Lifecycle الحالية غير صالحة.")
        if hold not in {"NONE", "SALES_HOLD", "RECALL"}:
            raise InventoryMutationError("حالة Hold الحالية غير صالحة.")
        if disposition not in _BATCH_DISPOSITIONS:
            raise InventoryMutationError("Batch disposition الحالي غير صالح.")
        if lifecycle == "DRAFT":
            # A valid started document can never return to DRAFT through the FSM.
            raise InventoryMutationError(
                "تم اكتشاف رجوع Lifecycle إلى DRAFT بعد بدء مستند التحويل."
            )

        min_days = int(row.minimum_remaining_shelf_life_days or 0)
        metadata_sellable = _batch_metadata_is_sellable(
            as_of_date=as_of_date,
            expiry_control_mode=str(row.expiry_control_mode),
            production_date=row.production_date,
            expiry_date=row.expiry_date,
            minimum_remaining_shelf_life_days=min_days,
        )

        # Safety precedence is deterministic and fail-closed.
        if hold == "RECALL" or disposition == "RECALLED":
            final_status = "RECALLED"
        elif disposition == "BLOCKED":
            final_status = "BLOCKED"
        elif (
            hold == "SALES_HOLD"
            or disposition == "QUARANTINED"
            or not bool(row.batch_is_active)
            or lifecycle == "ARCHIVED"
            or not metadata_sellable
        ):
            final_status = "QUARANTINED"
        else:
            final_status = "AVAILABLE"

        result[int(line.id)] = final_status

    return result

'''


def patch_services(src: str) -> str:
    # Insert resolver immediately after the Stage4C metadata evaluator.
    anchor = "\n\n# تثبيت أن VEHICLE_RECON مرتبط بجلسة عمل منتهية وغير مسواة وبنفس السيارة داخل Tenant واحد.\n"
    src = replace_once(
        src,
        anchor,
        "\n\n" + SERVICE_RESOLVER + anchor.lstrip("\n"),
        "services inflight resolver insertion",
    )

    old = '''        for spec in new_specs:
            scale, step, lifecycle_status, _operational_hold, _expiry_mode = variant_rules[spec["product_variant_id"]]
            if lifecycle_status in {"DRAFT", "ARCHIVED"}:
                raise InventoryMutationError(
                    f"الصنف ({spec['product_variant_id']}) بحالة {lifecycle_status} ولا يقبل حركة مخزون جديدة."
                )
            spec["quantity"] = validate_variant_quantity(
'''
    new = '''        for spec in new_specs:
            scale, step, lifecycle_status, _operational_hold, _expiry_mode = variant_rules[spec["product_variant_id"]]
            if lifecycle_status == "DRAFT":
                raise InventoryMutationError(
                    f"الصنف ({spec['product_variant_id']}) بحالة DRAFT ولا يقبل حركة مخزون."
                )
            if lifecycle_status == "ARCHIVED" and not (
                spec["transfer_header_id"] is not None
                and spec["reference_type"] in _TRANSFER_TERMINAL_REFERENCE_TYPES
            ):
                raise InventoryMutationError(
                    f"الصنف ({spec['product_variant_id']}) بحالة ARCHIVED ولا يقبل حركة جديدة؛ "
                    "المسموح فقط إنهاء مستند تحويل بدأ سابقاً."
                )
            spec["quantity"] = validate_variant_quantity(
'''
    return replace_once(
        src, old, new,
        "services archived in-flight terminal exception",
    )


def patch_warehouse(src: str) -> str:
    src = replace_once(
        src,
        """    allocate_fefo_inventory_batch,
    batch_sellability_predicate,
    get_company_local_date,
""",
        """    allocate_fefo_inventory_batch,
    batch_sellability_predicate,
    resolve_inflight_transfer_destination_statuses,
    get_company_local_date,
""",
        "warehouse resolver import",
    )
    src = replace_once(
        src,
        """    INBOUND_NEW,
    WAREHOUSE_BALANCING,
""",
        """    INBOUND_NEW,
    REPLENISHMENT_NEW,
    WAREHOUSE_BALANCING,
""",
        "warehouse replenishment capability import",
    )

    # Serialize purpose explicitly.
    src = replace_once(
        src,
        '''            "destination_location_id": int(header.destination_location_id),
            "destination_location_name": location_map[int(header.destination_location_id)],
            "status": str(header.status),
''',
        '''            "destination_location_id": int(header.destination_location_id),
            "destination_location_name": location_map[int(header.destination_location_id)],
            "transfer_purpose": str(header.transfer_purpose),
            "status": str(header.status),
''',
        "warehouse transfer serialization purpose",
    )

    dispatch_anchor = '@router.post("/warehouse/unified/transfer/dispatch", status_code=200)\n'
    purpose_block = '''# Stage 4E generic TRANSIT endpoint intentionally owns only the two unambiguous
# warehouse-to-warehouse purposes. Route load/return stay in Dispatch workflows.
# Special return/quarantine/disposal purposes remain fail-closed until their
# tenant-configured destination capability is approved and represented explicitly.
_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {
    "REPLENISHMENT": REPLENISHMENT_NEW,
    "WAREHOUSE_BALANCING": WAREHOUSE_BALANCING,
}


'''
    src = replace_once(
        src,
        dispatch_anchor,
        purpose_block + dispatch_anchor,
        "warehouse purpose capability map",
    )

    # Validate explicit purpose + direction after current location types are loaded.
    old = '''        location_types = dict((await db.execute(
            select(InventoryLocation.id, InventoryLocation.location_type).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id.in_([payload.source_location_id, payload.destination_location_id]),
            )
        )).all())
        variant_uom_rows = (
'''
    new = '''        location_types = dict((await db.execute(
            select(InventoryLocation.id, InventoryLocation.location_type).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id.in_([payload.source_location_id, payload.destination_location_id]),
            )
        )).all())

        transfer_purpose = str(payload.transfer_purpose).upper()
        lifecycle_capability = _GENERIC_TRANSFER_PURPOSE_CAPABILITY.get(
            transfer_purpose
        )
        if lifecycle_capability is None:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "TRANSFER_PURPOSE_WORKFLOW_REQUIRED",
                    "غرض الحوالة المطلوب يحتاج Workflow واتجاهاً مخصصاً ولا يجوز تمريره عبر الحوالة العامة.",
                    context={"transfer_purpose": transfer_purpose},
                ),
            )

        source_type = location_types.get(payload.source_location_id)
        destination_type = location_types.get(payload.destination_location_id)
        if source_type != "WAREHOUSE" or destination_type != "WAREHOUSE":
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "TRANSFER_DIRECTION_BLOCKED",
                    "REPLENISHMENT/WAREHOUSE_BALANCING في المسار العام يتطلبان WAREHOUSE -> WAREHOUSE.",
                    context={
                        "transfer_purpose": transfer_purpose,
                        "source_location_type": source_type,
                        "destination_location_type": destination_type,
                    },
                ),
            )

        variant_uom_rows = (
'''
    src = replace_once(
        src, old, new,
        "warehouse explicit purpose/direction validation",
    )

    old = '''                select(
                    ProductVariant.id,
                    ProductVariant.base_uom_id,
                    ProductVariant.lifecycle_status,
                    ProductVariant.operational_hold,
                ).filter(
'''
    new = '''                select(
                    ProductVariant.id,
                    ProductVariant.base_uom_id,
                    ProductVariant.lifecycle_status,
                    ProductVariant.operational_hold,
                    ProductVariant.lifecycle_revision,
                ).filter(
'''
    src = replace_once(
        src, old, new,
        "warehouse variant lifecycle revision selection",
    )

    old = '''        variant_uoms = {}
        for row in variant_uom_rows:
            decision = evaluate_product_capability(
                row.lifecycle_status,
                row.operational_hold,
                WAREHOUSE_BALANCING,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={"code": decision.code, "message": "حالة الصنف لا تسمح بحوالة جديدة.", "context": {"product_variant_id": int(row.id)}},
                )
            variant_uoms[int(row.id)] = int(row.base_uom_id)
        if set(variant_uoms) != requested_variant_ids:
'''
    new = '''        variant_uoms = {}
        variant_context = {}
        for row in variant_uom_rows:
            decision = evaluate_product_capability(
                row.lifecycle_status,
                row.operational_hold,
                lifecycle_capability,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={"code": decision.code, "message": "حالة الصنف لا تسمح بالحوالة المطلوبة.", "context": {"product_variant_id": int(row.id), "transfer_purpose": transfer_purpose}},
                )
            variant_uoms[int(row.id)] = int(row.base_uom_id)
            variant_context[int(row.id)] = row
        if set(variant_uoms) != requested_variant_ids:
'''
    src = replace_once(
        src, old, new,
        "warehouse purpose-aware lifecycle evaluation",
    )

    # The source ProductLocation must follow the actual purpose capability.
    src = replace_once(
        src,
        '''                assignments.get((payload.source_location_id, variant_id)),
                WAREHOUSE_BALANCING,
''',
        '''                assignments.get((payload.source_location_id, variant_id)),
                lifecycle_capability,
''',
        "warehouse purpose-aware ProductLocation source",
    )

    old_header = '''        header = InventoryTransferHeader(
            company_id=company_id,
            reference_number=transfer_ref,
            source_location_id=payload.source_location_id,
            destination_location_id=payload.destination_location_id,
            transit_location_id=transit_location_id,
            workflow_type='TRANSIT',
            status='IN_TRANSIT',
            dispatched_by=current_admin.id,
            notes=payload.notes or None
        )
'''
    new_header = '''        header = InventoryTransferHeader(
            company_id=company_id,
            reference_number=transfer_ref,
            source_location_id=payload.source_location_id,
            destination_location_id=payload.destination_location_id,
            transit_location_id=transit_location_id,
            workflow_type='TRANSIT',
            status='IN_TRANSIT',
            transfer_purpose=transfer_purpose,
            commercial_context={
                "schema_version": 1,
                "commercial_context_id": None,
                "tenant_policy_revision": None,
                "source_location_type": source_type,
                "destination_location_type": destination_type,
                "transfer_purpose": transfer_purpose,
            },
            dispatched_by=current_admin.id,
            notes=payload.notes or None
        )
'''
    src = replace_once(
        src, old_header, new_header,
        "warehouse explicit transfer header context",
    )

    old_line = '''                transfer_lines.append(InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=item.product_variant_id,
                    batch_id=batch_id,
                    quantity=take_qty,
                    fefo_override_reason_id=override_reason_id,
'''
    new_line = '''                variant_state = variant_context[int(item.product_variant_id)]
                transfer_lines.append(InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=item.product_variant_id,
                    batch_id=batch_id,
                    quantity=take_qty,
                    source_stock_status="AVAILABLE",
                    lifecycle_revision_snapshot=int(variant_state.lifecycle_revision),
                    lifecycle_status_snapshot=str(variant_state.lifecycle_status),
                    operational_hold_snapshot=str(variant_state.operational_hold),
                    fefo_override_reason_id=override_reason_id,
'''
    src = replace_once(
        src, old_line, new_line,
        "warehouse transfer line creation snapshots",
    )

    # Include purpose in mutation response.
    src = replace_once(
        src,
        '''            "transfer_reference": transfer_ref,
            "header_id": header.id,
        }
''',
        '''            "transfer_reference": transfer_ref,
            "header_id": header.id,
            "transfer_purpose": transfer_purpose,
        }
''',
        "warehouse dispatch response purpose",
    )

    start = '''async def _move_transfer_lines_from_transit(
'''
    end = '''@router.post("/warehouse/unified/transfer/receive", status_code=200)
'''
    replacement = r'''async def _move_transfer_lines_from_transit(
    db: AsyncSession,
    *,
    company_id: int,
    header: InventoryTransferHeader,
    performed_by: int,
    destination_location_id: int,
    reference_type: str,
    idempotency_prefix: str,
    notes: Optional[str]
) -> dict[int, str]:
    """Complete an already-valid TRANSIT document into a current safe terminal bucket."""
    transit_location_id = int(header.transit_location_id)

    await _verify_location_ownership(
        db,
        company_id,
        transit_location_id,
        allowed_types=['IN_TRANSIT']
    )
    await _verify_location_ownership(
        db,
        company_id,
        destination_location_id,
        allowed_types=['WAREHOUSE', 'VEHICLE']
    )

    await acquire_inventory_location_guards(
        db,
        company_id,
        [transit_location_id, destination_location_id],
    )
    await _verify_location_ownership(
        db,
        company_id,
        transit_location_id,
        allowed_types=['IN_TRANSIT'],
    )
    await _verify_location_ownership(
        db,
        company_id,
        destination_location_id,
        allowed_types=['WAREHOUSE', 'VEHICLE'],
    )

    lines = (
        await db.execute(
            select(InventoryTransferLine).filter_by(
                company_id=company_id,
                transfer_header_id=header.id
            ).order_by(
                InventoryTransferLine.product_variant_id.asc(),
                InventoryTransferLine.batch_id.asc(),
                InventoryTransferLine.id.asc()
            ).with_for_update()
        )
    ).scalars().all()

    if not lines:
        raise HTTPException(
            status_code=409,
            detail="الحوالة لا تحتوي على أسطر مخزون صالحة."
        )

    terminal_statuses = await resolve_inflight_transfer_destination_statuses(
        db,
        company_id=company_id,
        destination_location_id=destination_location_id,
        transfer_purpose=str(header.transfer_purpose),
        lines=lines,
    )

    movement_specs = []
    for line in lines:
        source_status = str(line.source_stock_status).upper()
        final_status = terminal_statuses[int(line.id)]

        # PHYSICAL preserves portion status by DB invariant.  Any safety downgrade
        # is a second explicit STATUS_CHANGE through the same Unified Engine.
        movement_specs.append({
            "product_variant_id": line.product_variant_id,
            "batch_id": line.batch_id,
            "quantity": line.quantity,
            "movement_kind": 'PHYSICAL',
            "reference_type": reference_type,
            "reference_id": header.reference_number,
            "idempotency_key": f"{idempotency_prefix}-{header.id}-{line.id}",
            "source_location_id": transit_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": source_status,
            "destination_stock_status": source_status,
            "transfer_header_id": header.id,
            "notes": notes,
        })
        if final_status != source_status:
            movement_specs.append({
                "product_variant_id": line.product_variant_id,
                "batch_id": line.batch_id,
                "quantity": line.quantity,
                "movement_kind": 'STATUS_CHANGE',
                "reference_type": 'TRANSFER_TERMINAL_STATUS',
                "reference_id": header.reference_number,
                "idempotency_key": (
                    f"{idempotency_prefix}-STATUS-{header.id}-{line.id}"
                ),
                "source_location_id": destination_location_id,
                "destination_location_id": destination_location_id,
                "source_stock_status": source_status,
                "destination_stock_status": final_status,
                "transfer_header_id": header.id,
                "notes": (
                    f"Safe terminal status for {header.transfer_purpose}: "
                    f"{source_status}->{final_status}"
                ),
            })

    await apply_inventory_movements_batch(
        db,
        company_id=company_id,
        performed_by=performed_by,
        movements=movement_specs,
    )
    return terminal_statuses


'''
    src = replace_between(
        src, start, end, replacement, "warehouse safe TRANSIT completion",
    )
    return src


def patch_dispatch(src: str) -> str:
    old_header = '''            header = InventoryTransferHeader(
                company_id=company_id,
                reference_number=f"HS-{uuid4().hex.upper()}",
                source_location_id=src,
                destination_location_id=dst,
                workflow_type="HANDSHAKE",
                status="PENDING",
                work_session_id=session.id,
                expected_receiver_id=route.driver_id,
                dispatched_by=admin.id,
                notes=batch_token,
            )
'''
    new_header = '''            transfer_purpose = "ROUTE_LOAD" if delta > 0 else "ROUTE_RETURN"
            source_location_type = "WAREHOUSE" if delta > 0 else "VEHICLE"
            destination_location_type = "VEHICLE" if delta > 0 else "WAREHOUSE"
            header = InventoryTransferHeader(
                company_id=company_id,
                reference_number=f"HS-{uuid4().hex.upper()}",
                source_location_id=src,
                destination_location_id=dst,
                workflow_type="HANDSHAKE",
                status="PENDING",
                transfer_purpose=transfer_purpose,
                commercial_context={
                    "schema_version": 1,
                    "commercial_context_id": None,
                    "tenant_policy_revision": None,
                    "route_id": int(route.id),
                    "work_session_id": int(session.id),
                    "source_location_type": source_location_type,
                    "destination_location_type": destination_location_type,
                    "transfer_purpose": transfer_purpose,
                },
                work_session_id=session.id,
                expected_receiver_id=route.driver_id,
                dispatched_by=admin.id,
                notes=batch_token,
            )
'''
    src = replace_once(
        src, old_header, new_header,
        "dispatch explicit handshake purpose/context",
    )

    old_line = '''                line = InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=pid,
                    batch_id=batch_id,
                    quantity=quantity,
                )
'''
    new_line = '''                line = InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=pid,
                    batch_id=batch_id,
                    quantity=quantity,
                    source_stock_status="AVAILABLE",
                    lifecycle_revision_snapshot=int(variant.lifecycle_revision),
                    lifecycle_status_snapshot=str(variant.lifecycle_status),
                    operational_hold_snapshot=str(variant.operational_hold),
                )
'''
    src = replace_once(
        src, old_line, new_line,
        "dispatch handshake line snapshots",
    )

    # No lossy cast while releasing reserved transfer quantity.
    src = replace_once(
        src,
        '''            "quantity": int(line.quantity),
            "movement_kind": "RESERVATION",
''',
        '''            "quantity": line.quantity,
            "movement_kind": "RESERVATION",
''',
        "dispatch force-cancel Decimal quantity",
    )
    return src


DRIVER_RESOLVE_WRAPPER = r'''async def _resolve_handshake_destination_statuses(
    db: AsyncSession,
    *,
    company_id: int,
    header: InventoryTransferHeader,
    lines,
) -> dict[int, str]:
    return await resolve_inflight_transfer_destination_statuses(
        db,
        company_id=company_id,
        destination_location_id=int(header.destination_location_id),
        transfer_purpose=str(header.transfer_purpose),
        lines=lines,
    )


'''


DRIVER_BUILD_SPECS = r'''def _build_handshake_movement_specs(
    *,
    header: InventoryTransferHeader,
    lines,
    accepted: bool,
    destination_status_by_line: Optional[dict[int, str]] = None,
):
    movement_specs = []
    status_map = destination_status_by_line or {}

    for line in lines:
        quantity = line.quantity
        source_status = str(line.source_stock_status).upper()

        movement_specs.append({
            "product_variant_id": int(line.product_variant_id),
            "batch_id": int(line.batch_id),
            "quantity": quantity,
            "movement_kind": "RESERVATION",
            "reservation_action": "RELEASE",
            "reference_type": "HANDSHAKE_RELEASE",
            "reference_id": str(header.reference_number),
            "idempotency_key": f"HS-REL-{header.id}-{line.id}",
            "source_location_id": int(header.source_location_id),
            "destination_location_id": int(header.source_location_id),
            "source_stock_status": source_status,
            "destination_stock_status": source_status,
            "work_session_id": int(header.work_session_id),
            "transfer_header_id": int(header.id),
            "notes": "تحرير حجز المصافحة بعد قرار المندوب.",
        })

        if not accepted:
            continue

        final_status = status_map.get(int(line.id))
        if final_status is None:
            raise RuntimeError(
                "Accepted handshake missing safe destination status decision."
            )

        movement_specs.append({
            "product_variant_id": int(line.product_variant_id),
            "batch_id": int(line.batch_id),
            "quantity": quantity,
            "movement_kind": "PHYSICAL",
            "reference_type": "HANDSHAKE_POST",
            "reference_id": str(header.reference_number),
            "idempotency_key": f"HS-POST-{header.id}-{line.id}",
            "source_location_id": int(header.source_location_id),
            "destination_location_id": int(header.destination_location_id),
            "source_stock_status": source_status,
            "destination_stock_status": source_status,
            "work_session_id": int(header.work_session_id),
            "transfer_header_id": int(header.id),
            "notes": "ترحيل مصافحة منتصف اليوم بعد موافقة المندوب.",
        })

        if final_status != source_status:
            movement_specs.append({
                "product_variant_id": int(line.product_variant_id),
                "batch_id": int(line.batch_id),
                "quantity": quantity,
                "movement_kind": "STATUS_CHANGE",
                "reference_type": "HANDSHAKE_TERMINAL_STATUS",
                "reference_id": str(header.reference_number),
                "idempotency_key": f"HS-STATUS-{header.id}-{line.id}",
                "source_location_id": int(header.destination_location_id),
                "destination_location_id": int(header.destination_location_id),
                "source_stock_status": source_status,
                "destination_stock_status": final_status,
                "work_session_id": int(header.work_session_id),
                "transfer_header_id": int(header.id),
                "notes": (
                    f"Safe terminal status for {header.transfer_purpose}: "
                    f"{source_status}->{final_status}"
                ),
            })
    return movement_specs


'''


def patch_driver(src: str) -> str:
    src = replace_once(
        src,
        """    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
    begin_idempotent_operation,
""",
        """    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
    resolve_inflight_transfer_destination_statuses,
    begin_idempotent_operation,
""",
        "driver resolver import",
    )
    # Optional is required by the new helper signature.
    src = replace_once(
        src,
        "from typing import List\n",
        "from typing import List, Optional\n",
        "driver Optional import",
    )

    # Replace the old partial batch validator with the central safe resolver wrapper.
    start = '''async def _validate_incoming_handshake_batches(
'''
    end = '''def _handshake_signed_quantity(
'''
    src = replace_between(
        src,
        start,
        end,
        DRIVER_RESOLVE_WRAPPER,
        "driver centralize handshake eligibility",
    )

    # Replace movement builder.
    start = '''def _build_handshake_movement_specs(
'''
    end = '''# =========================================
# 5. جلب بيانات الداشبورد للمندوب
'''
    src = replace_between(
        src,
        start,
        end,
        DRIVER_BUILD_SPECS,
        "driver safe handshake movement builder",
    )

    # Single accept: keep started-document lifecycle check for incoming route load,
    # then resolve current batch/hold/status for every accepted direction.
    old_single = '''        # الاستلام AVAILABLE إلى السيارة يحتاج صنفاً وBatch صالحين لحظة القبول.
        # هذا لا يغيّر مسار المرتجعات: VisitReturn يدخل DAMAGED فوراً حتى لو منتهي/موقوف.
        if response == "accepted" and int(header.destination_location_id) == vehicle_location_id:
            receipt_capability = evaluate_product_capability(
                variant.lifecycle_status,
                variant.operational_hold,
                INBOUND_COMPLETE,
                document_started=True,
            )
            if not receipt_capability.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": receipt_capability.code,
                        "message": f"لا يمكن إنهاء استلام المنتج ({variant.variant_name}) في حالته الحالية.",
                    },
                )
            as_of_date = await get_company_local_date(db, company_id)
            await _validate_incoming_handshake_batches(
                db,
                company_id=company_id,
                header=header,
                lines=lines,
                vehicle_location_id=vehicle_location_id,
                as_of_date=as_of_date,
            )

        movement_specs = _build_handshake_movement_specs(
            header=header,
            lines=lines,
            accepted=(response == "accepted"),
        )
'''
    new_single = '''        # مستند بدأ صحيحاً لا يُعلق عند RETIRING/Hold/Recall. عند القبول
        # نعيد تقييم الحالة الحالية ونستلم إلى Bucket آمن غير قابل للبيع عند الحاجة.
        if response == "accepted" and int(header.destination_location_id) == vehicle_location_id:
            receipt_capability = evaluate_product_capability(
                variant.lifecycle_status,
                variant.operational_hold,
                INBOUND_COMPLETE,
                document_started=True,
            )
            if not receipt_capability.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": receipt_capability.code,
                        "message": f"لا يمكن إنهاء استلام المنتج ({variant.variant_name}) في حالته الحالية.",
                    },
                )

        destination_status_by_line = {}
        if response == "accepted":
            destination_status_by_line = await _resolve_handshake_destination_statuses(
                db,
                company_id=company_id,
                header=header,
                lines=lines,
            )

        movement_specs = _build_handshake_movement_specs(
            header=header,
            lines=lines,
            accepted=(response == "accepted"),
            destination_status_by_line=destination_status_by_line,
        )
'''
    src = replace_once(
        src, old_single, new_single,
        "driver single handshake safe completion",
    )

    # Batch accept loop.
    old_batch = '''                if accepted and int(header.destination_location_id) == vehicle_location_id:
                    receipt_capability = evaluate_product_capability(
                        variant.lifecycle_status,
                        variant.operational_hold,
                        INBOUND_COMPLETE,
                        document_started=True,
                    )
                    if not receipt_capability.allowed:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": receipt_capability.code,
                                "message": f"لا يمكن إنهاء استلام المنتج ({variant.variant_name}) في الحوالة ({header.id}).",
                            },
                        )
                    await _validate_incoming_handshake_batches(
                        db,
                        company_id=company_id,
                        header=header,
                        lines=lines,
                        vehicle_location_id=vehicle_location_id,
                        as_of_date=as_of_date,
                    )

                movement_specs.extend(
                    _build_handshake_movement_specs(
                        header=header,
                        lines=lines,
                        accepted=accepted,
                    )
                )
'''
    new_batch = '''                if accepted and int(header.destination_location_id) == vehicle_location_id:
                    receipt_capability = evaluate_product_capability(
                        variant.lifecycle_status,
                        variant.operational_hold,
                        INBOUND_COMPLETE,
                        document_started=True,
                    )
                    if not receipt_capability.allowed:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": receipt_capability.code,
                                "message": f"لا يمكن إنهاء استلام المنتج ({variant.variant_name}) في الحوالة ({header.id}).",
                            },
                        )

                destination_status_by_line = {}
                if accepted:
                    destination_status_by_line = await _resolve_handshake_destination_statuses(
                        db,
                        company_id=company_id,
                        header=header,
                        lines=lines,
                    )

                movement_specs.extend(
                    _build_handshake_movement_specs(
                        header=header,
                        lines=lines,
                        accepted=accepted,
                        destination_status_by_line=destination_status_by_line,
                    )
                )
'''
    src = replace_once(
        src, old_batch, new_batch,
        "driver batch handshake safe completion",
    )

    # The old as_of_date block is now obsolete; central resolver owns company-local date.
    old_asof = '''            as_of_date = (
                await get_company_local_date(db, company_id)
                if accepted_headers
                else None
            )
'''
    src = replace_once(src, old_asof, "", "driver remove duplicate as_of resolver")

    return src


def validate_post(files: dict[str, str], migration_text: str) -> None:
    for name, content in files.items():
        try:
            ast.parse(content)
        except SyntaxError as exc:
            abort(f"AST validation failed for {name}: {exc}")
    try:
        ast.parse(migration_text)
    except SyntaxError as exc:
        abort(f"AST validation failed for migration: {exc}")

    models = files["wa_backend/models.py"]
    schemas = files["wa_backend/schemas.py"]
    services = files["wa_backend/services.py"]
    warehouse = files["wa_backend/api/warehouse.py"]
    dispatch = files["wa_backend/api/dispatch.py"]
    driver = files["wa_backend/api/driver.py"]

    require(
        models,
        [
            "commercial_context      = Column(JSONB, nullable=False)",
            "lifecycle_revision_snapshot = Column(Integer, nullable=False)",
            "source_stock_status     = Column(String(50), nullable=False)",
        ],
        "models Stage4E",
    )
    if "transfer_purpose        = Column(String(50), nullable=False, default=" in models:
        abort("silent transfer_purpose ORM default still exists in models.py")
    if "server_default='WAREHOUSE_BALANCING'" in models:
        abort("silent transfer_purpose DB default still exists in models.py")

    require(
        schemas,
        [
            "TransferPurpose = Literal[",
            "transfer_purpose: TransferPurpose",
            "expiry_date: Optional[date] = None",
        ],
        "schemas Stage4E",
    )

    require(
        services,
        [
            "async def resolve_inflight_transfer_destination_statuses(",
            "_TRANSFER_TERMINAL_REFERENCE_TYPES",
            '"TRANSFER_TERMINAL_STATUS"',
            '"HANDSHAKE_TERMINAL_STATUS"',
            'lifecycle_status == "ARCHIVED"',
        ],
        "services Stage4E",
    )

    require(
        warehouse,
        [
            "_GENERIC_TRANSFER_PURPOSE_CAPABILITY",
            '"TRANSFER_PURPOSE_WORKFLOW_REQUIRED"',
            '"TRANSFER_DIRECTION_BLOCKED"',
            "transfer_purpose=transfer_purpose",
            "commercial_context={",
            "lifecycle_revision_snapshot=int(variant_state.lifecycle_revision)",
            "resolve_inflight_transfer_destination_statuses(",
            "'TRANSFER_TERMINAL_STATUS'",
        ],
        "warehouse Stage4E",
    )

    require(
        dispatch,
        [
            'transfer_purpose = "ROUTE_LOAD" if delta > 0 else "ROUTE_RETURN"',
            "transfer_purpose=transfer_purpose",
            "commercial_context={",
            "lifecycle_revision_snapshot=int(variant.lifecycle_revision)",
            '"quantity": line.quantity',
        ],
        "dispatch Stage4E",
    )

    require(
        driver,
        [
            "async def _resolve_handshake_destination_statuses(",
            "destination_status_by_line",
            '"HANDSHAKE_TERMINAL_STATUS"',
            '"quantity": quantity',
            "resolve_inflight_transfer_destination_statuses(",
        ],
        "driver Stage4E",
    )
    if "_validate_incoming_handshake_batches" in driver:
        abort("legacy partial handshake batch validator still exists")
    if '"quantity": int(line.quantity)' in driver:
        abort("driver handshake still truncates transfer quantity to int")

    require(
        migration_text,
        [
            "Stage4E requires empty transfer tables",
            "commercial_context",
            "lifecycle_revision_snapshot",
            "server_default=None",
        ],
        "migration Stage4E",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = root_dir()
    validate_git_baseline(root)
    validate_constructor_surface(root)

    paths = {rel: root / rel for rel in TARGET_FILES}
    for rel, path in paths.items():
        if not path.is_file():
            abort(f"required file missing: {rel}")

    migration_path = find_empty_migration(root)
    revision = parse_revision(migration_path)
    migration_new = build_migration(revision)

    originals = {rel: read(path) for rel, path in paths.items()}
    if any(PATCH_ID in text for text in originals.values()):
        abort("Stage4E core marker already exists; refusing double/partial application.")

    # Baseline markers pinned to dev inv 8.
    require(
        originals["wa_backend/models.py"],
        [
            "default='WAREHOUSE_BALANCING', server_default='WAREHOUSE_BALANCING'",
            "class InventoryTransferLine(Base):",
        ],
        "models preflight",
    )
    require(
        originals["wa_backend/api/warehouse.py"],
        [
            "async def unified_transfer_dispatch(",
            "async def _move_transfer_lines_from_transit(",
            "batch_sellability_predicate(",
        ],
        "warehouse preflight",
    )
    require(
        originals["wa_backend/api/dispatch.py"],
        [
            'workflow_type="HANDSHAKE"',
            "InventoryTransferLine(",
            '"quantity": int(line.quantity)',
        ],
        "dispatch preflight",
    )
    require(
        originals["wa_backend/api/driver.py"],
        [
            "async def _validate_incoming_handshake_batches(",
            "def _build_handshake_movement_specs(",
            "batch_respond_to_transfers(",
        ],
        "driver preflight",
    )

    patched = dict(originals)
    patched["wa_backend/models.py"] = patch_models(patched["wa_backend/models.py"])
    patched["wa_backend/schemas.py"] = patch_schemas(patched["wa_backend/schemas.py"])
    patched["wa_backend/services.py"] = patch_services(patched["wa_backend/services.py"])
    patched["wa_backend/api/warehouse.py"] = patch_warehouse(
        patched["wa_backend/api/warehouse.py"]
    )
    patched["wa_backend/api/dispatch.py"] = patch_dispatch(
        patched["wa_backend/api/dispatch.py"]
    )
    patched["wa_backend/api/driver.py"] = patch_driver(
        patched["wa_backend/api/driver.py"]
    )

    validate_post(patched, migration_new)

    if args.check:
        print("STAGE4E_CORE_PREFLIGHT_OK")
        print(f"BASELINE_HEAD: {EXPECTED_HEAD}")
        print(f"MIGRATION: {migration_path.relative_to(root)}")
        print(
            "FILES_TO_CHANGE: models.py + schemas.py + services.py + "
            "api/warehouse.py + api/dispatch.py + api/driver.py + generated migration"
        )
        print("GENERIC_PURPOSES_ENABLED: REPLENISHMENT + WAREHOUSE_BALANCING")
        print("ROUTE_PURPOSES_EXPLICIT: ROUTE_LOAD + ROUTE_RETURN")
        print(
            "SPECIAL_PURPOSES_FAIL_CLOSED: RETURN_TO_VENDOR + QUARANTINE + "
            "RECALL_RETURN + DISPOSAL (awaiting explicit destination-capability design)"
        )
        return

    backup_dir = root / ".patch_backups" / PATCH_ID
    if backup_dir.exists():
        abort(f"backup directory already exists: {backup_dir}")
    backup_dir.mkdir(parents=True, exist_ok=False)

    for rel, path in paths.items():
        shutil.copy2(path, backup_dir / rel.replace("/", "__"))
    shutil.copy2(
        migration_path,
        backup_dir / f"migration__{migration_path.name}.before",
    )

    for rel, content in patched.items():
        paths[rel].write_text(content, encoding="utf-8", newline="\n")
    migration_path.write_text(migration_new, encoding="utf-8", newline="\n")

    print("STAGE4E_CORE_PURPOSE_INFLIGHT_OK")
    print("PURPOSE_OK: transfer_purpose is explicit; silent WAREHOUSE_BALANCING default removed")
    print("ROUTE_OK: HANDSHAKE route load/return records ROUTE_LOAD/ROUTE_RETURN explicitly")
    print("CREATION_CONTEXT_OK: line lifecycle revision/state/hold + header commercial context persisted")
    print("INFLIGHT_OK: current hold/disposition/expiry/shelf-life re-evaluated at terminal receipt")
    print("SALES_HOLD_OK: safe receipt is downgraded to QUARANTINED")
    print("RECALL_OK: safe receipt is downgraded to RECALLED")
    print("ARCHIVED_OK: only trusted transfer-terminal movements can finish prior documents")
    print("ENGINE_OK: physical movement preserves status; safety downgrade is explicit STATUS_CHANGE")
    print("QUANTITY_OK: handshake transfer quantities are not int-truncated")
    print("NO_DEFAULT_WAREHOUSE_OK: no location is inferred")
    print("NOTE: no project files were deleted.")
    print("NEXT: py_compile + alembic upgrade head, then Stage4E special-purpose direction decision/gate.")


if __name__ == "__main__":
    main()