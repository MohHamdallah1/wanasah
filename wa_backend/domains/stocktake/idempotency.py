"""Bounded Stocktake idempotency helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services import begin_idempotent_operation, complete_idempotent_operation


def stocktake_request_hash(payload: BaseModel, *, target: int | str | None = None) -> str:
    body: dict[str, Any] = payload.model_dump(mode="json", exclude={"request_id"})
    canonical = json.dumps(
        {"target": target, "payload": body},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def begin_stocktake_command(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    operation: str,
    payload: BaseModel,
    target: int | str | None = None,
):
    return await begin_idempotent_operation(
        db,
        company_id=company_id,
        actor_id=actor_id,
        operation=operation,
        request_id=str(getattr(payload, "request_id")),
        request_hash=stocktake_request_hash(payload, target=target),
    )


def complete_stocktake_command(record, response: dict) -> None:
    complete_idempotent_operation(record, response)
