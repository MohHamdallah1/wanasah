"""D07: durable identity and immutable result of one Dispatch route-launch intent.

Owns only the operation receipt/lookup. Existing route creation, published
commercial locks, stock movements and Visits stay in the canonical Dispatch
transaction and are not reimplemented. A receipt is committed with that route,
never inferred from matching Zone/Driver/Vehicle or a successful GET of routes.
Legacy no-request_id launches deliberately keep their old non-idempotent behavior.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import OperationIdempotency
from schemas import DispatchRouteRequest
from services import begin_idempotent_operation, complete_idempotent_operation

ROUTE_LAUNCH_OPERATION = "DISPATCH_ROUTE_LAUNCH_V1"


def route_launch_request_hash(payload: DispatchRouteRequest) -> str:
    """Canonical Pydantic-parsed business intent, excluding its stable UUID."""
    document = payload.model_dump(mode="json", exclude={"request_id"})
    return sha256(json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


async def begin_route_launch(
    db: AsyncSession, *, company_id: int, actor_id: int,
    payload: DispatchRouteRequest,
) -> tuple[OperationIdempotency | None, dict[str, Any] | None]:
    """Before any route/stock/Visit mutation, lock this company's UUID.

    Concurrent same UUID submissions wait on the existing canonical advisory
    and unique operation identity. Later identical calls replay the committed
    response, never re-enter the mutable stock or commercial preflight.
    """
    if payload.request_id is None:
        return None, None
    request_id = str(payload.request_id)
    record, original = await begin_idempotent_operation(
        db, company_id=company_id, actor_id=actor_id,
        operation=ROUTE_LAUNCH_OPERATION,
        request_id=request_id,
        request_hash=route_launch_request_hash(payload),
    )
    if original is not None:
        if (
            original.get("request_id") != request_id
            or original.get("state") != "COMMITTED"
            or type(original.get("route_id")) is not int
            or original["route_id"] <= 0
            or not isinstance(original.get("commercial_context"), dict)
        ):
            raise RuntimeError("D07 original route receipt is inconsistent")
    return record, original


def complete_route_launch(
    record: OperationIdempotency | None,
    *, payload: DispatchRouteRequest, response: dict[str, Any],
) -> dict[str, Any]:
    """Finish the immutable receipt INSIDE the route+visits+inventory TX."""
    if record is None:
        return response
    result = {
        **response,
        "request_id": str(payload.request_id),
        "state": "COMMITTED",
    }
    complete_idempotent_operation(record, result)
    return result


async def read_route_launch_receipt(
    db: AsyncSession, *, company_id: int, actor_id: int,
    request_id: UUID,
    require_authorized_route: Callable[[int], Awaitable[None]],
) -> dict[str, Any]:
    """Read only; authenticated same creator and current route authority required.

    A missing, rolled-back, in-flight or expired key is UNKNOWN (never guessed).
    No new route/stock/money/Visit is written by this lookup. Revoked or
    location-reassigned route access fails closed even for the original actor.
    """
    key = str(request_id)
    record = await db.scalar(
        select(OperationIdempotency).where(
            OperationIdempotency.company_id == company_id,
            OperationIdempotency.created_by == actor_id,
            OperationIdempotency.operation == ROUTE_LAUNCH_OPERATION,
            OperationIdempotency.request_id == key,
        )
    )
    if (
        record is None
        or str(record.state or "").upper() != "COMMITTED"
        or record.completed_at is None
        or not isinstance(record.response_json, dict)
        or record.response_json.get("request_id") != key
        or record.response_json.get("state") != "COMMITTED"
        or type(record.response_json.get("route_id")) is not int
        or record.response_json["route_id"] <= 0
        or not isinstance(record.response_json.get("commercial_context"), dict)
    ):
        return {"request_id": key, "state": "UNKNOWN"}

    response = dict(record.response_json)
    await require_authorized_route(response["route_id"])
    return {"request_id": key, "state": "COMMITTED", "response": response}
