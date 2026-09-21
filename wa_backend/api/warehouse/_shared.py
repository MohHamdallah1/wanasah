from datetime import timezone, datetime
import base64
import hashlib
import json
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import Integer, any_, bindparam
from sqlalchemy.dialects.postgresql import ARRAY


# تهريب المحارف الخاصة في LIKE حتى يبقى البحث الحرفي آمناً وصحيحاً.
def _escape_like(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# بناء شرط عضوية PostgreSQL لمجموعة معرفات صحيحة باستخدام ARRAY bind parameter.
def _warehouse_array_membership(column, values, bind_name: str):
    normalized = sorted({int(value) for value in values})
    if not normalized:
        raise ValueError("Warehouse array membership requires values.")
    return column == any_(
        bindparam(
            bind_name,
            value=normalized,
            type_=ARRAY(Integer),
        )
    )



# إنشاء بصمة ثابتة لنطاق Cursor الخاص بقوائم المنتجات.
def _variant_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


# ترميز Cursor المنتج مع الاسم والمعرف وربطه بنطاق الاستعلام الحالي.
def _encode_variant_cursor(
    *,
    kind: str,
    variant_name: str,
    variant_id: int,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": kind,
            "scope": _variant_cursor_scope_hash(scope),
            "name": variant_name,
            "id": int(variant_id),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# فك Cursor المنتج والتحقق من نوعه ونطاقه قبل استخدامه في الاستعلام.
def _decode_variant_cursor(
    cursor: str,
    *,
    expected_kind: str,
    expected_scope: str,
) -> tuple[str, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != expected_kind
            or payload.get("scope")
            != _variant_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        variant_name = payload.get("name")
        variant_id = payload.get("id")

        if (
            not isinstance(variant_name, str)
            or not variant_name
            or len(variant_name) > 200
            or type(variant_id) is not int
            or variant_id <= 0
        ):
            raise ValueError

        return variant_name, variant_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor الصفحة غير صالح أو لا يطابق معايير الاستعلام الحالي.",
        ) from exc


# ====================================================
# بصمة طلب ثابتة لعمليات Idempotency المشتركة
# ====================================================
# إنشاء بصمة ثابتة للطلب مع اعتبار ترتيب items غير مؤثر منطقياً.
def _stable_request_hash(
    payload,
    *,
    context: Optional[dict] = None,
) -> str:
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

    if context:
        body["_context"] = dict(context)

    canonical = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

