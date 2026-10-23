import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from api.warehouse import inbound
from domains.inventory_costing.opening_valuation import (
    OpeningBatchSnapshot,
    OpeningSnapshot,
    OpeningVariantSnapshot,
    opening_preview_payload,
    preview_opening_valuation,
)
from domains.inventory_costing.service import CostingError
from schemas import (
    InventoryOpeningValuationFinalizeRequest,
    InventoryOpeningValuationPreviewRequest,
)


def snapshot(hash_value: str = "a" * 64) -> OpeningSnapshot:
    return OpeningSnapshot(
        hash=hash_value,
        total_quantity=Decimal("5"),
        variants=(
            OpeningVariantSnapshot(
                product_variant_id=1,
                sku="SKU-1",
                name="One",
                base_uom_id=1,
                base_uom_code="EACH",
                base_uom_name="Each",
                quantity=Decimal("2"),
                batches=(OpeningBatchSnapshot(1, 11, Decimal("2")),),
            ),
            OpeningVariantSnapshot(
                product_variant_id=2,
                sku="SKU-2",
                name="Two",
                base_uom_id=1,
                base_uom_code="EACH",
                base_uom_name="Each",
                quantity=Decimal("3"),
                batches=(OpeningBatchSnapshot(2, 12, Decimal("3")),),
            ),
        ),
    )


class OpeningValuationContractTests(unittest.IsolatedAsyncioTestCase):
    def test_partial_or_extra_sku_coverage_fails_closed(self):
        with self.assertRaises(CostingError) as missing:
            opening_preview_payload(
                snapshot=snapshot(),
                raw_lines=[{"sku": "SKU-1", "unit_cost": "2"}],
                currency_code="JOD",
            )
        self.assertEqual(missing.exception.code, "OPENING_VALUATION_COVERAGE_MISMATCH")
        self.assertEqual(missing.exception.context["missing_count"], 1)

        with self.assertRaises(CostingError) as extra:
            opening_preview_payload(
                snapshot=snapshot(),
                raw_lines=[
                    {"sku": "SKU-1", "unit_cost": "2"},
                    {"sku": "SKU-2", "unit_cost": "3"},
                    {"sku": "FOREIGN", "unit_cost": "9"},
                ],
                currency_code="JOD",
            )
        self.assertEqual(extra.exception.code, "OPENING_VALUATION_COVERAGE_MISMATCH")
        self.assertEqual(extra.exception.context["extra_count"], 1)

    def test_client_cannot_supply_company_identity_and_duplicate_skus_are_rejected(self):
        with self.assertRaises(ValidationError):
            InventoryOpeningValuationFinalizeRequest.model_validate(
                {
                    "request_id": "00000000-0000-0000-0000-000000000001",
                    "snapshot_hash": "a" * 64,
                    "confirm_zero_costs": False,
                    "company_id": 999,
                    "lines": [{"sku": "SKU-1", "unit_cost": "2"}],
                }
            )
        with self.assertRaises(ValidationError):
            InventoryOpeningValuationPreviewRequest.model_validate(
                {
                    "lines": [
                        {"sku": "SKU-1", "unit_cost": "2"},
                        {"sku": "SKU-1", "unit_cost": "3"},
                    ],
                }
            )

    async def test_stale_template_is_rejected_before_preview_value_is_accepted(self):
        company = SimpleNamespace(currency_code="JOD")
        policy = SimpleNamespace(method="FIFO")
        with patch(
            "domains.inventory_costing.opening_valuation.load_opening_valuation_context",
            new=AsyncMock(return_value=(company, policy, snapshot("b" * 64))),
        ):
            with self.assertRaises(CostingError) as caught:
                await preview_opening_valuation(
                    SimpleNamespace(),
                    company_id=1,
                    raw_lines=[
                        {"sku": "SKU-1", "unit_cost": "2"},
                        {"sku": "SKU-2", "unit_cost": "3"},
                    ],
                    expected_snapshot_hash="a" * 64,
                )
        self.assertEqual(caught.exception.code, "OPENING_VALUATION_TEMPLATE_STALE")

    async def test_preview_endpoint_requires_costing_manage_and_uses_access_company_only(self):
        request = InventoryOpeningValuationPreviewRequest.model_validate(
            {"lines": [{"sku": "SKU-1", "unit_cost": "2"}]}
        )
        access = SimpleNamespace(company_id=77)
        db = SimpleNamespace()
        expected = {"snapshot_hash": "a" * 64}
        with (
            patch.object(
                inbound,
                "_require_inbound_access",
                new=AsyncMock(),
            ) as require,
            patch.object(
                inbound,
                "preview_opening_valuation",
                new=AsyncMock(return_value=expected),
            ) as preview,
        ):
            result = await inbound.preview_warehouse_opening_valuation(
                request, db, access,
            )
        self.assertEqual(result, expected)
        require.assert_awaited_once_with(access, "inventory.costing.manage")
        preview.assert_awaited_once()
        self.assertEqual(preview.await_args.kwargs["company_id"], 77)


if __name__ == "__main__":
    unittest.main()
