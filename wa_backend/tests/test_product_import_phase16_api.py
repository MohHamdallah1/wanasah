from __future__ import annotations

from contextlib import ExitStack
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_driver
from database import get_db

router_module = importlib.import_module(
    "domains.simple_products.imports.api.router"
)
api_service = importlib.import_module(
    "domains.simple_products.imports.application.api_service"
)


class _FakeDb:
    pass


def _status_payload(
    job_id: UUID,
) -> dict[str, object]:
    return {
        "job_id": str(
            job_id
        ),
        "status": "IMPORTING",
        "file_name": "products.csv",
        "total_rows": 2,
        "processed_rows": 1,
        "valid_rows": 2,
        "failed_rows": 0,
        "imported_rows": 1,
        "invalid_rows": 0,
        "import_failed_rows": 0,
        "pending_rows": 1,
        "detected_headers": [
            "name",
            "unit_price",
        ],
        "suggested_mapping": {
            "name": "name",
            "unit_price":
                "unit_price",
        },
        "column_mapping": {
            "name": "name",
            "unit_price":
                "unit_price",
        },
        "default_lot_control_mode":
            "NONE",
        "default_expiry_control_mode":
            "NONE",
        "error_summary": {},
        "created_at": None,
        "started_at": None,
        "finished_at": None,
        "errors": [],
    }


class ProductImportPhase16ApiLifecycleTests(
    unittest.TestCase
):
    def setUp(
        self,
    ) -> None:
        self.company_id = 101
        self.actor_id = 11
        self.actor = SimpleNamespace(
            company_id=
                self.company_id,
            id=self.actor_id,
        )
        self.db = _FakeDb()

        app = FastAPI()
        app.include_router(
            router_module.router
        )

        async def db_override():
            yield self.db

        async def actor_override():
            return self.actor

        app.dependency_overrides[
            get_db
        ] = db_override
        app.dependency_overrides[
            get_current_driver
        ] = actor_override
        self.client = TestClient(
            app
        )

        self.stack = ExitStack()
        self.stack.enter_context(
            patch.object(
                router_module,
                "_require",
                AsyncMock(),
            )
        )
        self.stack.enter_context(
            patch.object(
                router_module,
                "_require_manage",
                AsyncMock(),
            )
        )
        self.addCleanup(
            self.stack.close
        )
        self.addCleanup(
            self.client.close
        )

    def test_template_contract(
        self,
    ) -> None:
        with patch.object(
            router_module,
            "build_product_import_template",
            return_value=b"xlsx",
        ) as build:
            response = self.client.get(
                "/simple-products/import-template?locale=en-US"
            )

        self.assertEqual(
            response.status_code,
            200,
        )
        build.assert_called_once_with(
            locale="en-US"
        )
        body = response.json()
        self.assertEqual(
            body[
                "file_name"
            ],
            "products-import-template.xlsx",
        )
        self.assertEqual(
            set(
                body
            ),
            {
                "file_name",
                "content_type",
                "content_base64",
            },
        )

    def test_create_upload_contract(
        self,
    ) -> None:
        job_id = uuid4()
        create_mock = AsyncMock(
            return_value={
                "job_id":
                    str(
                        job_id
                    ),
                "status":
                    "QUEUED",
                "replayed":
                    False,
                "default_lot_control_mode":
                    "NONE",
                "default_expiry_control_mode":
                    "NONE",
                "message":
                    "Import accepted for background processing.",
            }
        )
        with patch.object(
            router_module,
            "create_import",
            create_mock,
        ):
            response = self.client.post(
                "/simple-products/imports",
                data={
                    "request_id":
                        str(
                            uuid4()
                        ),
                },
                files={
                    "file": (
                        "products.csv",
                        b"name,unit_price\nTea,1.0\n",
                        "application/octet-stream",
                    )
                },
            )

        self.assertEqual(
            response.status_code,
            202,
        )
        self.assertEqual(
            response.json()[
                "job_id"
            ],
            str(
                job_id
            ),
        )
        create_mock.assert_awaited_once()

    def test_status_contract(
        self,
    ) -> None:
        job_id = uuid4()
        with patch.object(
            router_module,
            "read_import_status",
            AsyncMock(
                return_value=
                    _status_payload(
                        job_id
                    )
            ),
        ):
            response = self.client.get(
                f"/simple-products/imports/{job_id}"
            )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()[
                "pending_rows"
            ],
            1,
        )

    def test_errors_contract(
        self,
    ) -> None:
        job_id = uuid4()
        with patch.object(
            router_module,
            "read_import_errors",
            AsyncMock(
                return_value={
                    "items": [
                        {
                            "row_number":
                                7,
                            "code":
                                "IMPORT_NAME_REQUIRED",
                            "field":
                                "name",
                            "message":
                                "Product name is required.",
                        }
                    ],
                    "next_after_row":
                        None,
                }
            ),
        ):
            response = self.client.get(
                f"/simple-products/imports/{job_id}/errors"
            )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()[
                "items"
            ][
                0
            ][
                "field"
            ],
            "name",
        )

    def test_mapping_contract(
        self,
    ) -> None:
        job_id = uuid4()
        mapping_mock = AsyncMock(
            return_value={
                "job_id":
                    str(
                        job_id
                    ),
                "status":
                    "VALIDATING",
                "message":
                    "Column mapping accepted.",
            }
        )
        with patch.object(
            router_module,
            "set_import_mapping",
            mapping_mock,
        ):
            response = self.client.put(
                f"/simple-products/imports/{job_id}/mapping",
                json={
                    "mapping": {
                        "name":
                            "Product",
                        "unit_price":
                            "Price",
                    }
                },
            )

        self.assertEqual(
            response.status_code,
            202,
        )
        mapping_mock.assert_awaited_once()
        self.assertEqual(
            mapping_mock.await_args.kwargs[
                "mapping"
            ][
                "name"
            ],
            "Product",
        )

    def test_correction_download_contract(
        self,
    ) -> None:
        job_id = uuid4()
        artifact = SimpleNamespace(
            file_name=
                "correction.xlsx",
            content_type=
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            payload=b"xlsx",
            row_count=2,
        )
        with patch.object(
            router_module,
            "download_correction",
            AsyncMock(
                return_value=
                    artifact
            ),
        ):
            response = self.client.get(
                f"/simple-products/imports/{job_id}/correction?format=xlsx"
            )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()[
                "row_count"
            ],
            2,
        )

    def test_correction_upload_contract(
        self,
    ) -> None:
        job_id = uuid4()
        with (
            patch.object(
                router_module,
                "ensure_import_job_access",
                AsyncMock(),
            ),
            patch.object(
                router_module,
                "apply_correction",
                AsyncMock(
                    return_value={
                        "job_id":
                            str(
                                job_id
                            ),
                        "status":
                            "VALIDATING",
                        "replayed":
                            False,
                        "message":
                            "Correction accepted for revalidation.",
                    }
                ),
            ),
        ):
            response = self.client.post(
                f"/simple-products/imports/{job_id}/correction",
                data={
                    "request_id":
                        str(
                            uuid4()
                        ),
                },
                files={
                    "file": (
                        "correction.csv",
                        b"__wanasah_row_identity,__wanasah_row_number,name\n"
                        b"11111111-1111-4111-8111-111111111111,2,Tea\n",
                        "text/plain",
                    )
                },
            )

        self.assertEqual(
            response.status_code,
            202,
        )
        self.assertEqual(
            response.json()[
                "status"
            ],
            "VALIDATING",
        )

    def test_cancel_contract(
        self,
    ) -> None:
        job_id = uuid4()
        with patch.object(
            router_module,
            "cancel_import",
            AsyncMock(
                return_value={
                    "job_id":
                        str(
                            job_id
                        ),
                    "status":
                        "CANCELLED",
                    "message":
                        "Import cancellation accepted.",
                }
            ),
        ):
            response = self.client.post(
                f"/simple-products/imports/{job_id}/cancel"
            )

        self.assertEqual(
            response.status_code,
            202,
        )
        self.assertEqual(
            response.json()[
                "status"
            ],
            "CANCELLED",
        )

    def test_retry_contract(
        self,
    ) -> None:
        job_id = uuid4()
        with patch.object(
            router_module,
            "retry_import",
            AsyncMock(
                return_value={
                    "job_id":
                        str(
                            job_id
                        ),
                    "status":
                        "RETRYING",
                    "message":
                        "Import retry accepted.",
                }
            ),
        ):
            response = self.client.post(
                f"/simple-products/imports/{job_id}/retry"
            )

        self.assertEqual(
            response.status_code,
            202,
        )
        self.assertEqual(
            response.json()[
                "status"
            ],
            "RETRYING",
        )


