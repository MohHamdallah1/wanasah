from __future__ import annotations

import ast
import os
import py_compile
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

TARGETS = {
    "models": BACKEND / "models.py",
    "schemas": BACKEND / "schemas.py",
    "services": BACKEND / "services.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
}


def normalize_newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match, found {count}. "
            "لم يتم تعديل أي ملف."
        )
    return text.replace(old, new, 1)


MODEL_BLOCK = """class OperationIdempotency(Base):
    # سجل عام للـ idempotency على مستوى العملية التجارية داخل Tenant واحد.
    __tablename__ = 'operation_idempotency'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'operation', 'request_id',
            name='uq_operation_idempotency_request'
        ),
        UniqueConstraint(
            'company_id', 'id',
            name='uq_operation_idempotency_company_id'
        ),
        ForeignKeyConstraint(
            ['company_id', 'created_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_operation_idempotency_tenant_actor'
        ),
        CheckConstraint(
            "length(trim(operation)) > 0",
            name='chk_operation_idempotency_operation_not_blank'
        ),
        CheckConstraint(
            "request_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name='chk_operation_idempotency_request_id_format'
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name='chk_operation_idempotency_hash_format'
        ),
        CheckConstraint(
            "((response_json IS NULL AND completed_at IS NULL) OR "
            "(response_json IS NOT NULL AND completed_at IS NOT NULL))",
            name='chk_operation_idempotency_completion_pair'
        ),
    )

    id            = Column(Integer, primary_key=True)
    company_id    = Column(
        Integer,
        ForeignKey('companies.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    operation     = Column(String(80), nullable=False)
    request_id    = Column(String(36), nullable=False)
    request_hash  = Column(String(64), nullable=False)
    created_by    = Column(Integer, nullable=False, index=True)
    response_json = Column(JSON, nullable=True)
    created_at    = Column(DateTime, nullable=False, default=utc_now, index=True)
    completed_at  = Column(DateTime, nullable=True)


"""


SERVICE_HELPERS = """# حجز request_id للعملية داخل Tenant واحد وإرجاع النتيجة السابقة عند retry مطابق.
async def begin_idempotent_operation(
    db_session: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    operation: str,
    request_id: str,
    request_hash: str,
) -> Tuple[OperationIdempotency, Optional[Dict[str, Any]]]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        actor_id = _strict_int(actor_id, "actor_id", minimum=1)
        canonical_request_id = str(UUID(str(request_id)))
    except (ValueError, TypeError) as exc:
        raise InventoryMutationError("بيانات idempotency غير صالحة.") from exc

    operation = str(operation).strip()
    if not operation or len(operation) > 80:
        raise InventoryMutationError("operation غير صالح لـ idempotency.")

    request_hash = str(request_hash).strip().lower()
    if (
        len(request_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in request_hash)
    ):
        raise InventoryMutationError("request_hash غير صالح لـ idempotency.")

    await db_session.execute(
        select(
            func.pg_advisory_xact_lock(
                company_id,
                func.hashtext(
                    f"op-idempotency:{operation}:{canonical_request_id}"
                ),
            )
        )
    )

    existing = (
        await db_session.execute(
            select(OperationIdempotency)
            .execution_options(populate_existing=True)
            .filter_by(
                company_id=company_id,
                operation=operation,
                request_id=canonical_request_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.created_by != actor_id:
            raise InventoryMutationError(
                "request_id مستخدم مسبقاً بواسطة مستخدم آخر داخل الشركة."
            )

        if existing.request_hash != request_hash:
            raise InventoryMutationError(
                "request_id مستخدم مسبقاً لطلب مختلف؛ استخدم request_id جديداً."
            )

        if existing.completed_at is None or existing.response_json is None:
            raise RuntimeError(
                "Idempotency invariant violated: committed request is incomplete."
            )

        if not isinstance(existing.response_json, dict):
            raise RuntimeError(
                "Idempotency invariant violated: stored response is not an object."
            )

        return existing, dict(existing.response_json)

    record = OperationIdempotency(
        company_id=company_id,
        operation=operation,
        request_id=canonical_request_id,
        request_hash=request_hash,
        created_by=actor_id,
    )
    db_session.add(record)
    await db_session.flush()
    return record, None


# تثبيت نتيجة العملية داخل نفس معاملة البيانات قبل commit.
def complete_idempotent_operation(
    record: OperationIdempotency,
    response_payload: Dict[str, Any],
) -> None:
    if record.completed_at is not None or record.response_json is not None:
        raise RuntimeError("Idempotency record already completed.")
    if not isinstance(response_payload, dict):
        raise TypeError("response_payload يجب أن يكون dict.")

    record.response_json = dict(response_payload)
    record.completed_at = utc_now()


"""


