"""Bounded staging I/O on the existing pool; no partial commits or new worker."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from contextvars import ContextVar
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import event

from database import engine
from domains.simple_products.imports.domain.errors import ProductImportStagingTimeoutError

# Per awaited database step / 500-row statement, never a whole-source deadline.
STAGING_IO_TIMEOUT_SECONDS = 120.0
STAGING_CLEANUP_TIMEOUT_SECONDS = 10.0
_active_guard: ContextVar[StagingIOGuard | None] = ContextVar("product_import_staging_io", default=None)
_GUARD_RECORD_KEY = "wanasah_product_import_staging_io"
logger = logging.getLogger("wanasah_logger")


@event.listens_for(engine.sync_engine, "checkout", insert=True)
def _capture_staging_connection(dbapi_connection, connection_record, connection_proxy) -> None:
    # Run BEFORE the existing checkout RLS query, including reused connections.
    # Other sessions have no active guard and retain their existing behavior.
    guard = _active_guard.get()
    if guard is not None:
        guard.driver_connection = dbapi_connection.driver_connection
        guard.connection_record = connection_record
        connection_record.info[_GUARD_RECORD_KEY] = guard
        if guard.aborted:
            # A checkout that finishes after its caller timed out must never
            # continue with tenant SQL on a now-abandoned session.
            guard.driver_connection.terminate()
            raise ProductImportStagingTimeoutError()


@event.listens_for(engine.sync_engine, "checkin")
def _release_staging_connection(dbapi_connection, connection_record) -> None:
    guard = connection_record.info.pop(_GUARD_RECORD_KEY, None)
    if guard is not None and guard.connection_record is connection_record:
        # COMMIT returns the connection to the shared pool. A late cancellation
        # must never terminate a transport already borrowed by another tenant.
        guard.driver_connection = None
        guard.connection_record = None


def _consume_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except BaseException:
        pass


class StagingIOGuard:
    """Abort only this staging session's transport if an await stops progressing.

    asyncio.wait_for alone waits for driver cancellation to finish and can exceed
    its timeout. Wait independently, terminate the owned asyncpg transport first,
    then cancel/drain the operation. PostgreSQL rolls back an uncommitted
    transaction when that connection closes; never terminate another backend.
    """

    def __init__(self, *, company_id: int, job_id: UUID) -> None:
        self.company_id = int(company_id)
        self.job_id = job_id
        self.driver_connection: Any = None
        self.connection_record: Any = None
        self.aborted = False

    def abort(self, *, operation: str) -> None:
        if self.aborted:
            return
        self.aborted = True
        owned_connection = self.driver_connection is not None
        if owned_connection:
            # Transport can already be disconnecting or invalidated. A failure
            # here must not skip _stop(task) and orphan the staging coroutine.
            # Log only scoped identifiers; never expose driver exception text.
            try:
                self.driver_connection.terminate()
            except Exception:
                logger.warning(
                    "PRODUCT_IMPORT_STAGING_IO_TERMINATE_FAILED "
                    "correlation_id=product-import:%s company_id=%s job_id=%s",
                    self.job_id, self.company_id, self.job_id,
                )
        logger.warning(
            "PRODUCT_IMPORT_STAGING_IO_ABORT correlation_id=product-import:%s "
            "company_id=%s job_id=%s operation=%s owned_connection=%s",
            self.job_id, self.company_id, self.job_id, operation,
            int(owned_connection),
        )

    async def _stop(self, task: asyncio.Task) -> None:
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=STAGING_CLEANUP_TIMEOUT_SECONDS)
        if done:
            _consume_result(task)
        else:
            # Never await a non-cooperating cancellation forever. Any captured
            # transport is closed; consume a late failure without echoing input.
            task.add_done_callback(_consume_result)
            logger.error(
                "PRODUCT_IMPORT_STAGING_IO_PENDING correlation_id=product-import:%s "
                "company_id=%s job_id=%s owned_connection=%s",
                self.job_id, self.company_id, self.job_id,
                int(self.driver_connection is not None),
            )

    async def run(
        self, operation_coro: Coroutine[Any, Any, Any], *, operation: str,
        cleanup: bool = False,
    ) -> Any:
        if self.aborted and not cleanup:
            operation_coro.close()
            raise ProductImportStagingTimeoutError()
        token = _active_guard.set(self)
        try:
            task = asyncio.create_task(operation_coro)
        finally:
            _active_guard.reset(token)
        timeout = STAGING_CLEANUP_TIMEOUT_SECONDS if cleanup else STAGING_IO_TIMEOUT_SECONDS
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
        except BaseException:
            self.abort(operation=operation)
            await self._stop(task)
            raise
        if not done:
            self.abort(operation=operation)
            await self._stop(task)
            raise ProductImportStagingTimeoutError()
        return task.result()
