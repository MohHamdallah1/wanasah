from __future__ import annotations

import asyncio
import os
import unittest
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

from database import engine
from domains.simple_products.imports.application.audit_service import (
    get_import_lineage,
)
from domains.simple_products.imports.application.state_machine import (
    RowStatus,
)
from domains.simple_products.imports.application.retention_service import (
    run_product_import_retention,
)
from domains.simple_products.imports.domain.retention import (
    ProductImportRetentionPolicy,
)


load_dotenv()


def _owner_dsn() -> str:
    raw = (
        os.getenv("DATABASE_URL_MIGRATION")
        or os.getenv("DATABASE_URL")
    )
    if not raw:
        raise RuntimeError(
            "Database URL is required for Phase 10 integration tests."
        )
    return (
        make_url(raw)
        .set(drivername="postgresql")
        .render_as_string(
            hide_password=False
        )
    )


def _utc_naive() -> datetime:
    return (
        datetime.now(
            timezone.utc
        )
        .replace(
            tzinfo=None
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


class ProductImportRetentionAuditTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.owner_dsn = (
            _owner_dsn()
        )
        self.now = _utc_naive()
        self.jobs: list[
            tuple[int, UUID]
        ] = []

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            fixtures = (
                conn.execute(
                    """
                    SELECT
                        drivers.company_id,
                        min(drivers.id)
                    FROM drivers
                    JOIN companies
                      ON companies.id =
                            drivers.company_id
                    WHERE drivers.is_active IS TRUE
                    GROUP BY
                        drivers.company_id
                    ORDER BY
                        drivers.company_id
                    LIMIT 2
                    """
                ).fetchall()
            )
            if len(
                fixtures
            ) < 2:
                self.fail(
                    "Phase 10 retention test requires two companies with active drivers."
                )

            (
                self.company_a,
                self.driver_a,
            ) = map(
                int,
                fixtures[
                    0
                ],
            )
            (
                self.company_b,
                self.driver_b,
            ) = map(
                int,
                fixtures[
                    1
                ],
            )

            self.a_recent = (
                self._insert_job(
                    conn,
                    company_id=
                        self.company_a,
                    driver_id=
                        self.driver_a,
                    age_days=6,
                    payload=b"recent-a",
                    row_name=
                        "Recent A",
                )
            )
            self.a_payload = (
                self._insert_job(
                    conn,
                    company_id=
                        self.company_a,
                    driver_id=
                        self.driver_a,
                    age_days=8,
                    payload=b"payload-a",
                    row_name=
                        "Payload A",
                )
            )
            self.a_compact = (
                self._insert_job(
                    conn,
                    company_id=
                        self.company_a,
                    driver_id=
                        self.driver_a,
                    age_days=31,
                    payload=b"compact-a",
                    row_name=
                        "Compact A",
                    error_code=
                        "ROW_NOTE",
                    error_message=
                        "Heavy detail",
                    add_barcode=True,
                )
            )
            self.a_expired = (
                self._insert_job(
                    conn,
                    company_id=
                        self.company_a,
                    driver_id=
                        self.driver_a,
                    age_days=366,
                    payload=b"expired-a",
                    row_name=
                        "Expired A",
                )
            )

            self.b_old = (
                self._insert_job(
                    conn,
                    company_id=
                        self.company_b,
                    driver_id=
                        self.driver_b,
                    age_days=366,
                    payload=b"old-b",
                    row_name=
                        "Old B",
                    error_code=
                        "B_NOTE",
                    error_message=
                        "Must survive A cleanup",
                    add_barcode=True,
                )
            )

        self.addCleanup(
            self._cleanup
        )

    def _insert_job(
        self,
        conn,
        *,
        company_id: int,
        driver_id: int,
        age_days: int,
        payload: bytes,
        row_name: str,
        error_code: str | None = None,
        error_message: str | None = None,
        add_barcode: bool = False,
    ) -> UUID:
        job_id = uuid4()
        request_id = uuid4()
        finished_at = (
            self.now
            - timedelta(
                days=age_days
            )
        )
        source_hash = (
            uuid4().hex
            + uuid4().hex
        )[:64]

        conn.execute(
            """
            INSERT INTO product_import_jobs (
                id,
                company_id,
                request_id,
                created_by,
                file_name,
                content_type,
                source_payload,
                source_payload_cleared_at,
                source_sha256,
                file_size,
                status,
                detected_headers,
                suggested_mapping,
                column_mapping,
                default_lot_control_mode,
                default_expiry_control_mode,
                error_summary,
                total_rows,
                processed_rows,
                valid_rows,
                failed_rows,
                version,
                created_at,
                updated_at,
                started_at,
                finished_at
            )
            VALUES (
                %s,%s,%s,%s,
                %s,
                'text/csv',
                %s,
                NULL,
                %s,
                %s,
                'COMPLETED',
                '["Product","Unit Price"]'::jsonb,
                '{}'::jsonb,
                '{"name":"Product","unit_price":"Unit Price"}'::jsonb,
                'NONE',
                'NONE',
                '{}'::jsonb,
                1,1,1,0,1,
                %s,%s,%s,%s
            )
            """,
            (
                job_id,
                company_id,
                request_id,
                driver_id,
                f"phase10-{job_id}.csv",
                payload,
                source_hash,
                len(
                    payload
                ),
                finished_at,
                finished_at,
                finished_at,
                finished_at,
            ),
        )

        row = conn.execute(
            """
            INSERT INTO product_import_rows (
                company_id,
                job_id,
                row_number,
                raw_data,
                normalized_data,
                compacted_at,
                status,
                error_code,
                error_message,
                product_variant_id,
                version,
                created_at,
                updated_at
            )
            VALUES (
                %s,%s,2,
                jsonb_build_object(
                    'Product', %s,
                    'Unit Price', '1.000'
                ),
                jsonb_build_object(
                    'name', %s,
                    'unit_price', '1.000'
                ),
                NULL,
                'IMPORTED',
                %s,%s,
                NULL,
                1,%s,%s
            )
            RETURNING row_identity
            """,
            (
                company_id,
                job_id,
                row_name,
                row_name,
                error_code,
                error_message,
                finished_at,
                finished_at,
            ),
        ).fetchone()
        row_identity = UUID(
            str(
                row[
                    0
                ]
            )
        )

        if add_barcode:
            conn.execute(
                """
                INSERT INTO product_import_row_barcodes (
                    company_id,
                    job_id,
                    row_number,
                    barcode,
                    created_at
                )
                VALUES (
                    %s,%s,2,%s,%s
                )
                """,
                (
                    company_id,
                    job_id,
                    (
                        "P10"
                        + uuid4().hex[:20]
                    ),
                    finished_at,
                ),
            )

        self.jobs.append(
            (
                company_id,
                job_id,
            )
        )
        setattr(
            self,
            f"_identity_{job_id}",
            row_identity,
        )
        return job_id

    def _cleanup(self) -> None:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            for (
                company_id,
                job_id,
            ) in self.jobs:
                conn.execute(
                    """
                    DELETE FROM product_import_jobs
                    WHERE company_id = %s
                      AND id = %s
                    """,
                    (
                        company_id,
                        job_id,
                    ),
                )

    def _job_snapshot(
        self,
        *,
        company_id: int,
        job_id: UUID,
    ):
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            job = conn.execute(
                """
                SELECT
                    source_payload,
                    source_payload_cleared_at,
                    source_sha256
                FROM product_import_jobs
                WHERE company_id = %s
                  AND id = %s
                """,
                (
                    company_id,
                    job_id,
                ),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT
                    row_number,
                    row_identity,
                    status,
                    product_variant_id,
                    error_code,
                    error_message,
                    raw_data,
                    normalized_data,
                    compacted_at
                FROM product_import_rows
                WHERE company_id = %s
                  AND job_id = %s
                ORDER BY row_number
                """,
                (
                    company_id,
                    job_id,
                ),
            ).fetchall()
            barcode_count = int(
                conn.execute(
                    """
                    SELECT count(*)
                    FROM product_import_row_barcodes
                    WHERE company_id = %s
                      AND job_id = %s
                    """,
                    (
                        company_id,
                        job_id,
                    ),
                ).fetchone()[0]
            )
        return (
            job,
            rows,
            barcode_count,
        )

    def test_cleanup_applies_policy_and_never_crosses_tenant_boundary(
        self,
    ) -> None:
        (
            b_job_before,
            b_rows_before,
            b_barcodes_before,
        ) = self._job_snapshot(
            company_id=
                self.company_b,
            job_id=
                self.b_old,
        )
        (
            compact_job_before,
            compact_rows_before,
            _compact_barcodes_before,
        ) = self._job_snapshot(
            company_id=
                self.company_a,
            job_id=
                self.a_compact,
        )
        compact_identity = UUID(
            str(
                compact_rows_before[
                    0
                ][
                    1
                ]
            )
        )
        compact_hash = str(
            compact_job_before[
                2
            ]
        )

        result = _run_async(
            run_product_import_retention(
                company_id=
                    self.company_a,
                now=self.now,
            )
        )

        self.assertEqual(
            result[
                "payloads_cleared"
            ],
            3,
        )
        self.assertEqual(
            result[
                "rows_compacted"
            ],
            1,
        )
        self.assertEqual(
            result[
                "barcode_rows_pruned"
            ],
            1,
        )
        self.assertEqual(
            result[
                "lineage_rows_deleted"
            ],
            1,
        )

        (
            recent_job,
            recent_rows,
            _recent_barcodes,
        ) = self._job_snapshot(
            company_id=
                self.company_a,
            job_id=
                self.a_recent,
        )
        self.assertEqual(
            bytes(
                recent_job[
                    0
                ]
            ),
            b"recent-a",
        )
        self.assertEqual(
            recent_rows[
                0
            ][
                6
            ][
                "Product"
            ],
            "Recent A",
        )

        (
            payload_job,
            payload_rows,
            _payload_barcodes,
        ) = self._job_snapshot(
            company_id=
                self.company_a,
            job_id=
                self.a_payload,
        )
        self.assertIsNone(
            payload_job[
                0
            ]
        )
        self.assertIsNotNone(
            payload_job[
                1
            ]
        )
        self.assertEqual(
            payload_rows[
                0
            ][
                6
            ][
                "Product"
            ],
            "Payload A",
        )

        (
            compact_job,
            compact_rows,
            compact_barcodes,
        ) = self._job_snapshot(
            company_id=
                self.company_a,
            job_id=
                self.a_compact,
        )
        self.assertIsNone(
            compact_job[
                0
            ]
        )
        self.assertEqual(
            str(
                compact_job[
                    2
                ]
            ),
            compact_hash,
        )
        self.assertEqual(
            len(
                compact_rows
            ),
            1,
        )
        compacted = (
            compact_rows[
                0
            ]
        )
        self.assertEqual(
            int(
                compacted[
                    0
                ]
            ),
            2,
        )
        self.assertEqual(
            UUID(
                str(
                    compacted[
                        1
                    ]
                )
            ),
            compact_identity,
        )
        self.assertEqual(
            str(
                compacted[
                    2
                ]
            ),
            RowStatus.IMPORTED.value,
        )
        self.assertIsNone(
            compacted[
                3
            ]
        )
        self.assertEqual(
            str(
                compacted[
                    4
                ]
            ),
            "ROW_NOTE",
        )
        self.assertIsNone(
            compacted[
                5
            ]
        )
        self.assertEqual(
            compacted[
                6
            ],
            {},
        )
        self.assertEqual(
            compacted[
                7
            ],
            {},
        )
        self.assertIsNotNone(
            compacted[
                8
            ]
        )
        self.assertEqual(
            compact_barcodes,
            0,
        )

        (
            expired_job,
            expired_rows,
            _expired_barcodes,
        ) = self._job_snapshot(
            company_id=
                self.company_a,
            job_id=
                self.a_expired,
        )
        self.assertIsNotNone(
            expired_job
        )
        self.assertEqual(
            expired_rows,
            [],
        )

        (
            b_job_after,
            b_rows_after,
            b_barcodes_after,
        ) = self._job_snapshot(
            company_id=
                self.company_b,
            job_id=
                self.b_old,
        )
        self.assertEqual(
            b_job_after,
            b_job_before,
        )
        self.assertEqual(
            b_rows_after,
            b_rows_before,
        )
        self.assertEqual(
            b_barcodes_after,
            b_barcodes_before,
        )

    def test_audit_path_is_tenant_scoped_and_survives_compaction(
        self,
    ) -> None:
        _run_async(
            run_product_import_retention(
                company_id=
                    self.company_a,
                now=self.now,
            )
        )

        compacted = _run_async(
            get_import_lineage(
                company_id=
                    self.company_a,
                job_id=
                    self.a_compact,
                limit=20,
            )
        )
        self.assertIsNotNone(
            compacted
        )
        assert compacted is not None
        self.assertEqual(
            len(
                compacted[
                    "rows"
                ]
            ),
            1,
        )
        lineage_row = (
            compacted[
                "rows"
            ][
                0
            ]
        )
        self.assertEqual(
            lineage_row[
                "raw_data"
            ],
            {},
        )
        self.assertEqual(
            lineage_row[
                "normalized_data"
            ],
            {},
        )
        self.assertEqual(
            lineage_row[
                "error_code"
            ],
            "ROW_NOTE",
        )
        self.assertIsNotNone(
            lineage_row[
                "compacted_at"
            ]
        )
        self.assertFalse(
            compacted[
                "source_payload_retained"
            ]
        )
        self.assertEqual(
            len(
                str(
                    compacted[
                        "source_sha256"
                    ]
                )
            ),
            64,
        )

        expired = _run_async(
            get_import_lineage(
                company_id=
                    self.company_a,
                job_id=
                    self.a_expired,
                limit=20,
            )
        )
        self.assertIsNotNone(
            expired
        )
        assert expired is not None
        self.assertEqual(
            expired[
                "rows"
            ],
            [],
        )
        self.assertTrue(
            expired[
                "lineage_expired"
            ]
        )

        cross_tenant = _run_async(
            get_import_lineage(
                company_id=
                    self.company_a,
                job_id=
                    self.b_old,
                limit=20,
            )
        )
        self.assertIsNone(
            cross_tenant
        )

    def test_cleanup_work_is_bounded_per_run(
        self,
    ) -> None:
        extra_job = None
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            extra_job = self._insert_job(
                conn,
                company_id=
                    self.company_a,
                driver_id=
                    self.driver_a,
                age_days=8,
                payload=b"extra-a",
                row_name=
                    "Extra A",
            )

        policy = ProductImportRetentionPolicy(
            upload_bytes=
                timedelta(
                    days=7
                ),
            full_row_detail=
                timedelta(
                    days=30
                ),
            compact_lineage=
                timedelta(
                    days=365
                ),
            batch_size=1,
            max_batches_per_run=1,
        )
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            eligible_before = int(
                conn.execute(
                    """
                    SELECT count(*)
                    FROM product_import_jobs
                    WHERE company_id = %s
                      AND status IN (
                          'VALIDATION_FAILED',
                          'COMPLETED',
                          'COMPLETED_WITH_ERRORS',
                          'FAILED'
                      )
                      AND finished_at <= %s
                      AND source_payload IS NOT NULL
                    """,
                    (
                        self.company_a,
                        (
                            self.now
                            - timedelta(
                                days=7
                            )
                        ),
                    ),
                ).fetchone()[0]
            )

        result = _run_async(
            run_product_import_retention(
                company_id=
                    self.company_a,
                policy=policy,
                now=self.now,
            )
        )
        self.assertEqual(
            result[
                "payloads_cleared"
            ],
            1,
        )
        self.assertTrue(
            result[
                "batch_limit_reached"
            ]
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            eligible_after = int(
                conn.execute(
                    """
                    SELECT count(*)
                    FROM product_import_jobs
                    WHERE company_id = %s
                      AND status IN (
                          'VALIDATION_FAILED',
                          'COMPLETED',
                          'COMPLETED_WITH_ERRORS',
                          'FAILED'
                      )
                      AND finished_at <= %s
                      AND source_payload IS NOT NULL
                    """,
                    (
                        self.company_a,
                        (
                            self.now
                            - timedelta(
                                days=7
                            )
                        ),
                    ),
                ).fetchone()[0]
            )
        self.assertEqual(
            eligible_after,
            eligible_before - 1,
        )


if __name__ == "__main__":
    unittest.main()