WAREHOUSE_HASH_HELPER = """# إنشاء بصمة ثابتة للطلب مع اعتبار ترتيب items غير مؤثر منطقياً.
def _stable_request_hash(payload) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})

    items = body.get("items")
    if isinstance(items, list):
        body["items"] = sorted(
            items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )

    canonical = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


"""


def patch_models(text: str) -> str:
    if "class OperationIdempotency(Base):" in text:
        raise RuntimeError("models.py: OperationIdempotency موجود مسبقاً.")

    if "Text, JSON, ForeignKey" not in text:
        text = replace_once(
            text,
            "Text, ForeignKey",
            "Text, JSON, ForeignKey",
            "models.py JSON import",
        )

    return replace_once(
        text,
        "class ProductBatch(Base):",
        MODEL_BLOCK + "class ProductBatch(Base):",
        "models.py OperationIdempotency insertion",
    )


def patch_schemas(text: str) -> str:
    if "from uuid import UUID" not in text:
        text = replace_once(
            text,
            "from datetime import datetime, timezone, date\n",
            "from datetime import datetime, timezone, date\nfrom uuid import UUID\n",
            "schemas.py UUID import",
        )

    text = replace_once(
        text,
        "class UpgradedInboundRequest(RequestModel):\n"
        "    location_id: PositiveDbInt\n",
        "class UpgradedInboundRequest(RequestModel):\n"
        "    request_id: UUID\n"
        "    location_id: PositiveDbInt\n",
        "schemas.py inbound request_id",
    )

    text = replace_once(
        text,
        "class UnifiedDispatchRequest(RequestModel):\n"
        "    source_location_id: PositiveDbInt\n",
        "class UnifiedDispatchRequest(RequestModel):\n"
        "    request_id: UUID\n"
        "    source_location_id: PositiveDbInt\n",
        "schemas.py dispatch request_id",
    )
    return text


def patch_services(text: str) -> str:
    if "async def begin_idempotent_operation(" in text:
        raise RuntimeError("services.py: idempotency helpers موجودة مسبقاً.")

    if "from uuid import UUID\n" not in text:
        text = replace_once(
            text,
            "from datetime import date\n",
            "from datetime import date\nfrom uuid import UUID\n",
            "services.py UUID import",
        )

    text = replace_once(
        text,
        "    ProductBatch,\n    StocktakeSession,\n",
        "    ProductBatch,\n    OperationIdempotency,\n    StocktakeSession,\n",
        "services.py OperationIdempotency import",
    )

    text = replace_once(
        text,
        "class InventoryMutationError(Exception):\n    pass\n\n\n",
        "class InventoryMutationError(Exception):\n    pass\n\n\n"
        + SERVICE_HELPERS,
        "services.py idempotency service insertion",
    )
    return text


