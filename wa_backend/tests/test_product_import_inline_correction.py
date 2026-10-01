"""Focused inline-correction contracts; all persistence/queue boundaries are fake.

No live database, worker, benchmark, source file or staging traffic is used.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ast
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from api.dependencies import get_current_driver
from database import get_db
from domains.simple_products.imports.application import api_service, correction_service
from domains.simple_products.imports.domain.inline_correction import (
    MAX_INLINE_CORRECTION_BYTES, InlineCorrectionError,
)
from domains.simple_products.imports.infrastructure import correction_repository as repository

router = importlib.import_module("domains.simple_products.imports.api.router")


def _production_error_handlers():
    # Execute the actual central handlers without importing main or its lifespan.
    source = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
    names = {
        "_request_id", "_error_contract", "_error_response_payload",
        "custom_http_exception_handler", "validation_exception_handler",
    }
    definitions = [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for definition in definitions:
        definition.decorator_list = []
    namespace = {
        "Request": Request, "StarletteHTTPException": StarletteHTTPException,
        "RequestValidationError": RequestValidationError, "JSONResponse": JSONResponse,
        "log_http_server_error": AsyncMock(), "get_real_ip": lambda request: "in-process",
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "main-error-handlers", "exec"), namespace)
    return namespace



class _Result:
    def __init__(self, rows=None, one=None, rowcount=1):
        self.rows = rows or []
        self.one = one
        self.rowcount = rowcount

    def all(self):
        return self.rows

    async def fetchall(self):
        return self.rows

    async def fetchone(self):
        return self.one


class _Db:
    def __init__(self, job, rows):
        self.job, self.rows = job, rows
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.job

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(rows=self.rows)


class _Transaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.events.append("BEGIN")

    async def __aexit__(self, kind, value, traceback):
        self.conn.events.append("ROLLBACK" if kind else "COMMIT")


class _Connection:
    def __init__(self, identity, *, job_version=7, row_version=3, status="INVALID", expired=False, overdue=False):
        self.identity = identity
        self.job_version, self.row_version = job_version, row_version
        self.status, self.expired = status, expired
        self.finished_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=31 if overdue else 0)
        self.events, self.sql, self.staged = [], [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def transaction(self):
        return _Transaction(self)

    def cursor(self):
        return self

    async def executemany(self, sql, values):
        self.staged.extend(values)

    async def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if "SELECT version, column_mapping" in sql:
            return _Result(one=(self.job_version, {"name": "Product", "unit_barcode": "Barcode"}, ["Product", "Barcode", "Secret"], self.finished_at))
        if "SELECT row_identity, status" in sql:
            return _Result(rows=[(self.identity, self.status, self.row_version, datetime(2026, 1, 1) if self.expired else None)])
        if "AS unknown_count" in sql:
            return _Result(one=(0, 0, 0))
        return _Result()


def _job(job_id):
    return SimpleNamespace(
        id=job_id, version=7, status="COMPLETED_WITH_ERRORS",
        finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
        column_mapping={"name": "Product", "unit_barcode": "Barcode", "not_canonical": "Secret"},
        detected_headers=["Product", "Barcode", "Secret"],
    )


def _row(number, *, expired=False, values=None):
    return SimpleNamespace(
        row_identity=uuid4(), row_number=number, version=3, status="INVALID",
        compacted_at=datetime(2026, 1, 1) if expired else None,
        values=values if values is not None else {"name": "Original", "unit_barcode": "00123"},
        error_code="IMPORT_NAME_REQUIRED",
        # Persistence diagnostics must never become response text.
        error_message="password SQL tenant-private diagnostic",
    )


class InlineCorrectionReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_projection_identity_safe_errors_and_retention(self):
        job_id = uuid4()
        rows = [_row(4), _row(17, expired=True), _row(29)]
        db = _Db(_job(job_id), rows)
        result = await api_service.read_correction_rows(
            db, company_id=101, job_id=job_id, after_row=2, limit=2,
        )
        self.assertEqual(result["fields"], ["name", "unit_barcode"])
        self.assertEqual(result["next_after_row"], 17)
        first, expired = result["items"]
        self.assertEqual((first["row_number"], first["version"]), (4, 3))
        self.assertEqual(first["row_identity"], str(rows[0].row_identity))
        self.assertEqual(first["values"]["unit_barcode"], "00123")
        self.assertEqual(first["errors"][0]["message"], "Product name is required.")
        self.assertTrue(first["editable"])
        self.assertFalse(expired["editable"])
        self.assertEqual(expired["unavailable_reason"], "ROW_DETAILS_EXPIRED")
        self.assertEqual(expired["values"], {})
        self.assertNotIn("password", json.dumps(result))
        job_query, page_query = [s.compile(dialect=postgresql.dialect()) for s in db.statements]
        self.assertIn("FOR SHARE", str(job_query))
        self.assertIn("product_import_rows.company_id =", str(page_query))
        self.assertIn("product_import_rows.job_id =", str(page_query))
        self.assertIn(["INVALID", "IMPORT_FAILED"], page_query.params.values())
        self.assertIn(101, page_query.params.values())
        self.assertIn(3, page_query.params.values())  # limit + one lookahead
        self.assertIn("jsonb_build_object", str(page_query))
        self.assertIn("octet_length", str(page_query))
        self.assertNotIn("Secret", page_query.params.values())
        self.assertNotIn("product_import_rows.error_message", str(page_query))

    async def test_byte_budget_page_cursor_and_noncorrectable_job(self):
        job_id = uuid4()
        job = _job(job_id)
        job.status = "VALIDATING"
        rows = [_row(n, values={"name": "\u0639" * 28_000}) for n in range(2, 10)]
        db = _Db(job, rows)
        result = await api_service.read_correction_rows(db, company_id=101, job_id=job_id, after_row=0, limit=8)
        self.assertLess(len(result["items"]), 8)
        self.assertEqual(result["next_after_row"], result["items"][-1]["row_number"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), MAX_INLINE_CORRECTION_BYTES)
        self.assertTrue(all(not row["editable"] for row in result["items"]))
        self.assertEqual(result["items"][0]["unavailable_reason"], "JOB_NOT_CORRECTABLE")
        rows[0].values = None
        job.status = "COMPLETED_WITH_ERRORS"
        result = await api_service.read_correction_rows(db, company_id=101, job_id=job_id, after_row=0, limit=1)
        self.assertEqual(result["items"][0]["unavailable_reason"], "ROW_VALUES_TOO_LARGE")
        self.assertEqual(result["items"][0]["values"], {})
        with self.assertRaises(InlineCorrectionError) as caught:
            await api_service.read_correction_rows(db, company_id=101, job_id=job_id, after_row=0, limit=1, expected_job_version=6)
        self.assertEqual(caught.exception.code, "PRODUCT_IMPORT_CORRECTION_STALE_JOB")
        job.finished_at -= timedelta(days=31)
        rows[0].values = {"name": "retained but overdue"}
        result = await api_service.read_correction_rows(db, company_id=101, job_id=job_id, after_row=0, limit=1)
        self.assertEqual(result["items"][0]["unavailable_reason"], "ROW_DETAILS_EXPIRED")
        self.assertEqual(result["items"][0]["values"], {})


class InlineCorrectionHttpTests(unittest.TestCase):
    def setUp(self):
        self.job_id, self.identity, self.request_id = uuid4(), uuid4(), uuid4()
        self.db = _Db(_job(self.job_id), [_row(23)])
        self.actor = SimpleNamespace(company_id=101, id=11)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        app = FastAPI()
        app.include_router(router.router)
        handlers = _production_error_handlers()
        app.add_exception_handler(StarletteHTTPException, handlers["custom_http_exception_handler"])
        app.add_exception_handler(RequestValidationError, handlers["validation_exception_handler"])

        @app.middleware("http")
        async def correlation(request, call_next):
            request.state.request_id = "inline-test-correlation"
            return await call_next(request)

        async def db_override():
            yield self.db

        async def actor_override():
            return self.actor

        app.dependency_overrides[get_db] = db_override
        app.dependency_overrides[get_current_driver] = actor_override
        self.app = app
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.permission = self.stack.enter_context(patch.object(router, "_require", AsyncMock()))
        self.apply = self.stack.enter_context(patch.object(router, "apply_inline_correction", AsyncMock(return_value={
            "job_id": str(self.job_id), "status": "VALIDATING", "corrected_rows": 1,
            "replayed": False, "message": "Correction accepted for revalidation.",
        })))
        self.url = f"/simple-products/imports/{self.job_id}/correction/rows"
        self.body = {
            "request_id": str(self.request_id), "expected_job_version": 7,
            "rows": [{"row_identity": str(self.identity), "expected_version": 3, "values": {"unit_barcode": "000123"}}],
        }

    def test_read_and_save_exact_contract_and_permissions(self):
        read = self.client.get(self.url + "?limit=1")
        self.assertEqual(read.status_code, 200)
        schema = self.app.openapi()["paths"]["/simple-products/imports/{job_id}/correction/rows"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(set(schema["required"]), {"request_id", "expected_job_version", "rows"})
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["rows"]["maxItems"], 100)
        self.assertEqual(set(schema["properties"]["rows"]["items"]["required"]), {"row_identity", "expected_version", "values"})
        item = read.json()["items"][0]
        self.assertEqual(item["row_number"], 23)
        response = self.client.post(self.url, json=self.body)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "VALIDATING")
        self.assertEqual(self.apply.await_args.kwargs["rows"], self.body["rows"])
        self.assertEqual(self.apply.await_args.kwargs["company_id"], 101)
        self.assertEqual(self.apply.await_args.kwargs["actor_id"], 11)
        self.assertEqual(self.apply.await_args.kwargs["job_id"], self.job_id)
        self.assertEqual(self.apply.await_args.kwargs["request_id"], self.request_id)
        self.assertEqual([c.args[2] for c in self.permission.await_args_list], [
            "catalog.manage", "catalog.publish", "pricing.manage",
            "catalog.manage", "catalog.publish", "pricing.manage",
        ])

    def test_permission_and_tenant_lookup_before_body_or_authority(self):
        self.permission.side_effect = HTTPException(403, detail="Forbidden")
        self.assertEqual(self.client.post(self.url, json=self.body).status_code, 403)
        self.apply.assert_not_awaited()
        self.permission.side_effect = None
        self.db.job = None
        response = self.client.post(self.url, content=b"invalid JSON", headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "PRODUCT_IMPORT_NOT_FOUND")
        self.apply.assert_not_awaited()

    def test_invalid_shape_duplicate_keys_bounds_and_literals_fail_safely(self):
        invalid = []
        for mutate in (
            lambda b: b.update(expected_job_version=True),
            lambda b: b["rows"][0].update(row_number=23),
            lambda b: b["rows"][0]["values"].update(unit_barcode=123),
            lambda b: b["rows"][0]["values"].update(name={"secret": "sql password"}),
            lambda b: b["rows"].append(dict(b["rows"][0])),
        ):
            body = json.loads(json.dumps(self.body))
            mutate(body)
            invalid.append(json.dumps(body))
        invalid.extend([
            '{"request_id":"first","request_id":"second"}',
            '{"unexpected":NaN}', json.dumps({"unexpected": "\ud800"}),
        ])
        for raw in invalid:
            with self.subTest(raw=raw[:40]):
                response = self.client.post(self.url, content=raw, headers={"content-type": "application/json"})
                self.assertEqual(response.status_code, 422)
                detail = response.json()["error"]
                self.assertEqual(detail["code"], "PRODUCT_IMPORT_CORRECTION_ROWS_INVALID")
                self.assertEqual(detail["context"]["correlation_id"], "inline-test-correlation")
                self.assertNotIn("password", json.dumps(detail))
        self.assertEqual(self.client.get(self.url + "?limit=101").status_code, 422)
        response = self.client.post(self.url, content=b"x" * (MAX_INLINE_CORRECTION_BYTES + 1), headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.post(self.url, content=b"{}").status_code, 415)
        self.apply.assert_not_awaited()

    def test_stable_conflicts_expiration_and_hidden_server_failure(self):
        for code, status in (
            ("PRODUCT_IMPORT_CORRECTION_STALE_JOB", 409),
            ("PRODUCT_IMPORT_CORRECTION_STALE_ROW", 409),
            ("PRODUCT_IMPORT_CORRECTION_REQUEST_REUSED", 409),
            ("PRODUCT_IMPORT_CORRECTION_ROW_NOT_EDITABLE", 409),
            ("PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED", 410),
            ("PRODUCT_IMPORT_CORRECTION_FIELD_INVALID", 422),
        ):
            with self.subTest(code=code):
                self.apply.side_effect = InlineCorrectionError(code)
                response = self.client.post(self.url, json=self.body)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertEqual(response.json()["error"]["context"]["correlation_id"], "inline-test-correlation")
        self.apply.side_effect = RuntimeError("private SQL password")
        with patch.object(router, "_log_api_exception"):
            response = self.client.post(self.url, json=self.body)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("password", response.text)


class InlineCorrectionAuthorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.identity, self.job_id, self.request_id = uuid4(), uuid4(), uuid4()
        self.rows = [{"row_identity": str(self.identity), "expected_version": 3, "values": {"unit_barcode": "000123"}}]

    async def invoke(self, conn, replay=None):
        with patch.object(repository.psycopg.AsyncConnection, "connect", AsyncMock(return_value=conn)), \
             patch.object(repository, "_begin_correction_idempotency", AsyncMock(return_value=replay)), \
             patch.object(repository, "_load_correctable_job_status", AsyncMock(return_value="COMPLETED_WITH_ERRORS")), \
             patch.object(repository, "defer_import_on_connection", AsyncMock()) as queue:
            try:
                result = await repository.apply_correction_and_requeue(
                    company_id=101, actor_id=11, job_id=self.job_id, request_id=self.request_id,
                    request_hash="a" * 64, corrections=None, inline_rows=self.rows, expected_job_version=7,
                )
            except InlineCorrectionError:
                queue.assert_not_awaited()
                raise
            return result, queue

    async def test_same_authority_transaction_patch_and_queue(self):
        conn = _Connection(self.identity)
        result, queue = await self.invoke(conn)
        self.assertEqual(result["status"], "VALIDATING")
        self.assertEqual(result["job_id"], str(self.job_id))
        self.assertEqual(conn.events, ["BEGIN", "COMMIT"])
        queue.assert_awaited_once_with(conn, company_id=101, job_id=self.job_id)
        identity, raw, edited_headers, version = conn.staged[0]
        self.assertEqual((identity, raw.obj, edited_headers, version), (self.identity, {"Barcode": "000123"}, ["Barcode"], 3))
        sql = "\n".join(statement for statement, params in conn.sql)
        self.assertIn("ORDER BY row_number\n        FOR UPDATE", sql)
        self.assertIn("rows.raw_data || correction.raw_data", sql)
        self.assertIn("- correction.edited_headers", sql)
        self.assertIn("rows.version = correction.expected_version", sql)
        self.assertIn("rows.compacted_at IS NULL", sql)
        update = next(s for s, p in conn.sql if "UPDATE product_import_rows" in s)
        self.assertNotIn("row_number =", update)
        self.assertNotIn("row_identity =", update.split("WHERE")[0])
        self.assertIn("'INVALID'", update)
        self.assertIn("'IMPORT_FAILED'", update)
        self.assertIn("UPDATE operation_idempotency", sql)

    async def test_stale_success_unknown_and_retained_targets_rollback_before_queue(self):
        cases = [
            ({"job_version": 8}, "PRODUCT_IMPORT_CORRECTION_STALE_JOB"),
            ({"row_version": 4}, "PRODUCT_IMPORT_CORRECTION_STALE_ROW"),
            ({"status": "IMPORTED"}, "PRODUCT_IMPORT_CORRECTION_ROW_NOT_EDITABLE"),
            ({"expired": True}, "PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED"),
            ({"overdue": True}, "PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED"),
        ]
        for kwargs, code in cases:
            with self.subTest(code=code):
                conn = _Connection(self.identity, **kwargs)
                with patch.object(repository, "defer_import_on_connection", AsyncMock()) as queue:
                    with self.assertRaises(InlineCorrectionError) as caught:
                        await self.invoke(conn)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(conn.events, ["BEGIN", "ROLLBACK"])
                    self.assertEqual(conn.staged, [])
                    queue.assert_not_awaited()
        conn = _Connection(uuid4())  # foreign job/company identities are absent under scope
        with self.assertRaises(InlineCorrectionError) as caught:
            await self.invoke(conn)
        self.assertEqual(caught.exception.code, "PRODUCT_IMPORT_CORRECTION_ROW_NOT_EDITABLE")

    async def test_completed_replay_bypasses_stale_versions_and_row_state(self):
        replay = {"job_id": str(self.job_id), "status": "VALIDATING", "corrected_rows": 1, "replayed": True}
        conn = _Connection(self.identity, job_version=999, status="IMPORTED", expired=True)
        with patch.object(repository, "_prepare_inline_corrections", AsyncMock(side_effect=AssertionError("must not load rows"))) as prepare:
            result, queue = await self.invoke(conn, replay=replay)
        self.assertEqual(result, replay)
        prepare.assert_not_awaited()
        queue.assert_not_awaited()
        self.assertEqual(conn.staged, [])

    async def test_existing_idempotency_rejects_reused_content_or_actor(self):
        for actor, content in ((12, "a" * 64), (11, "b" * 64)):
            conn = SimpleNamespace(execute=AsyncMock(return_value=_Result(one=(actor, content, {"status": "VALIDATING"}, datetime(2026, 1, 1)))))
            with self.assertRaises(InlineCorrectionError) as caught:
                await repository._begin_correction_idempotency(
                    conn, company_id=101, actor_id=11, request_id=self.request_id, request_hash="a" * 64,
                )
            self.assertEqual(caught.exception.code, "PRODUCT_IMPORT_CORRECTION_REQUEST_REUSED")

    async def test_intent_hash_stability_and_existing_file_input_compatibility(self):
        with patch.object(correction_service, "apply_correction_and_requeue", AsyncMock(return_value={})) as authority:
            for values in ({"unit_barcode": "000123", "name": "Edited"}, {"name": "Edited", "unit_barcode": "000123"}, {"name": "Edited", "unit_barcode": "123"}):
                rows = [{**self.rows[0], "values": values}]
                await correction_service.apply_correction_cells(
                    company_id=101, actor_id=11, job_id=self.job_id,
                    request_id=self.request_id, expected_job_version=7, rows=rows,
                )
            hashes = [call.kwargs["request_hash"] for call in authority.await_args_list]
            self.assertEqual(hashes[0], hashes[1])
            self.assertNotEqual(hashes[1], hashes[2])
            self.assertTrue(all(call.kwargs["corrections"] is None for call in authority.await_args_list))
        conn = _Connection(self.identity)
        raw = {"Product": "Old file value"}
        await repository._stage_corrections(conn, corrections=[{"row_identity": self.identity, "raw_data": raw}])
        self.assertEqual(conn.staged[0][1].obj, raw)
        self.assertEqual(conn.staged[0][2:], (None, None))


if __name__ == "__main__":
    unittest.main()
