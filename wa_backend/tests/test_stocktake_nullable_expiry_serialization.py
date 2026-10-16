from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

from api.warehouse import stocktake
from domains.product_tracking import build_internal_no_lot_batch_number


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self


class _SequenceDB:
    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if not self._results:
            raise AssertionError("unexpected execute call")
        return self._results.pop(0)


def _anonymous_batch_number() -> str:
    return build_internal_no_lot_batch_number(
        request_id=UUID("00000000-0000-0000-0000-000000000123"),
        production_date=None,
        expiry_date=None,
    )


def _stocktake_line():
    return SimpleNamespace(
        id=501,
        product_variant_id=44,
        batch_id=99,
        stock_status="AVAILABLE",
        line_origin="SNAPSHOT",
    )


def _count_sheet_row(batch_number: str, expiry_date: date | None):
    return (
        _stocktake_line(),
        "Tracked Product",
        3,
        0,
        Decimal("1"),
        "EA",
        "Each",
        batch_number,
        expiry_date,
    )


def _attempt():
    return SimpleNamespace(
        id=701,
        attempt_number=1,
        counted_by=7,
        authorized_by=None,
        recount_of_attempt_id=None,
        recount_reason=None,
        requires_independent_recount=False,
        submitted_at=datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc),
    )


def _review_row(batch_number: str, expiry_date: date | None):
    return (
        SimpleNamespace(
            id=801,
            expected_quantity=Decimal("4"),
            actual_quantity=Decimal("4"),
            variance_quantity=Decimal("0"),
            notes=None,
        ),
        _stocktake_line(),
        "Tracked Product",
        3,
        0,
        Decimal("1"),
        "EA",
        "Each",
        batch_number,
        expiry_date,
    )


def _count_session():
    return SimpleNamespace(
        id=12,
        status="COUNTING",
        pending_independent_recount_required=False,
    )


def _review_session():
    return SimpleNamespace(
        id=12,
        reference_number="ST-12",
        stocktake_type="CYCLE_COUNT",
        status="PENDING_REVIEW",
        location_id=5,
        scope_product_variant_id=44,
        scope_batch_id=99,
        related_work_session_id=None,
        snapshot_cutoff_at=None,
    )


class StocktakeNullableExpirySerializationTests(unittest.IsolatedAsyncioTestCase):
    async def _get_count_sheet(self, *, batch_number: str, expiry_date: date | None):
        db = _SequenceDB([_Result([_count_sheet_row(batch_number, expiry_date)])])
        access = SimpleNamespace(company_id=77)
        legacy_actor = SimpleNamespace(id=7)
        with patch.object(
            stocktake,
            "_require_stocktake_capability",
            new=AsyncMock(),
        ), patch.object(
            stocktake,
            "_load_stocktake_session",
            new=AsyncMock(return_value=_count_session()),
        ):
            return await stocktake.get_stocktake_count_sheet(
                12,
                db=db,
                access=access,
                legacy_actor=legacy_actor,
            )

    async def _get_review(self, *, batch_number: str, expiry_date: date | None):
        attempt = _attempt()
        db = _SequenceDB(
            [
                _Result([attempt]),
                _Result([(7, "Counter")]),
                _Result([_review_row(batch_number, expiry_date)]),
            ]
        )
        access = SimpleNamespace(company_id=77)
        with patch.object(
            stocktake,
            "_require_stocktake_capability",
            new=AsyncMock(),
        ), patch.object(
            stocktake,
            "_load_stocktake_session",
            new=AsyncMock(return_value=_review_session()),
        ):
            return await stocktake.get_stocktake_review(
                12,
                db=db,
                access=access,
            )

    async def test_count_sheet_null_expiry_and_anonymous_batch_serialize_as_public_nulls(self):
        internal_batch = _anonymous_batch_number()
        response = await self._get_count_sheet(
            batch_number=internal_batch,
            expiry_date=None,
        )
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["batch_id"], 99)
        self.assertIsNone(response[0]["batch_number"])
        self.assertIsNone(response[0]["expiry_date"])
        self.assertNotIn(internal_batch, repr(response))

    async def test_count_sheet_real_expiry_preserves_plain_iso_date(self):
        response = await self._get_count_sheet(
            batch_number="REAL-LOT-COUNT",
            expiry_date=date(2031, 2, 3),
        )
        self.assertEqual(response[0]["batch_id"], 99)
        self.assertEqual(response[0]["batch_number"], "REAL-LOT-COUNT")
        self.assertEqual(response[0]["expiry_date"], "2031-02-03")

    async def test_review_null_expiry_and_anonymous_batch_serialize_as_public_nulls(self):
        internal_batch = _anonymous_batch_number()
        response = await self._get_review(
            batch_number=internal_batch,
            expiry_date=None,
        )
        self.assertEqual(len(response["lines"]), 1)
        self.assertEqual(response["lines"][0]["batch_id"], 99)
        self.assertIsNone(response["lines"][0]["batch_number"])
        self.assertIsNone(response["lines"][0]["expiry_date"])
        self.assertNotIn(internal_batch, repr(response))

    async def test_review_real_expiry_preserves_plain_iso_date(self):
        response = await self._get_review(
            batch_number="REAL-LOT-REVIEW",
            expiry_date=date(2032, 4, 5),
        )
        self.assertEqual(response["lines"][0]["batch_id"], 99)
        self.assertEqual(response["lines"][0]["batch_number"], "REAL-LOT-REVIEW")
        self.assertEqual(response["lines"][0]["expiry_date"], "2032-04-05")


if __name__ == "__main__":
    unittest.main()