def patch_warehouse(text: str) -> str:
    text = replace_once(
        text,
        "    get_company_local_date,\n"
        "    InventoryMutationError,\n",
        "    get_company_local_date,\n"
        "    begin_idempotent_operation,\n"
        "    complete_idempotent_operation,\n"
        "    InventoryMutationError,\n",
        "warehouse.py idempotency service imports",
    )

    if "def _stable_request_hash(" in text:
        raise RuntimeError("warehouse.py: request hash helper موجود مسبقاً.")

    text = replace_once(
        text,
        "router = APIRouter()\n\n",
        "router = APIRouter()\n\n\n" + WAREHOUSE_HASH_HELPER,
        "warehouse.py request hash helper",
    )

    # Inbound
    start = text.index('@router.post("/warehouse/inbound"')
    end = text.index(
        "# =================================================================================\n# 2. إشعارات النواقص",
        start,
    )
    inbound = text[start:end]

    inbound = replace_once(
        inbound,
        "    try:\n"
        "        if not payload.items:\n",
        "    try:\n"
        "        request_hash = _stable_request_hash(payload)\n"
        "        idempotency_record, replay_response = await begin_idempotent_operation(\n"
        "            db,\n"
        "            company_id=company_id,\n"
        "            actor_id=current_admin.id,\n"
        "            operation=\"WAREHOUSE_INBOUND\",\n"
        "            request_id=str(payload.request_id),\n"
        "            request_hash=request_hash,\n"
        "        )\n"
        "        if replay_response is not None:\n"
        "            await db.rollback()\n"
        "            return replay_response\n\n"
        "        if not payload.items:\n",
        "warehouse.py inbound begin idempotency",
    )

    inbound = replace_once(
        inbound,
        '            reference_id = f"AUTO-INB-{uuid.uuid4().hex[:10].upper()}"',
        '            reference_id = f"AUTO-INB-{payload.request_id.hex.upper()}"',
        "warehouse.py deterministic AUTO-INB reference",
    )

    inbound = replace_once(
        inbound,
        '        await db.commit()\n'
        '        return {"message": "تم إدخال البضاعة وتحديث المخزون بنجاح"}',
        '        response_payload = {\n'
        '            "message": "تم إدخال البضاعة وتحديث المخزون بنجاح"\n'
        '        }\n'
        '        complete_idempotent_operation(\n'
        '            idempotency_record,\n'
        '            response_payload,\n'
        '        )\n'
        '        await db.commit()\n'
        '        return response_payload',
        "warehouse.py inbound complete idempotency",
    )
    text = text[:start] + inbound + text[end:]

    # Transfer dispatch
    start = text.index('@router.post("/warehouse/unified/transfer/dispatch"')
    end = text.index(
        '@router.post("/warehouse/unified/transfer/receive"',
        start,
    )
    dispatch = text[start:end]

    dispatch = replace_once(
        dispatch,
        "    try:\n"
        "        await _verify_location_ownership(\n",
        "    try:\n"
        "        request_hash = _stable_request_hash(payload)\n"
        "        idempotency_record, replay_response = await begin_idempotent_operation(\n"
        "            db,\n"
        "            company_id=company_id,\n"
        "            actor_id=current_admin.id,\n"
        "            operation=\"WAREHOUSE_TRANSFER_DISPATCH\",\n"
        "            request_id=str(payload.request_id),\n"
        "            request_hash=request_hash,\n"
        "        )\n"
        "        if replay_response is not None:\n"
        "            await db.rollback()\n"
        "            return replay_response\n\n"
        "        await _verify_location_ownership(\n",
        "warehouse.py dispatch begin idempotency",
    )

    dispatch = replace_once(
        dispatch,
        '        await db.commit()\n'
        '        return {\n'
        '            "message": "تم تحميل البضاعة بنجاح وهي الآن في الطريق.",\n'
        '            "transfer_reference": transfer_ref,\n'
        '            "header_id": header.id\n'
        '        }',
        '        response_payload = {\n'
        '            "message": "تم تحميل البضاعة بنجاح وهي الآن في الطريق.",\n'
        '            "transfer_reference": transfer_ref,\n'
        '            "header_id": header.id,\n'
        '        }\n'
        '        complete_idempotent_operation(\n'
        '            idempotency_record,\n'
        '            response_payload,\n'
        '        )\n'
        '        await db.commit()\n'
        '        return response_payload',
        "warehouse.py dispatch complete idempotency",
    )
    text = text[:start] + dispatch + text[end:]
    return text


