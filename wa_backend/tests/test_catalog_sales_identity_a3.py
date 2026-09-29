"""A3.2: preserve concrete SKU identity when freezing driver-sale evidence.

These are isolated unit tests. No database connection, pricing publication,
accounting policy mutation, or business-rule change is involved.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from domains.sales_evidence.core import SalesEvidenceError
from domains.sales_evidence.service import freeze_sales_evidence


class CatalogSalesIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_visit_item_from_wrong_sku_before_any_write(self):
        db = SimpleNamespace(add=MagicMock(), flush=AsyncMock())
        calculation = SimpleNamespace(
            transaction_currency_code="JOD",
            rounding_policy=SimpleNamespace(currency_code="JOD"),
            lines=(SimpleNamespace(line_id=1, product_variant_id=321),),
        )
        visit = SimpleNamespace(
            current_sales_revision_id=None,
            financial_evidence_version=None,
        )
        wrong_variant_item = SimpleNamespace(
            product_variant_id=322,
            financial_evidence_version=None,
        )
        with (
            patch(
                "domains.sales_evidence.service._locked_visit",
                new_callable=AsyncMock,
                return_value=visit,
            ) as get_visit,
            patch(
                "domains.sales_evidence.service._locked_items",
                new_callable=AsyncMock,
                return_value={17: wrong_variant_item},
            ) as get_items,
        ):
            with self.assertRaises(SalesEvidenceError) as caught:
                await freeze_sales_evidence(
                    db,
                    company_id=38,
                    visit_id=11,
                    line_item_ids={1: 17},
                    calculation=calculation,
                    commercial_context_id=44,
                    functional_currency_code="JOD",
                )
        self.assertEqual(caught.exception.code, "SALES_EVIDENCE_PRODUCT_MISMATCH")
        get_visit.assert_awaited_once()
        get_items.assert_awaited_once()
        db.add.assert_not_called()
        db.flush.assert_not_awaited()

    async def test_duplicate_visit_item_assignment_rejected_before_reading_items(self):
        db = SimpleNamespace(add=MagicMock(), flush=AsyncMock())
        calculation = SimpleNamespace(
            transaction_currency_code="JOD",
            rounding_policy=SimpleNamespace(currency_code="JOD"),
            lines=(
                SimpleNamespace(line_id=1, product_variant_id=321),
                SimpleNamespace(line_id=2, product_variant_id=322),
            ),
        )
        visit = SimpleNamespace(
            current_sales_revision_id=None,
            financial_evidence_version=None,
        )
        with (
            patch(
                "domains.sales_evidence.service._locked_visit",
                new_callable=AsyncMock,
                return_value=visit,
            ),
            patch(
                "domains.sales_evidence.service._locked_items",
                new_callable=AsyncMock,
            ) as get_items,
        ):
            with self.assertRaises(SalesEvidenceError) as caught:
                await freeze_sales_evidence(
                    db,
                    company_id=38,
                    visit_id=11,
                    line_item_ids={1: 17, 2: 17},
                    calculation=calculation,
                    commercial_context_id=44,
                    functional_currency_code="JOD",
                )
        self.assertEqual(caught.exception.code, "SALES_EVIDENCE_LINE_MAPPING_INVALID")
        get_items.assert_not_awaited()
        db.add.assert_not_called()
        db.flush.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
