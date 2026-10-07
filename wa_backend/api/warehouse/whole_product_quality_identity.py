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
    db: AsyncSession,
    *,
    payload: WholeProductQualityResolveRequest,
    product_variant_id: int,
    company_id: int,
    actor_id: int,
) -> str:
    context = {"product_variant_id": int(product_variant_id)}
    supplier_id = payload.supplier_id
    semantic_excluded = {
        "confirmation_password",
        "supplier_id" if supplier_id is None else "recipient_name",
    }
    semantic_hash = _stable_request_hash(
        payload,
        context=context,
        exclude_fields=semantic_excluded,
    )
    if supplier_id is not None:
        return semantic_hash

    # New commands exclude credentials from identity. Older committed commands may
    # have serialized SecretStr's constant mask, and commands created before the
    # post-resolution choice did not contain post_resolution_hold at all. Accept
    # only those exact historical semantic shapes for replay; changed input still
    # fails canonical idempotency validation.
    compatible_hashes = {
        semantic_hash,
        _stable_request_hash(
            payload,
            context=context,
            exclude_fields={"supplier_id"},
        ),
        _stable_request_hash(
            payload,
            context=context,
            exclude_fields=semantic_excluded | {"post_resolution_hold"},
        ),
        _stable_request_hash(
            payload,
            context=context,
            exclude_fields={"supplier_id", "post_resolution_hold"},
        ),
    }
    stored_hash = await db.scalar(
        select(OperationIdempotency.request_hash)
        .where(
            OperationIdempotency.company_id == company_id,
            OperationIdempotency.created_by == actor_id,
            OperationIdempotency.operation == "WHOLE_PRODUCT_QUALITY_RESOLVE_ALL",
            OperationIdempotency.request_id == str(payload.request_id),
        )
        .limit(1)
    )
    return stored_hash if stored_hash in compatible_hashes else semantic_hash