def validate_cross_file(prepared: dict[str, str]) -> None:
    required = {
        "models": (
            "class OperationIdempotency(Base):",
            "uq_operation_idempotency_request",
            "fk_operation_idempotency_tenant_actor",
        ),
        "schemas": (
            "class UpgradedInboundRequest(RequestModel):\n    request_id: UUID",
            "class UnifiedDispatchRequest(RequestModel):\n    request_id: UUID",
        ),
        "services": (
            "async def begin_idempotent_operation(",
            "def complete_idempotent_operation(",
            "OperationIdempotency,",
        ),
        "warehouse": (
            "def _stable_request_hash(",
            'operation="WAREHOUSE_INBOUND"',
            'operation="WAREHOUSE_TRANSFER_DISPATCH"',
            'reference_id = f"AUTO-INB-{payload.request_id.hex.upper()}"',
        ),
    }

    for name, tokens in required.items():
        for token in tokens:
            if token not in prepared[name]:
                raise RuntimeError(
                    f"{name}: missing invariant after patch: {token}"
                )

    if 'AUTO-INB-{uuid.uuid4().hex[:10].upper()}' in prepared["warehouse"]:
        raise RuntimeError("warehouse.py: random AUTO-INB reference ما زال موجوداً.")

    if prepared["schemas"].count("    request_id: UUID") < 2:
        raise RuntimeError("schemas.py: request_id ناقص من أحد العقدين.")


def main() -> None:
    if not BACKEND.is_dir():
        raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

    for name, path in TARGETS.items():
        if not path.is_file():
            raise SystemExit(f"ERROR: الملف مفقود ({name}): {path}")

    originals: dict[str, bytes] = {}
    newline_styles: dict[str, str] = {}
    prepared: dict[str, str] = {}

    for name, path in TARGETS.items():
        raw = path.read_bytes()
        originals[name] = raw
        newline_styles[name] = "CRLF" if b"\r\n" in raw else "LF"
        text = normalize_newlines(raw).decode("utf-8")

        if name == "models":
            text = patch_models(text)
        elif name == "schemas":
            text = patch_schemas(text)
        elif name == "services":
            text = patch_services(text)
        else:
            text = patch_warehouse(text)

        ast.parse(text, filename=str(path))
        prepared[name] = text

    validate_cross_file(prepared)

    temp_paths: dict[str, Path] = {}
    replaced: list[str] = []

    try:
        for name, path in TARGETS.items():
            output = prepared[name].encode("utf-8")
            if newline_styles[name] == "CRLF":
                output = output.replace(b"\n", b"\r\n")

            tmp = path.with_suffix(path.suffix + ".idempotency_v2.tmp")
            tmp.write_bytes(output)
            py_compile.compile(str(tmp), doraise=True)
            temp_paths[name] = tmp

        try:
            for name in ("models", "schemas", "services", "warehouse"):
                os.replace(temp_paths[name], TARGETS[name])
                replaced.append(name)
        except Exception:
            for name in replaced:
                TARGETS[name].write_bytes(originals[name])
            raise

    finally:
        for tmp in temp_paths.values():
            if tmp.exists():
                tmp.unlink()

    print("WAREHOUSE_REQUEST_IDEMPOTENCY_OK")
    print("models.py: OperationIdempotency added")
    print("schemas.py: request_id required for inbound + transfer dispatch")
    print("services.py: generic idempotency transaction service added")
    print("warehouse.py: inbound + transfer retry protection enabled")


if __name__ == "__main__":
    main()
