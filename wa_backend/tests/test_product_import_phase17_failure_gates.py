from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from domains.simple_products.imports.application import execution_service
from domains.simple_products.imports.application import source_service
from domains.simple_products.imports.application.state_machine import JobStatus
from domains.simple_products.imports.domain import ProductImportTerminalError
from domains.simple_products.imports.infrastructure import repository


class Phase17ParsingCrashTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_parsing_crash_retains_source_and_retry_resumes_safely(
        self,
    ) -> None:
        source_id = uuid4()
        job_id = uuid4()
        payload = (
            b"Product,Unit Price\n"
            b"Tea,1.000\n"
        )
        first_context = (
            source_service.ProductImportSourceContext(
                legacy_payload=None,
                source_id=source_id,
                source_size=len(
                    payload
                ),
                source_sha256=
                    __import__(
                        "hashlib"
                    ).sha256(
                        payload
                    ).hexdigest(),
                source_cleared=False,
                file_name=
                    "products.csv",
                status=
                    JobStatus.QUEUED.value,
            )
        )
        retry_context = (
            source_service.ProductImportSourceContext(
                legacy_payload=None,
                source_id=source_id,
                source_size=len(
                    payload
                ),
                source_sha256=
                    first_context.source_sha256,
                source_cleared=False,
                file_name=
                    "products.csv",
                status=
                    JobStatus.PARSING.value,
            )
        )
        store = SimpleNamespace(
            read_verified_bytes=
                AsyncMock(
                    return_value=
                        payload
                ),
            delete_source_bytes=
                AsyncMock(),
        )
        stage = AsyncMock(
            side_effect=[
                RuntimeError(
                    "simulated parser worker crash"
                ),
                None,
            ]
        )

        with (
            patch.object(
                source_service,
                "_load_source_context",
                AsyncMock(
                    side_effect=[
                        first_context,
                        retry_context,
                    ]
                ),
            ),
            patch.object(
                source_service,
                "set_job_status",
                AsyncMock(
                    return_value=
                        JobStatus.PARSING.value
                ),
            ),
            patch.object(
                source_service,
                "stage_source",
                stage,
            ),
            patch.object(
                source_service,
                "_runtime_state",
                AsyncMock(
                    return_value=(
                        JobStatus.VALIDATING.value,
                        False,
                    )
                ),
            ),
            patch.object(
                source_service,
                "_mark_source_cleaned",
                AsyncMock(),
            ) as mark_cleaned,
        ):
            with self.assertRaises(
                RuntimeError
            ):
                await source_service.prepare_import_source(
                    company_id=7,
                    job_id=job_id,
                    source_store=store,
                )

            store.delete_source_bytes.assert_not_awaited()

            status = (
                await source_service.prepare_import_source(
                    company_id=7,
                    job_id=job_id,
                    source_store=store,
                )
            )

        self.assertEqual(
            status,
            JobStatus.VALIDATING.value,
        )
        self.assertEqual(
            store.read_verified_bytes.await_count,
            2,
        )
        self.assertEqual(
            stage.await_count,
            2,
        )
        store.delete_source_bytes.assert_awaited_once_with(
            company_id=7,
            source_id=source_id,
        )
        mark_cleaned.assert_awaited_once_with(
            company_id=7,
            job_id=job_id,
        )


class Phase17PermissionRevocationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_revoked_permission_fails_before_execution_rows_or_writes(
        self,
    ) -> None:
        job_id = uuid4()
        db = SimpleNamespace(
            rollback=AsyncMock(),
            commit=AsyncMock(),
        )
        job = SimpleNamespace(
            status=
                JobStatus.IMPORTING.value,
            created_by=55,
        )
        actor = SimpleNamespace(
            id=55,
            company_id=7,
        )
        list_rows = AsyncMock()
        execute_rows = AsyncMock()

        class RevokedAccess:
            def __init__(
                self,
                _db,
                _actor,
            ) -> None:
                pass

            async def require(
                self,
                _permission,
                *,
                any_location,
            ) -> None:
                self.assert_any_location(
                    any_location
                )
                raise HTTPException(
                    status_code=403,
                    detail="revoked",
                )

            @staticmethod
            def assert_any_location(
                value,
            ) -> None:
                if value is not True:
                    raise AssertionError(
                        "permission scope changed"
                    )

        with (
            patch.object(
                execution_service,
                "open_tenant_session",
                AsyncMock(
                    return_value=(
                        object(),
                        db,
                    )
                ),
            ),
            patch.object(
                execution_service,
                "close_tenant_session",
                AsyncMock(),
            ),
            patch.object(
                execution_service,
                "load_job",
                AsyncMock(
                    return_value=job
                ),
            ),
            patch.object(
                execution_service,
                "load_active_actor",
                AsyncMock(
                    return_value=actor
                ),
            ),
            patch.object(
                execution_service,
                "InventoryAccess",
                RevokedAccess,
            ),
            patch.object(
                execution_service,
                "list_job_rows",
                list_rows,
            ),
            patch.object(
                execution_service,
                "_execute_rows_best_effort",
                execute_rows,
            ),
        ):
            with self.assertRaises(
                ProductImportTerminalError
            ) as raised:
                await execution_service.execute_import(
                    company_id=7,
                    job_id=job_id,
                )

        self.assertIn(
            "required permissions",
            str(
                raised.exception
            ),
        )
        list_rows.assert_not_awaited()
        execute_rows.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()


class Phase17RepositoryIsolationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_job_lookup_is_tenant_prefixed_before_repository_read(
        self,
    ) -> None:
        job_id = uuid4()

        class FakeDb:
            def __init__(
                self,
            ) -> None:
                self.statement = None

            async def scalar(
                self,
                statement,
            ):
                self.statement = statement
                return None

        db = FakeDb()
        result = await repository.load_job(
            db,
            company_id=101,
            job_id=job_id,
        )

        self.assertIsNone(
            result
        )
        self.assertIsNotNone(
            db.statement
        )
        compiled = db.statement.compile()
        values = list(
            compiled.params.values()
        )
        self.assertIn(
            101,
            values,
        )
        self.assertIn(
            job_id,
            values,
        )
        sql = str(
            compiled
        )
        self.assertIn(
            "product_import_jobs.company_id",
            sql,
        )
        self.assertIn(
            "product_import_jobs.id",
            sql,
        )


if __name__ == "__main__":
    unittest.main()
