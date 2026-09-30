from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from procrastinate import RetryStrategy

from domains.simple_products.imports.infrastructure.queue import (
    _is_final_retry_attempt,
)
from domains.simple_products.imports.infrastructure.recovery_reconciler import (
    reconcile_orphaned_import_jobs,
)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, statement, parameters):
        self.statement = statement
        self.parameters = parameters
        return _Cursor(self.rows)

    @asynccontextmanager
    async def transaction(self):
        yield


class ProductImportD4RetryDecisionTests(unittest.TestCase):
    def test_retry_decision_uses_installed_procrastinate_task_contract(self):
        strategy = RetryStrategy(max_attempts=4, wait=3, exponential_wait=2)
        context = SimpleNamespace(
            task=SimpleNamespace(retry_strategy=strategy),
            job=SimpleNamespace(attempts=1),
        )
        self.assertFalse(_is_final_retry_attempt(context, RuntimeError("transient")))
        context.job.attempts = 4
        self.assertTrue(_is_final_retry_attempt(context, RuntimeError("final")))


class ProductImportD4RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_orphan_reconciliation_uses_job_dedupe_and_company_execution_lock(self):
        first = uuid4()
        second = uuid4()
        connection = _Connection([(7, first), (8, second)])
        deferred = AsyncMock()
        configured = SimpleNamespace(defer_async=deferred)
        task = SimpleNamespace(configure=Mock(return_value=configured))

        result = await reconcile_orphaned_import_jobs(
            task,
            connection=connection,
            stale_seconds=60,
            limit=100,
        )

        self.assertEqual(result["orphan_candidates"], 2)
        self.assertEqual(result["orphan_requeued"], 2)
        self.assertEqual(result["orphan_deduplicated"], 0)
        self.assertEqual(task.configure.call_count, 2)
        task.configure.assert_any_call(
            connection=connection,
            lock="product-import:7",
            queueing_lock=f"product-import-job:{first}",
        )
        task.configure.assert_any_call(
            connection=connection,
            lock="product-import:8",
            queueing_lock=f"product-import-job:{second}",
        )
        self.assertEqual(deferred.await_count, 2)

    async def test_orphan_reconciliation_is_bounded(self):
        connection = _Connection([])
        task = SimpleNamespace(configure=Mock())
        with self.assertRaisesRegex(ValueError, "between 1 and 500"):
            await reconcile_orphaned_import_jobs(
                task,
                connection=connection,
                stale_seconds=60,
                limit=501,
            )