class _TenantAwareDb:
    def __init__(
        self,
        *,
        foreign_company_id: int,
        foreign_job_id: UUID,
    ) -> None:
        self.foreign_company_id = int(
            foreign_company_id
        )
        self.foreign_job_id = (
            foreign_job_id
        )
        self.scalar_params: list[
            list[object]
        ] = []

    async def scalar(
        self,
        statement,
    ):
        compiled = statement.compile()
        values = list(
            compiled.params.values()
        )
        self.scalar_params.append(
            values
        )
        if (
            self.foreign_company_id
            in values
            and self.foreign_job_id
            in values
        ):
            return SimpleNamespace(
                id=
                    self.foreign_job_id,
                company_id=
                    self.foreign_company_id,
            )
        return None

    async def execute(
        self,
        _statement,
    ):
        raise AssertionError(
            "Cross-tenant request reached row query."
        )

    async def scalars(
        self,
        _statement,
    ):
        raise AssertionError(
            "Cross-tenant request reached error rows."
        )


class ProductImportPhase16TenantIsolationTests(
    unittest.TestCase
):
    def setUp(
        self,
    ) -> None:
        self.company_a = 101
        self.company_b = 202
        self.job_b = uuid4()
        self.db = _TenantAwareDb(
            foreign_company_id=
                self.company_b,
            foreign_job_id=
                self.job_b,
        )
        self.actor = SimpleNamespace(
            company_id=
                self.company_a,
            id=11,
        )

        app = FastAPI()
        app.include_router(
            router_module.router
        )

        async def db_override():
            yield self.db

        async def actor_override():
            return self.actor

        app.dependency_overrides[
            get_db
        ] = db_override
        app.dependency_overrides[
            get_current_driver
        ] = actor_override
        self.client = TestClient(
            app
        )

        self.stack = ExitStack()
        self.stack.enter_context(
            patch.object(
                router_module,
                "_require",
                AsyncMock(),
            )
        )
        self.stack.enter_context(
            patch.object(
                router_module,
                "_require_manage",
                AsyncMock(),
            )
        )
        self.addCleanup(
            self.stack.close
        )
        self.addCleanup(
            self.client.close
        )

    def _assert_tenant_a_scope(
        self,
    ) -> None:
        self.assertTrue(
            self.db.scalar_params
        )
        values = (
            self.db.scalar_params[
                -1
            ]
        )
        self.assertIn(
            self.company_a,
            values,
        )
        self.assertNotIn(
            self.company_b,
            values,
        )
        self.assertIn(
            self.job_b,
            values,
        )

    def test_company_a_cannot_read_company_b_job(
        self,
    ) -> None:
        with patch.object(
            api_service,
            "count_job_progress",
            AsyncMock(),
        ) as progress:
            response = self.client.get(
                f"/simple-products/imports/{self.job_b}"
            )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()
        progress.assert_not_awaited()

    def test_company_a_cannot_read_company_b_errors(
        self,
    ) -> None:
        response = self.client.get(
            f"/simple-products/imports/{self.job_b}/errors"
        )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()

    def test_company_a_cannot_download_company_b_correction(
        self,
    ) -> None:
        with patch.object(
            api_service,
            "build_correction_artifact",
            AsyncMock(),
        ) as build:
            response = self.client.get(
                f"/simple-products/imports/{self.job_b}/correction"
            )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()
        build.assert_not_awaited()

    def test_company_a_cannot_cancel_company_b_job(
        self,
    ) -> None:
        with patch.object(
            api_service,
            "cancel_import_job",
            AsyncMock(),
        ) as cancel:
            response = self.client.post(
                f"/simple-products/imports/{self.job_b}/cancel"
            )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()
        cancel.assert_not_awaited()

    def test_company_a_cannot_map_company_b_job(
        self,
    ) -> None:
        response = self.client.put(
            f"/simple-products/imports/{self.job_b}/mapping",
            json={
                "mapping": {
                    "name": "Product",
                    "unit_price": "Price",
                }
            },
        )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()

    def test_company_a_cannot_retry_company_b_job(
        self,
    ) -> None:
        with patch.object(
            api_service,
            "retry_failed_import",
            AsyncMock(),
        ) as retry:
            response = self.client.post(
                f"/simple-products/imports/{self.job_b}/retry"
            )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()
        retry.assert_not_awaited()

    def test_company_a_cannot_read_company_b_lineage(
        self,
    ) -> None:
        lineage = AsyncMock(
            return_value=None
        )
        with patch.object(
            router_module,
            "get_import_lineage",
            lineage,
        ):
            response = self.client.get(
                f"/simple-products/imports/{self.job_b}/lineage"
            )

        self.assertEqual(
            response.status_code,
            404,
        )
        lineage.assert_awaited_once()
        self.assertEqual(
            lineage.await_args.kwargs[
                "company_id"
            ],
            self.company_a,
        )
        self.assertEqual(
            lineage.await_args.kwargs[
                "job_id"
            ],
            self.job_b,
        )

    def test_company_a_correction_upload_fails_before_file_read(
        self,
    ) -> None:
        parse_upload = AsyncMock()
        with patch.object(
            router_module,
            "_parse_correction_upload",
            parse_upload,
        ):
            response = self.client.post(
                f"/simple-products/imports/{self.job_b}/correction",
                data={
                    "request_id":
                        str(
                            uuid4()
                        ),
                },
                files={
                    "file": (
                        "correction.csv",
                        b"malicious",
                        "text/csv",
                    )
                },
            )

        self.assertEqual(
            response.status_code,
            404,
        )
        self._assert_tenant_a_scope()
        parse_upload.assert_not_awaited()


class ProductImportPhase16MappingAuthorityTests(
    unittest.TestCase
):
    def test_mapping_authority_is_application_owned(
        self,
    ) -> None:
        cleaned = (
            api_service.validate_import_mapping(
                detected_headers=[
                    "Product",
                    "Price",
                ],
                mapping={
                    "name":
                        "Product",
                    "unit_price":
                        "Price",
                },
            )
        )
        self.assertEqual(
            cleaned[
                "name"
            ],
            "Product",
        )

        with self.assertRaises(
            Exception
        ) as caught:
            api_service.validate_import_mapping(
                detected_headers=[
                    "Product",
                    "Price",
                ],
                mapping={
                    "unknown":
                        "Product",
                    "unit_price":
                        "Price",
                },
            )
        self.assertEqual(
            getattr(
                caught.exception,
                "code",
                None,
            ),
            "PRODUCT_IMPORT_MAPPING_INVALID",
        )


if __name__ == "__main__":
    unittest.main()
