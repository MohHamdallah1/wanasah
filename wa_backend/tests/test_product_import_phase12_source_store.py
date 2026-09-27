from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import os
import tracemalloc
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

from database import engine
from domains.simple_products.imports.application.source_store import (
    ProductImportSourceIntegrityError,
    ProductImportSourceMissingError,
)
from domains.simple_products.imports.application.worker import (
    run_product_import_job,
)
from domains.simple_products.imports.domain.admission import (
    ProductImportAdmissionDenied,
    ProductImportAdmissionPolicy,
)
from domains.simple_products.imports.infrastructure.capacity_monitor import (
    read_tenant_source_capacity_metrics,
)
from domains.simple_products.imports.infrastructure.postgres_source_store import (
    POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
    SOURCE_CHUNK_BYTES,
)
from domains.simple_products.imports.infrastructure.queue import (
    enqueue_new_import,
)
from domains.simple_products.imports.infrastructure.upload_stream import (
    ProductImportUploadTooLarge,
    spool_upload_bounded,
)


load_dotenv()


def _owner_dsn() -> str:
    raw = (
        os.getenv("DATABASE_URL_MIGRATION")
        or os.getenv("DATABASE_URL")
    )
    if not raw:
        raise RuntimeError(
            "Database URL is required for Phase 12 integration tests."
        )
    return (
        make_url(raw)
        .set(drivername="postgresql")
        .render_as_string(
            hide_password=False
        )
    )


def _run_async(coro):
    async def wrapped():
        try:
            return await coro
        finally:
            await engine.dispose()

    with asyncio.Runner(
        loop_factory=
            asyncio.SelectorEventLoop
    ) as runner:
        return runner.run(
            wrapped()
        )


class _SyntheticUpload:
    def __init__(
        self,
        byte_size: int,
        *,
        fill: bytes = b"x",
    ) -> None:
        self.remaining = int(
            byte_size
        )
        self.fill = bytes(
            fill
        )
        self.read_calls = 0

    async def read(
        self,
        size: int,
    ) -> bytes:
        self.read_calls += 1
        if self.remaining <= 0:
            return b""
        take = min(
            int(
                size
            ),
            self.remaining,
        )
        self.remaining -= take
        return (
            self.fill
            * take
        )


class Phase12BoundedUploadTests(
    unittest.TestCase
):
    def _measure(
        self,
        byte_size: int,
    ) -> tuple[int, str, int]:
        upload = _SyntheticUpload(
            byte_size
        )
        tracemalloc.start()
        bounded = _run_async(
            spool_upload_bounded(
                upload,
                max_bytes=
                    8
                    * 1024
                    * 1024,
            )
        )
        _current, peak = (
            tracemalloc.get_traced_memory()
        )
        tracemalloc.stop()
        try:
            return (
                int(
                    peak
                ),
                str(
                    bounded.sha256
                ),
                int(
                    upload.read_calls
                ),
            )
        finally:
            bounded.close()

    def test_upload_hash_and_size_stay_inside_fixed_memory_envelope(
        self,
    ) -> None:
        peak_1m, hash_1m, calls_1m = (
            self._measure(
                1
                * 1024
                * 1024
            )
        )
        peak_8m, hash_8m, calls_8m = (
            self._measure(
                8
                * 1024
                * 1024
            )
        )

        expected_1m = hashlib.sha256()
        for _ in range(
            16
        ):
            expected_1m.update(
                b"x"
                * (
                    64
                    * 1024
                )
            )
        expected_8m = hashlib.sha256()
        for _ in range(
            128
        ):
            expected_8m.update(
                b"x"
                * (
                    64
                    * 1024
                )
            )

        self.assertEqual(
            hash_1m,
            expected_1m.hexdigest(),
        )
        self.assertEqual(
            hash_8m,
            expected_8m.hexdigest(),
        )
        self.assertGreater(
            calls_8m,
            calls_1m,
        )
        self.assertLess(
            peak_8m,
            peak_1m
            + (
                1024
                * 1024
            ),
        )

    def test_upload_limit_stops_incrementally_above_eight_megabytes(
        self,
    ) -> None:
        upload = _SyntheticUpload(
            (
                8
                * 1024
                * 1024
            )
            + (
                64
                * 1024
            )
        )
        with self.assertRaises(
            ProductImportUploadTooLarge
        ):
            _run_async(
                spool_upload_bounded(
                    upload,
                    max_bytes=
                        8
                        * 1024
                        * 1024,
                )
            )

        self.assertLessEqual(
            upload.read_calls,
            129,
        )


