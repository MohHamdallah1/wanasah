"""Explicit V1 cost-formula selection: fail-closed behavioral regression tests."""
from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from domains.inventory_costing.service import (
    CostingError,
    activate_costing_for_first_receipt,
    cost_policy_payload,
    provision_default_cost_policy,
    set_cost_policy,
)
from models import InventoryCostPolicy


def fake_policy(*, method="MOVING_AVERAGE", selected=False, active=False, version=1):
    return InventoryCostPolicy(
        company_id=38,
        method=method,
        is_active=active,
        locked_at=datetime(2026, 1, 1) if active else None,
        selected_at=datetime(2025, 12, 31) if selected else None,
        selected_by=26 if selected else None,
        version=version,
        created_by=26,
        updated_by=26,
    )


class ExplicitCostPolicyC1Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = SimpleNamespace(
            scalar=AsyncMock(return_value=Decimal("0")),
            add=MagicMock(),
            flush=AsyncMock(),
        )

    async def test_new_tenant_default_is_provisioned_but_not_selected(self):
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=None),
        ):
            policy = await provision_default_cost_policy(
                self.db, company_id=38, actor_id=26,
            )
        self.assertEqual(policy.method, "MOVING_AVERAGE")
        self.assertIsNone(policy.selected_at)
        self.assertIsNone(policy.selected_by)
        self.assertFalse(policy.is_active)
        self.db.add.assert_called_once_with(policy)

    async def test_same_default_method_requires_real_actor_confirmation(self):
        policy = fake_policy()
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=policy),
        ):
            changed = await set_cost_policy(
                self.db, company_id=38, actor_id=27, method="MOVING_AVERAGE",
                expected_version=1,
            )
        self.assertIs(changed, policy)
        self.assertIsNotNone(policy.selected_at)
        self.assertEqual(policy.selected_by, 27)
        self.assertEqual(policy.version, 2)
        self.db.flush.assert_awaited_once()

    async def test_explicit_new_fifo_selection_records_provenance(self):
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=None),
        ):
            policy = await set_cost_policy(
                self.db, company_id=38, actor_id=27, method="FIFO",
                expected_version=0,
            )
        self.assertEqual(policy.method, "FIFO")
        self.assertEqual(policy.version, 1)
        self.assertEqual(policy.selected_by, 27)
        self.assertIsNotNone(policy.selected_at)
        self.db.add.assert_called_once_with(policy)

    async def test_unchanged_selected_method_has_no_extra_version_or_write(self):
        policy = fake_policy(method="FIFO", selected=True, version=3)
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=policy),
        ):
            await set_cost_policy(
                self.db, company_id=38, actor_id=27, method="FIFO",
                expected_version=3,
            )
        self.assertEqual(policy.version, 3)
        self.assertEqual(policy.selected_by, 26)
        self.db.flush.assert_not_awaited()

    async def test_before_first_receipt_unselected_policy_is_rejected_before_stock_reads(self):
        for policy in (None, fake_policy()):
            with self.subTest(policy=policy):
                self.db.scalar.reset_mock()
                self.db.add.reset_mock()
                self.db.flush.reset_mock()
                with (
                    patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
                    patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=policy),
                ):
                    with self.assertRaises(CostingError) as caught:
                        await activate_costing_for_first_receipt(
                            self.db, company_id=38, actor_id=26,
                        )
                self.assertEqual(caught.exception.code, "INVENTORY_COST_POLICY_SELECTION_REQUIRED")
                self.assertEqual(caught.exception.status_code, 409)
                self.db.scalar.assert_not_awaited()
                self.db.add.assert_not_called()
                self.db.flush.assert_not_awaited()

    async def test_confirmed_fifo_activates_and_locks_only_once(self):
        policy = fake_policy(method="FIFO", selected=True, version=3)
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=policy),
        ):
            first = await activate_costing_for_first_receipt(
                self.db, company_id=38, actor_id=26,
            )
            second = await activate_costing_for_first_receipt(
                self.db, company_id=38, actor_id=26,
            )
        self.assertIs(first, policy)
        self.assertIs(second, policy)
        self.assertTrue(policy.is_active)
        self.assertIsNotNone(policy.locked_at)
        self.assertEqual(policy.version, 4)
        self.assertEqual(self.db.flush.await_count, 1)
        self.assertEqual(self.db.scalar.await_count, 1)

    async def test_legacy_active_method_not_changed_or_reconfirmed(self):
        policy = fake_policy(method="FIFO", selected=False, active=True, version=9)
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=policy),
        ):
            result = await activate_costing_for_first_receipt(
                self.db, company_id=38, actor_id=27,
            )
        self.assertIs(result, policy)
        self.assertEqual(policy.method, "FIFO")
        self.assertIsNone(policy.selected_at)
        self.assertEqual(policy.version, 9)
        self.db.scalar.assert_not_awaited()
        self.db.flush.assert_not_awaited()

    async def test_locked_policy_cannot_change_even_with_confirmation(self):
        policy = fake_policy(method="FIFO", selected=True, active=True, version=9)
        with (
            patch("domains.inventory_costing.service._policy_guard", new_callable=AsyncMock),
            patch("domains.inventory_costing.service.get_cost_policy", new_callable=AsyncMock, return_value=policy),
        ):
            with self.assertRaises(CostingError) as caught:
                await set_cost_policy(
                    self.db, company_id=38, actor_id=27, method="MOVING_AVERAGE",
                    expected_version=9,
                )
        self.assertEqual(caught.exception.code, "INVENTORY_COST_POLICY_LOCKED")
        self.assertEqual(policy.method, "FIFO")
        self.db.flush.assert_not_awaited()

    async def test_unselected_cost_policy_read_hides_implicit_default(self):
        for policy in (None, fake_policy()):
            with self.subTest(policy=policy):
                self.db.scalar.return_value = SimpleNamespace(currency_code="JOD")
                with patch(
                    "domains.inventory_costing.service.get_cost_policy",
                    new_callable=AsyncMock,
                    return_value=policy,
                ):
                    payload = await cost_policy_payload(
                        self.db, company_id=38, can_change=True,
                    )
                self.assertIsNone(payload["method"])
                self.assertFalse(payload["is_selected"])
                self.assertEqual(payload["selection_status"], "UNSELECTED")
                self.assertTrue(payload["can_change"])

    async def test_legacy_active_policy_read_preserves_history(self):
        policy = fake_policy(method="FIFO", active=True)
        self.db.scalar.return_value = SimpleNamespace(currency_code="JOD")
        with patch(
            "domains.inventory_costing.service.get_cost_policy",
            new_callable=AsyncMock,
            return_value=policy,
        ):
            payload = await cost_policy_payload(
                self.db, company_id=38, can_change=True,
            )
        self.assertEqual(payload["method"], "FIFO")
        self.assertTrue(payload["is_selected"])
        self.assertEqual(payload["selection_status"], "LEGACY_ACTIVE")
        self.assertFalse(payload["can_change"])


if __name__ == "__main__":
    unittest.main()
