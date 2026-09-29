"""B3 tracking defaults remain company-bound and overrides stay fail-closed.

No API-wide/global cache: only the current single creation transaction may
hold these previously validated defaults. Verify the original public tracking
resolver returns the exact same data and bad configs/overrides still fail.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from domains.product_tracking import (
    ProductTrackingDefaults,
    ProductTrackingError,
    resolve_product_tracking_modes,
    resolve_product_tracking_modes_from_defaults,
)


class TrackingBatchB3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_and_missing_tracking_override_are_identical(self):
        defaults = ProductTrackingDefaults("REQUIRED", "OPTIONAL")
        variants = (
            (None, None),
            ("NONE", None),
            (None, "REQUIRED"),
            ("optional", "none"),
            ("REQUIRED", "REQUIRED"),
        )
        with patch(
            "domains.product_tracking.load_company_product_tracking_defaults",
            new_callable=AsyncMock,
            return_value=defaults,
        ) as loader:
            for lot, expiry in variants:
                uncached = await resolve_product_tracking_modes(
                    db=object(), company_id=38,
                    lot_control_mode=lot,
                    expiry_control_mode=expiry,
                )
                cached = resolve_product_tracking_modes_from_defaults(
                    defaults,
                    lot_control_mode=lot,
                    expiry_control_mode=expiry,
                )
                self.assertEqual(cached, uncached)
            self.assertEqual(loader.await_count, len(variants))

    async def test_both_override_codes_validate_with_original_field_errors(self):
        defaults = ProductTrackingDefaults("NONE", "REQUIRED")
        for field, lot, expiry in (
            ("lot_control_mode", "Invalid", None),
            ("expiry_control_mode", None, "Bad"),
        ):
            with self.subTest(field=field), self.assertRaises(
                ProductTrackingError,
            ) as caught:
                resolve_product_tracking_modes_from_defaults(
                    defaults,
                    lot_control_mode=lot, expiry_control_mode=expiry,
                )
            self.assertEqual(caught.exception.code, "PRODUCT_TRACKING_MODE_INVALID")
            self.assertEqual(caught.exception.context["field"], field)

    async def test_public_resolver_reloads_defaults_each_independent_request(self):
        first = ProductTrackingDefaults("NONE", "NONE")
        second = ProductTrackingDefaults("REQUIRED", "OPTIONAL")
        with patch(
            "domains.product_tracking.load_company_product_tracking_defaults",
            new_callable=AsyncMock,
            side_effect=(first, second),
        ) as loader:
            one = await resolve_product_tracking_modes(
                db=object(), company_id=2,
                lot_control_mode=None, expiry_control_mode=None,
            )
            two = await resolve_product_tracking_modes(
                db=object(), company_id=2,
                lot_control_mode=None, expiry_control_mode=None,
            )
            self.assertEqual(one, first)
            self.assertEqual(two, second)
            self.assertEqual(loader.await_count, 2)

    async def test_invalid_company_defaults_cannot_be_silently_bypassed(self):
        with patch(
            "domains.product_tracking.load_company_product_tracking_defaults",
            new_callable=AsyncMock,
            side_effect=ProductTrackingError(
                "PRODUCT_TRACKING_MODE_INVALID",
                "Company configuration invalid",
            ),
        ):
            with self.assertRaises(ProductTrackingError) as caught:
                await resolve_product_tracking_modes(
                    db=object(), company_id=2,
                    lot_control_mode="NONE", expiry_control_mode="NONE",
                )
            self.assertEqual(caught.exception.code, "PRODUCT_TRACKING_MODE_INVALID")


if __name__ == "__main__":
    unittest.main()