class Phase12SourceStoreIntegrationTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.owner_dsn = (
            _owner_dsn()
        )
        self.created_jobs: list[
            UUID
        ] = []
        self.created_sources: list[
            UUID
        ] = []
        self.started_at = (
            datetime.now(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            fixtures = conn.execute(
                """
                SELECT
                    drivers.company_id,
                    min(drivers.id)
                FROM drivers
                WHERE drivers.is_active IS TRUE
                GROUP BY drivers.company_id
                ORDER BY drivers.company_id
                LIMIT 2
                """
            ).fetchall()
            if not fixtures:
                self.fail(
                    "Phase 12 integration tests require an active driver."
                )
            (
                self.company_id,
                self.actor_id,
            ) = map(
                int,
                fixtures[
                    0
                ],
            )
            if len(
                fixtures
            ) > 1:
                self.other_company_id = int(
                    fixtures[
                        1
                    ][
                        0
                    ]
                )
            else:
                self.other_company_id = None

        self.addCleanup(
            self._cleanup
        )

    @property
    def permissive_policy(
        self,
    ) -> ProductImportAdmissionPolicy:
        return ProductImportAdmissionPolicy(
            user_window_seconds=60,
            max_uploads_per_user_window=
                10_000,
            max_uploads_per_tenant_window=
                10_000,
            max_active_jobs_per_tenant=
                10_000,
            max_live_source_bytes_per_tenant=
                10
                * 1024
                * 1024
                * 1024,
            global_live_source_bytes=
                100
                * 1024
                * 1024
                * 1024,
            retry_after_seconds=7,
            storage_alert_percent=80,
            oldest_source_alert_seconds=
                300,
        )

    @contextmanager
    def _queue_test_context(
        self,
        policy: (
            ProductImportAdmissionPolicy
            | None
        ) = None,
    ):
        with (
            patch(
                "domains.simple_products.imports.infrastructure.queue.DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY",
                (
                    policy
                    or self.permissive_policy
                ),
            ),
            patch(
                "domains.simple_products.imports.infrastructure.queue.defer_import_on_connection",
                new=AsyncMock(),
            ),
        ):
            yield

    def _set_tenant(
        self,
        conn,
        company_id: int | None = None,
    ) -> None:
        conn.execute(
            "SELECT set_config("
            "'app.current_tenant', %s, false)",
            (
                str(
                    int(
                        company_id
                        if company_id
                        is not None
                        else self.company_id
                    )
                ),
            ),
        )

    def _enqueue(
        self,
        payload: bytes,
        *,
        request_id: UUID | None = None,
        file_name: str =
            "phase12.csv",
        policy: (
            ProductImportAdmissionPolicy
            | None
        ) = None,
    ) -> dict[str, object]:
        request = (
            request_id
            or uuid4()
        )
        with self._queue_test_context(
            policy
        ):
            result = _run_async(
                enqueue_new_import(
                    company_id=
                        self.company_id,
                    actor_id=
                        self.actor_id,
                    request_id=
                        request,
                    file_name=
                        file_name,
                    content_type=
                        "text/csv",
                    source_stream=
                        BytesIO(
                            payload
                        ),
                    source_size=
                        len(
                            payload
                        ),
                    source_sha256=
                        hashlib.sha256(
                            payload
                        ).hexdigest(),
                    default_lot_control_mode=
                        "NONE",
                    default_expiry_control_mode=
                        "NONE",
                )
            )

        job_id = UUID(
            str(
                result[
                    "job_id"
                ]
            )
        )
        if not bool(
            result[
                "replayed"
            ]
        ):
            self.created_jobs.append(
                job_id
            )
            source_id = (
                self._job_source(
                    job_id
                )[
                    0
                ]
            )
            self.created_sources.append(
                source_id
            )
        return result

    def _job_source(
        self,
        job_id: UUID,
    ) -> tuple[
        UUID,
        int,
        str,
        object,
        object,
        str,
    ]:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            row = conn.execute(
                """
                SELECT
                    source_id,
                    file_size,
                    source_sha256,
                    source_payload,
                    source_payload_cleared_at,
                    status
                FROM product_import_jobs
                WHERE company_id = %s
                  AND id = %s
                """,
                (
                    self.company_id,
                    job_id,
                ),
            ).fetchone()
        if row is None:
            raise AssertionError(
                "Test Product Import job was not found."
            )
        return (
            UUID(
                str(
                    row[
                        0
                    ]
                )
            ),
            int(
                row[
                    1
                ]
            ),
            str(
                row[
                    2
                ]
            ),
            row[
                3
            ],
            row[
                4
            ],
            str(
                row[
                    5
                ]
            ),
        )

    def _source_count(
        self,
    ) -> int:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            return int(
                conn.execute(
                    """
                    SELECT count(*)
                    FROM product_import_sources
                    WHERE company_id = %s
                      AND deleted_at IS NULL
                    """,
                    (
                        self.company_id,
                    ),
                ).fetchone()[0]
            )

    def _capacity(
        self,
    ) -> tuple[int, int]:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            tenant = conn.execute(
                """
                SELECT live_bytes
                FROM product_import_tenant_source_capacity
                WHERE company_id = %s
                """,
                (
                    self.company_id,
                ),
            ).fetchone()
            global_row = conn.execute(
                """
                SELECT live_bytes
                FROM product_import_global_source_capacity
                WHERE id = 1
                """
            ).fetchone()
        return (
            int(
                (
                    tenant[
                        0
                    ]
                    if tenant
                    else 0
                )
                or 0
            ),
            int(
                global_row[
                    0
                ]
                or 0
            ),
        )

    def _cleanup(self) -> None:
        for source_id in list(
            self.created_sources
        ):
            try:
                _run_async(
                    POSTGRES_PRODUCT_IMPORT_SOURCE_STORE.delete_source_bytes(
                        company_id=
                            self.company_id,
                        source_id=
                            source_id,
                    )
                )
            except Exception:
                pass

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            if self.created_jobs:
                conn.execute(
                    """
                    DELETE FROM product_import_jobs
                    WHERE company_id = %s
                      AND id = ANY(%s::uuid[])
                    """,
                    (
                        self.company_id,
                        [
                            str(
                                job_id
                            )
                            for job_id
                            in self.created_jobs
                        ],
                    ),
                )
            if self.created_sources:
                conn.execute(
                    """
                    DELETE FROM product_import_sources
                    WHERE company_id = %s
                      AND id = ANY(%s::uuid[])
                    """,
                    (
                        self.company_id,
                        [
                            str(
                                source_id
                            )
                            for source_id
                            in self.created_sources
                        ],
                    ),
                )
            conn.execute(
                """
                DELETE FROM product_import_admission_rejections
                WHERE company_id = %s
                  AND actor_id = %s
                  AND created_at >= %s
                """,
                (
                    self.company_id,
                    self.actor_id,
                    self.started_at
                    - timedelta(
                        seconds=2
                    ),
                ),
            )

    def test_enqueue_persists_one_immutable_source_and_replay_does_not_duplicate_it(
        self,
    ) -> None:
        payload = (
            b"Product,Unit Price\n"
            b"Tea,1.000\n"
        )
        request_id = uuid4()
        sources_before = (
            self._source_count()
        )
        capacity_before = (
            self._capacity()
        )

        first = self._enqueue(
            payload,
            request_id=
                request_id,
        )
        first_job = UUID(
            str(
                first[
                    "job_id"
                ]
            )
        )
        (
            source_id,
            source_size,
            source_hash,
            inline_payload,
            _cleared_at,
            _status,
        ) = self._job_source(
            first_job
        )

        self.assertIsNone(
            inline_payload
        )
        self.assertEqual(
            source_size,
            len(
                payload
            ),
        )
        self.assertEqual(
            source_hash,
            hashlib.sha256(
                payload
            ).hexdigest(),
        )
        self.assertEqual(
            self._source_count(),
            sources_before + 1,
        )
        capacity_after = (
            self._capacity()
        )
        self.assertEqual(
            capacity_after[
                0
            ],
            capacity_before[
                0
            ]
            + len(
                payload
            ),
        )
        self.assertEqual(
            capacity_after[
                1
            ],
            capacity_before[
                1
            ]
            + len(
                payload
            ),
        )

        verified = _run_async(
            POSTGRES_PRODUCT_IMPORT_SOURCE_STORE.read_verified_bytes(
                company_id=
                    self.company_id,
                source_id=
                    source_id,
                expected_size=
                    len(
                        payload
                    ),
                expected_sha256=
                    source_hash,
            )
        )
        self.assertEqual(
            verified,
            payload,
        )

        replay = self._enqueue(
            payload,
            request_id=
                request_id,
        )
        self.assertTrue(
            replay[
                "replayed"
            ]
        )
        self.assertEqual(
            UUID(
                str(
                    replay[
                        "job_id"
                    ]
                )
            ),
            first_job,
        )
        self.assertEqual(
            self._source_count(),
            sources_before + 1,
        )
        self.assertEqual(
            self._capacity(),
            capacity_after,
        )

    def test_source_store_is_tenant_scoped(
        self,
    ) -> None:
        if self.other_company_id is None:
            self.skipTest(
                "Second tenant is required for RLS test."
            )

        payload = (
            b"Product,Unit Price\n"
            b"Tea,1.000\n"
        )
        job = self._enqueue(
            payload
        )
        source_id, size, sha, *_ = (
            self._job_source(
                UUID(
                    str(
                        job[
                            "job_id"
                        ]
                    )
                )
            )
        )

        with self.assertRaises(
            ProductImportSourceMissingError
        ):
            _run_async(
                POSTGRES_PRODUCT_IMPORT_SOURCE_STORE.read_verified_bytes(
                    company_id=
                        int(
                            self.other_company_id
                        ),
                    source_id=
                        source_id,
                    expected_size=
                        size,
                    expected_sha256=
                        sha,
                )
            )

    def test_tampered_source_fails_hash_before_parser_runs(
        self,
    ) -> None:
        payload = (
            b"Product,Unit Price\n"
            b"Tea,1.000\n"
        )
        job = self._enqueue(
            payload
        )
        job_id = UUID(
            str(
                job[
                    "job_id"
                ]
            )
        )
        source_id, size, sha, *_ = (
            self._job_source(
                job_id
            )
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            with self.assertRaises(
                psycopg.Error
            ):
                with conn.transaction():
                    conn.execute(
                        """
                        UPDATE product_import_source_chunks
                        SET payload = decode('58','hex')
                            || substring(payload from 2)
                        WHERE company_id = %s
                          AND source_id = %s
                          AND chunk_index = 0
                        """,
                        (
                            self.company_id,
                            source_id,
                        ),
                    )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            with conn.transaction():
                conn.execute(
                    """
                    ALTER TABLE product_import_source_chunks
                    DISABLE TRIGGER
                    trg_product_import_source_chunk_immutable
                    """
                )
                conn.execute(
                    """
                    UPDATE product_import_source_chunks
                    SET payload = decode('58','hex')
                        || substring(payload from 2)
                    WHERE company_id = %s
                      AND source_id = %s
                      AND chunk_index = 0
                    """,
                    (
                        self.company_id,
                        source_id,
                    ),
                )
                conn.execute(
                    """
                    ALTER TABLE product_import_source_chunks
                    ENABLE TRIGGER
                    trg_product_import_source_chunk_immutable
                    """
                )

        with patch(
            "domains.simple_products.imports.application.worker.open_source"
        ) as parser:
            with self.assertRaises(
                ProductImportSourceIntegrityError
            ):
                _run_async(
                    run_product_import_job(
                        company_id=
                            self.company_id,
                        job_id=
                            job_id,
                        source_store=
                            POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
                    )
                )
            parser.assert_not_called()

        source_id_again, size_again, sha_again, *_ = (
            self._job_source(
                job_id
            )
        )
        self.assertEqual(
            source_id_again,
            source_id,
        )
        self.assertEqual(
            size_again,
            size,
        )
        self.assertEqual(
            sha_again,
            sha,
        )

    def test_successful_staging_deletes_source_bytes_and_releases_capacity(
        self,
    ) -> None:
        # Missing price mapping deliberately stops after staging at NEEDS_MAPPING.
        payload = (
            b"Product\n"
            b"Tea\n"
        )
        baseline = (
            self._capacity()
        )
        job = self._enqueue(
            payload
        )
        job_id = UUID(
            str(
                job[
                    "job_id"
                ]
            )
        )
        source_id, *_ = (
            self._job_source(
                job_id
            )
        )

        _run_async(
            run_product_import_job(
                company_id=
                    self.company_id,
                job_id=
                    job_id,
                source_store=
                    POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
            )
        )

        (
            _source_id,
            _size,
            _sha,
            inline_payload,
            cleared_at,
            status,
        ) = self._job_source(
            job_id
        )
        self.assertIsNone(
            inline_payload
        )
        self.assertIsNotNone(
            cleared_at
        )
        self.assertEqual(
            status,
            "NEEDS_MAPPING",
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            source = conn.execute(
                """
                SELECT
                    deleted_at,
                    (
                        SELECT count(*)
                        FROM product_import_source_chunks
                        WHERE company_id = %s
                          AND source_id = %s
                    )
                FROM product_import_sources
                WHERE company_id = %s
                  AND id = %s
                """,
                (
                    self.company_id,
                    source_id,
                    self.company_id,
                    source_id,
                ),
            ).fetchone()
        self.assertIsNotNone(
            source[
                0
            ]
        )
        self.assertEqual(
            int(
                source[
                    1
                ]
            ),
            0,
        )
        self.assertEqual(
            self._capacity(),
            baseline,
        )

    def test_admission_denial_occurs_before_source_persistence_and_is_durable(
        self,
    ) -> None:
        payload = (
            b"Product,Unit Price\n"
            b"Tea,1.000\n"
        )
        tenant_live, global_live = (
            self._capacity()
        )
        sources_before = (
            self._source_count()
        )

        policy = ProductImportAdmissionPolicy(
            user_window_seconds=60,
            max_uploads_per_user_window=
                10_000,
            max_uploads_per_tenant_window=
                10_000,
            max_active_jobs_per_tenant=
                10_000,
            max_live_source_bytes_per_tenant=(
                tenant_live
                + len(
                    payload
                )
                - 1
            ),
            global_live_source_bytes=(
                global_live
                + (
                    1024
                    * 1024
                    * 1024
                )
            ),
            retry_after_seconds=11,
            storage_alert_percent=80,
            oldest_source_alert_seconds=
                300,
        )

        with self.assertRaises(
            ProductImportAdmissionDenied
        ) as raised:
            self._enqueue(
                payload,
                policy=
                    policy,
            )

        self.assertEqual(
            raised.exception.code,
            "PRODUCT_IMPORT_TENANT_SOURCE_CAPACITY",
        )
        self.assertEqual(
            raised.exception.retry_after_seconds,
            11,
        )
        self.assertEqual(
            self._source_count(),
            sources_before,
        )
        self.assertEqual(
            self._capacity(),
            (
                tenant_live,
                global_live,
            ),
        )

        metrics = _run_async(
            read_tenant_source_capacity_metrics(
                company_id=
                    self.company_id
            )
        )
        self.assertGreaterEqual(
            metrics.quota_rejections_last_hour,
            1,
        )

    def test_postgres_source_chunks_are_bounded_and_wal_amplification_is_measured(
        self,
    ) -> None:
        payload = os.urandom(
            1024
            * 1024
        )
        with psycopg.connect(
            self.owner_dsn,
            autocommit=True,
        ) as conn:
            before = conn.execute(
                "SELECT pg_current_wal_insert_lsn()"
            ).fetchone()[0]

        job = self._enqueue(
            payload,
            file_name=
                "phase12-wal.csv",
        )
        job_id = UUID(
            str(
                job[
                    "job_id"
                ]
            )
        )
        source_id, *_ = (
            self._job_source(
                job_id
            )
        )

        with psycopg.connect(
            self.owner_dsn,
            autocommit=True,
        ) as conn:
            after = conn.execute(
                "SELECT pg_current_wal_insert_lsn()"
            ).fetchone()[0]
            wal_bytes = int(
                conn.execute(
                    """
                    SELECT pg_wal_lsn_diff(
                        %s,
                        %s
                    )::bigint
                    """,
                    (
                        after,
                        before,
                    ),
                ).fetchone()[0]
            )

        ratio = (
            wal_bytes
            / len(
                payload
            )
        )
        print(
            "PRODUCT_IMPORT_WAL_AMPLIFICATION_RATIO="
            f"{ratio:.3f}"
        )
        self.assertGreater(
            wal_bytes,
            0,
        )
        self.assertLess(
            ratio,
            64.0,
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            self._set_tenant(
                conn
            )
            (
                max_chunk,
                chunk_count,
            ) = conn.execute(
                """
                SELECT
                    max(byte_size),
                    count(*)
                FROM product_import_source_chunks
                WHERE company_id = %s
                  AND source_id = %s
                """,
                (
                    self.company_id,
                    source_id,
                ),
            ).fetchone()

        self.assertLessEqual(
            int(
                max_chunk
            ),
            SOURCE_CHUNK_BYTES,
        )
        self.assertGreater(
            int(
                chunk_count
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
