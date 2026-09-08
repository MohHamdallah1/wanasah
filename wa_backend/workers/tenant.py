# WORKER_CORE_V1
from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import text

from context import tenant_context
from database import AsyncSessionLocal


def normalize_company_id(company_id: int) -> int:
    """Reject ambiguous/invalid tenant identities before touching the DB."""
    if isinstance(company_id, bool):
        raise ValueError("company_id must be a positive integer.")
    try:
        value = int(company_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("company_id must be a positive integer.") from exc
    if value <= 0 or str(value) != str(company_id).strip():
        raise ValueError("company_id must be a positive integer.")
    return value


@asynccontextmanager
async def tenant_session(company_id: int):
    """Open one tenant-scoped SQLAlchemy session for a worker task.

    - tenant_context is set BEFORE the first connection checkout.
    - app.current_tenant is set explicitly on the acquired connection.
    - no implicit commit is performed; the task owns its transaction boundary.
    - tenant context is always restored, including cancellation/errors.
    """
    cid = normalize_company_id(company_id)
    token = tenant_context.set(cid)
    try:
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    text(
                        "SELECT set_config("
                        "'app.current_tenant', :tenant_id, false)"
                    ),
                    {"tenant_id": str(cid)},
                )
                yield db
            except BaseException:
                await db.rollback()
                raise
            finally:
                # A task that forgot to commit must never leak an open transaction.
                if db.in_transaction():
                    await db.rollback()
    finally:
        tenant_context.reset(token)
