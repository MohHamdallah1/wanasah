from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from psycopg.errors import UniqueViolation
from sqlalchemy.engine import make_url

from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    invalidate_external_barcode_conflicts,
    invalidate_internal_duplicate_barcodes,
    open_tenant_session,
    rebuild_job_barcode_staging,
)


BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")


def _owner_dsn() -> str:
    raw = (
        os.getenv("DATABASE_URL_MIGRATION")
        or os.getenv("DATABASE_URL")
    )
    if not raw:
        raise RuntimeError(
            "Database URL is required for Phase 6 integration tests."
        )
    return (
        make_url(raw)
        .set(drivername="postgresql")
        .render_as_string(
            hide_password=False
        )
    )


class ProductImportBarcodeSqlTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.owner_dsn = _owner_dsn()
        self.job_id = uuid4()
        self.request_id = uuid4()
        marker = uuid4().hex[:16].upper()
        self.duplicate = (
            f"P6DUP{marker}"
        )
        self.conflict = (
            f"P6CONFLICT{marker}"
        )
        self.shared = (
            f"P6SHARED{marker}"
        )
        self.race = (
            f"P6RACE{marker}"
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            fixture = conn.execute(
                """
                SELECT
                    variants.company_id,
                    variants.id,
                    variants.base_uom_id,
                    drivers.id
                FROM product_variants AS variants
                JOIN drivers
                  ON drivers.company_id = variants.company_id
                 AND drivers.is_active IS TRUE
                ORDER BY variants.id
                LIMIT 1
                """
            ).fetchone()
            if fixture is None:
                self.fail(
                    "Phase 6 integration test requires one Product variant and active driver."
                )

            (
                self.company_id,
                self.variant_id,
                self.uom_id,
                self.driver_id,
            ) = map(
                int,
                fixture,
            )

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
                    version
                )
                VALUES (
                    %s,%s,%s,%s,
                    'phase6.csv',
                    'text/csv',
                    NULL,
                    %s,
                    1,
                    'VALIDATING',
                    '[]'::jsonb,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    'NONE',
                    'NONE',
                    '{}'::jsonb,
                    5,0,5,0,1
                )
                """,
                (
                    self.job_id,
                    self.company_id,
                    self.request_id,
                    self.driver_id,
                    uuid4().hex.ljust(
                        64,
                        "0",
                    )[:64],
                ),
            )

            rows = (
                (
                    2,
                    {
                        "unit_barcode":
                            self.duplicate,
                        "package_barcode":
                            None,
                    },
                ),
                (
                    3,
                    {
                        "unit_barcode":
                            self.conflict,
                        "package_barcode":
                            None,
                    },
                ),
                (
                    4,
                    {
                        "unit_barcode":
                            self.shared,
                        "package_barcode":
                            self.shared,
                    },
                ),
                (
                    5,
                    {
                        "unit_barcode":
                            self.race,
                        "package_barcode":
                            None,
                    },
                ),
                (
                    50001,
                    {
                        "unit_barcode":
                            None,
                        "package_barcode":
                            self.duplicate,
                    },
                ),
            )
            for (
                row_number,
                normalized,
            ) in rows:
                conn.execute(
                    """
                    INSERT INTO product_import_rows (
                        company_id,
                        job_id,
                        row_number,
                        raw_data,
                        normalized_data,
                        status,
                        version
                    )
                    VALUES (
                        %s,%s,%s,
                        '{}'::jsonb,
                        %s::jsonb,
                        'VALID',
                        1
                    )
                    """,
                    (
                        self.company_id,
                        self.job_id,
                        row_number,
                        json.dumps(
                            normalized
                        ),
                    ),
                )

            self._insert_active_barcode(
                conn,
                self.conflict,
            )

        self.addCleanup(
            self._cleanup
        )

    def _insert_active_barcode(
        self,
        conn,
        barcode: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO product_barcodes (
                company_id,
                product_variant_id,
                uom_id,
                barcode,
                barcode_type,
                is_primary,
                valid_from,
                valid_to,
                is_active,
                version
            )
            VALUES (
                %s,%s,%s,%s,
                'INTERNAL',
                FALSE,
                CURRENT_TIMESTAMP,
                NULL,
                TRUE,
                1
            )
            """,
            (
                self.company_id,
                self.variant_id,
                self.uom_id,
                barcode,
            ),
        )

    def _cleanup(self) -> None:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            conn.execute(
                """
                DELETE FROM product_import_jobs
                WHERE id = %s
                  AND company_id = %s
                """,
                (
                    self.job_id,
                    self.company_id,
                ),
            )
            conn.execute(
                """
                DELETE FROM product_barcodes
                WHERE company_id = %s
                  AND barcode IN (%s, %s)
                """,
                (
                    self.company_id,
                    self.conflict,
                    self.race,
                ),
            )

    async def _run_set_validation(
        self,
    ) -> tuple[int, int, int]:
        token, db = (
            await open_tenant_session(
                self.company_id
            )
        )
        try:
            staged = (
                await rebuild_job_barcode_staging(
                    db,
                    company_id=
                        self.company_id,
                    job_id=self.job_id,
                )
            )
            duplicates = (
                await invalidate_internal_duplicate_barcodes(
                    db,
                    company_id=
                        self.company_id,
                    job_id=self.job_id,
                )
            )
            conflicts = (
                await invalidate_external_barcode_conflicts(
                    db,
                    company_id=
                        self.company_id,
                    job_id=self.job_id,
                )
            )
            await db.commit()
            return (
                staged,
                duplicates,
                conflicts,
            )
        finally:
            await close_tenant_session(
                token,
                db,
            )

    def test_first_last_duplicate_external_conflict_and_shared_identity(
        self,
    ) -> None:
        (
            staged,
            duplicates,
            conflicts,
        ) = asyncio.run(
            self._run_set_validation()
        )

        self.assertEqual(
            staged,
            5,
        )
        self.assertEqual(
            duplicates,
            2,
        )
        self.assertEqual(
            conflicts,
            1,
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            statuses = dict(
                conn.execute(
                    """
                    SELECT
                        row_number,
                        status,
                        error_code
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                    ORDER BY row_number
                    """,
                    (
                        self.company_id,
                        self.job_id,
                    ),
                ).fetchall()
            )

            shared_count = (
                conn.execute(
                    """
                    SELECT count(*)
                    FROM product_import_row_barcodes
                    WHERE company_id = %s
                      AND job_id = %s
                      AND row_number = 4
                      AND barcode = %s
                    """,
                    (
                        self.company_id,
                        self.job_id,
                        self.shared,
                    ),
                ).fetchone()[0]
            )

        self.assertEqual(
            statuses[2],
            (
                "INVALID",
                "IMPORT_BARCODE_DUPLICATE",
            ),
        )
        self.assertEqual(
            statuses[50001],
            (
                "INVALID",
                "IMPORT_BARCODE_DUPLICATE",
            ),
        )
        self.assertEqual(
            statuses[3],
            (
                "INVALID",
                "IMPORT_BARCODE_CONFLICT",
            ),
        )
        self.assertEqual(
            statuses[4][0],
            "VALID",
        )
        self.assertEqual(
            statuses[5][0],
            "VALID",
        )
        self.assertEqual(
            int(shared_count),
            1,
        )

    def test_database_unique_index_closes_post_validation_race(
        self,
    ) -> None:
        asyncio.run(
            self._run_set_validation()
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            before = conn.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM product_barcodes
                    WHERE company_id = %s
                      AND barcode = %s
                      AND is_active IS TRUE
                )
                """,
                (
                    self.company_id,
                    self.race,
                ),
            ).fetchone()[0]
        self.assertFalse(before)

        with psycopg.connect(
            self.owner_dsn
        ) as racer:
            self._insert_active_barcode(
                racer,
                self.race,
            )

        importer = psycopg.connect(
            self.owner_dsn
        )
        try:
            with self.assertRaises(
                UniqueViolation
            ):
                self._insert_active_barcode(
                    importer,
                    self.race,
                )
                importer.commit()
        finally:
            importer.rollback()
            importer.close()


if __name__ == "__main__":
    unittest.main()
