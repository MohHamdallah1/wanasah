"""Semantic command identity and bounded compatibility with committed V1 history."""
from __future__ import annotations

from typing import TYPE_CHECKING
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import OperationIdempotency
from ._shared import _stable_request_hash

if TYPE_CHECKING:
    from .whole_product_quality import WholeProductQualityResolveRequest


async def quality_request_hash(
    db: AsyncSession, *, payload: WholeProductQualityResolveRequest, product_variant_id: int,
    company_id: int, actor_id: int,
) -> str:
    context = {"product_variant_id": int(product_variant_id)}
    supplier_id = payload.supplier_id
    excluded = {"confirmation_password", "supplier_id" if supplier_id is None else "recipient_name"}
    semantic_hash = _stable_request_hash(payload, context=context, exclude_fields=excluded)
    if supplier_id is not None:
        return semantic_hash

    # Earlier V1 schemas either omitted the credential or serialized SecretStr's
    # constant mask. Only these exact semantic hashes qualify for legacy replay;
    # canonical begin_idempotent_operation still rejects any changed input.
    masked_legacy_hash = _stable_request_hash(payload, context=context, exclude_fields={"supplier_id"})
    stored_hash = await db.scalar(select(OperationIdempotency.request_hash).where(
        OperationIdempotency.company_id == company_id,
        OperationIdempotency.created_by == actor_id,
        OperationIdempotency.operation == "WHOLE_PRODUCT_QUALITY_RESOLVE_ALL",
        OperationIdempotency.request_id == str(payload.request_id),
    ).limit(1))
    return stored_hash if stored_hash in {semantic_hash, masked_legacy_hash} else semantic_hash
