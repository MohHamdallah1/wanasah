from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from uuid import uuid4

from openpyxl import Workbook

from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure import parsers
from domains.simple_products.imports.infrastructure.parsers import (
    MAX_IMPORT_ROWS,
    ParsedRow,
    open_source,
)
from domains.simple_products.imports.infrastructure.repository import (
    insert_staged_rows,
)


def _xlsx_payload_with_blank_row() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Product",
            "Unit Price",
        ]
    )
    sheet.append(
        [
            "Tea",
            "1.000",
        ]
    )
    sheet.append(
        [
            None,
            None,
        ]
    )
    sheet.append(
        [
            "Coffee",
            "2.000",
        ]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _csv_payload(
    count: int,
) -> bytes:
    buffer = io.BytesIO()
    buffer.write(
        b"Product,Unit Price\n"
    )
    for index in range(
        count
    ):
        buffer.write(
            (
                f"P{index},1.000\n"
            ).encode("utf-8")
        )
    return buffer.getvalue()


class ParserStreamingTests(
    unittest.TestCase
):
    def test_csv_stream_preserves_original_row_numbers(
        self,
    ) -> None:
        payload = (
            b"Product,Unit Price\n"
            b"Tea,1.000\n"
            b",\n"
            b"Coffee,2.000\n"
        )
        with open_source(
            "products.csv",
            payload,
        ) as source:
            self.assertIs(
                iter(source.rows),
                source.rows,
            )
            rows = list(
                source.rows
            )

        self.assertEqual(
            [
                row.row_number
                for row in rows
            ],
            [2, 4],
        )

    def test_xlsx_stream_preserves_original_row_numbers(
        self,
    ) -> None:
        with open_source(
            "products.xlsx",
            _xlsx_payload_with_blank_row(),
        ) as source:
            rows = list(
                source.rows
            )

        self.assertEqual(
            [
                row.row_number
                for row in rows
            ],
            [2, 4],
        )

    def test_row_limit_is_enforced_incrementally(
        self,
    ) -> None:
        yielded = 0
        with self.assertRaises(
            ProductImportTerminalError
        ):
            with open_source(
                "products.csv",
                _csv_payload(
                    MAX_IMPORT_ROWS
                    + 1
                ),
            ) as source:
                for _row in source.rows:
                    yielded += 1

        self.assertEqual(
            yielded,
            MAX_IMPORT_ROWS,
        )

    def test_xlsx_security_runs_before_workbook_traversal_and_closes(
        self,
    ) -> None:
        events: list[str] = []

        class FakeSheet:
            def iter_rows(
                self,
                *,
                values_only: bool,
            ):
                self_values = (
                    ("Product",),
                    ("Tea",),
                )
                return iter(
                    self_values
                )

        class FakeWorkbook:
            active = FakeSheet()
            closed = False

            def close(
                self,
            ) -> None:
                self.closed = True
                events.append(
                    "close"
                )

        workbook = FakeWorkbook()

        def validate(
            _payload: bytes,
        ) -> None:
            events.append(
                "validate"
            )

        def load(
            *_args,
            **_kwargs,
        ):
            events.append(
                "load"
            )
            return workbook

        with (
            patch.object(
                parsers,
                "_validate_xlsx_archive",
                validate,
            ),
            patch.object(
                parsers,
                "load_workbook",
                load,
            ),
        ):
            with open_source(
                "products.xlsx",
                b"fake",
            ) as source:
                self.assertEqual(
                    list(
                        source.rows
                    )[0].raw[
                        "Product"
                    ],
                    "Tea",
                )

        self.assertEqual(
            events,
            [
                "validate",
                "load",
                "close",
            ],
        )
        self.assertTrue(
            workbook.closed
        )

    def test_xlsx_workbook_closes_when_row_iteration_fails(
        self,
    ) -> None:
        class BrokenSheet:
            def iter_rows(
                self,
                *,
                values_only: bool,
            ):
                yield (
                    "Product",
                )
                raise RuntimeError(
                    "read failure"
                )

        class FakeWorkbook:
            active = BrokenSheet()
            closed = False

            def close(
                self,
            ) -> None:
                self.closed = True

        workbook = FakeWorkbook()

        with (
            patch.object(
                parsers,
                "_validate_xlsx_archive",
                lambda _payload: None,
            ),
            patch.object(
                parsers,
                "load_workbook",
                lambda *_args, **_kwargs:
                    workbook,
            ),
        ):
            with self.assertRaises(
                RuntimeError
            ):
                with open_source(
                    "products.xlsx",
                    b"fake",
                ) as source:
                    list(
                        source.rows
                    )

        self.assertTrue(
            workbook.closed
        )


class _FakeDb:
    def __init__(
        self,
    ) -> None:
        self.batch_sizes: list[
            int
        ] = []

    async def execute(
        self,
        _statement,
        parameters,
    ) -> None:
        self.batch_sizes.append(
            len(parameters)
        )


def _parsed_rows(
    count: int,
):
    for index in range(
        count
    ):
        yield ParsedRow(
            row_number=index + 2,
            raw={
                "Product":
                    f"P{index}",
            },
        )


class RepositoryStreamingTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_staging_batches_are_bounded_at_fifty_thousand_rows(
        self,
    ) -> None:
        db = _FakeDb()
        total = await insert_staged_rows(
            db,
            company_id=1,
            job_id=uuid4(),
            rows=_parsed_rows(
                MAX_IMPORT_ROWS
            ),
            batch_size=1_000,
            max_rows=MAX_IMPORT_ROWS,
        )

        self.assertEqual(
            total,
            MAX_IMPORT_ROWS,
        )
        self.assertEqual(
            len(db.batch_sizes),
            50,
        )
        self.assertEqual(
            max(db.batch_sizes),
            1_000,
        )
        self.assertEqual(
            min(db.batch_sizes),
            1_000,
        )

    async def test_repository_defensively_rejects_row_fifty_thousand_and_one(
        self,
    ) -> None:
        db = _FakeDb()
        with self.assertRaises(
            ProductImportTerminalError
        ):
            await insert_staged_rows(
                db,
                company_id=1,
                job_id=uuid4(),
                rows=_parsed_rows(
                    MAX_IMPORT_ROWS
                    + 1
                ),
                batch_size=1_000,
                max_rows=MAX_IMPORT_ROWS,
            )

        self.assertEqual(
            len(db.batch_sizes),
            50,
        )
        self.assertEqual(
            max(db.batch_sizes),
            1_000,
        )


if __name__ == "__main__":
    unittest.main()
