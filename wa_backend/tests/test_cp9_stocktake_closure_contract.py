from __future__ import annotations

import inspect
import unittest
from uuid import UUID

from api.warehouse import stocktake
from api.warehouse import locations as warehouse_locations
from domains.stocktake.contracts import (
    StocktakeApprovalCommand,
    StocktakeCancelCommand,
    StocktakeCountCommand,
    StocktakeRecountCommand,
    StocktakeStartCommand,
)
from domains.stocktake.idempotency import stocktake_request_hash


class CP9StocktakeClosureContractTests(unittest.TestCase):
    def test_all_mutation_commands_carry_durable_request_identity(self):
        commands = (
            StocktakeStartCommand(location_id=7, stocktake_type="FULL_COUNT"),
            StocktakeCountCommand(items=[]),
            StocktakeApprovalCommand(count_attempt_id=3, password="synthetic"),
            StocktakeRecountCommand(
                count_attempt_id=3,
                reason="independent recount",
                authorizer_username="supervisor",
                authorizer_password="synthetic",
            ),
            StocktakeCancelCommand(password="synthetic", reason="operator cancelled"),
        )
        for command in commands:
            self.assertIsInstance(command.request_id, UUID)

    def test_request_hash_is_stable_excludes_request_id_and_binds_target(self):
        one = StocktakeStartCommand(location_id=7, stocktake_type="FULL_COUNT")
        two = StocktakeStartCommand(location_id=7, stocktake_type="FULL_COUNT")
        self.assertNotEqual(one.request_id, two.request_id)
        self.assertEqual(stocktake_request_hash(one, target=7), stocktake_request_hash(two, target=7))
        self.assertNotEqual(stocktake_request_hash(one, target=7), stocktake_request_hash(one, target=8))

    def test_every_mutation_authorizes_before_idempotency_and_completes_before_terminal_commit(self):
        cases = {
            stocktake.start_unified_stocktake: ("stocktake.start", "STOCKTAKE_START"),
            stocktake.submit_stocktake_count: ("stocktake.count", "STOCKTAKE_COUNT"),
            stocktake.approve_stocktake_session: ("stocktake.approve", "STOCKTAKE_APPROVE"),
            stocktake.recount_stocktake_session: ("stocktake.recount", "STOCKTAKE_RECOUNT"),
            stocktake.cancel_stocktake_session: ("stocktake.cancel", "STOCKTAKE_CANCEL"),
        }
        for function, (capability, operation) in cases.items():
            source = inspect.getsource(function)
            self.assertIn(capability, source)
            self.assertIn("begin_stocktake_command(", source)
            self.assertIn(operation, source)
            self.assertIn("complete_stocktake_command(", source)
            begin_index = source.index("begin_stocktake_command(")
            complete_index = source.index("complete_stocktake_command(")
            self.assertLess(source.index(capability), begin_index)
            self.assertGreater(complete_index, begin_index)
            self.assertIn("await db.commit()", source[complete_index:])

    def test_stock_correction_remains_authoritative_movement_posting(self):
        source = inspect.getsource(stocktake.approve_stocktake_session)
        self.assertIn("post_approved_stocktake_adjustments(", source)
        self.assertNotIn("update(InventoryBalance)", source)
        self.assertNotIn("InventoryBalance.on_hand_quantity =", source)

    def test_cycle_candidates_are_tenant_location_scoped_and_public_batch_safe(self):
        source = inspect.getsource(stocktake.list_stocktake_cycle_batches)
        for marker in (
            "access.company_id",
            "InventoryLocation.id == location_id",
            "InventoryBalance.location_id == location_id",
            "ProductBatch.company_id == company_id",
            "public_batch_number(",
            "_encode_stocktake_cycle_batch_cursor(",
            "_decode_stocktake_cycle_batch_cursor(",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("__WANASAH_NOLOT__", source)

    def test_vehicle_candidates_and_start_require_exact_vehicle_location_authority(self):
        candidates = inspect.getsource(stocktake.list_vehicle_recon_candidates)
        start = inspect.getsource(stocktake.start_unified_stocktake)
        self.assertIn("access.location_filter('stocktake.start')", candidates)
        self.assertIn("InventoryLocation.location_type", candidates)
        self.assertIn('"VEHICLE"', candidates)
        self.assertIn("InventoryLocation.is_active", candidates)
        self.assertIn("resolve_vehicle_custody_location_id(", start)
        self.assertIn("expected_location_id=int(payload.location_id)", start)
        self.assertIn("require_active=True", start)
        self.assertIn("validate_vehicle_recon_work_session(", start)

    def test_count_review_recount_cancel_preserve_scope_and_evidence_contracts(self):
        count = inspect.getsource(stocktake.submit_stocktake_count)
        review = inspect.getsource(stocktake.get_stocktake_review)
        recount = inspect.getsource(stocktake.recount_stocktake_session)
        cancel = inspect.getsource(stocktake.cancel_stocktake_session)
        self.assertIn("filter_by(company_id=company_id, stocktake_session_id=session.id)", count)
        self.assertIn("StocktakeCountAttemptLine(", count)
        self.assertIn("company_id=company_id", count)
        self.assertIn("stocktake_session_id=session.id", count)
        self.assertIn("expected_quantity", review)
        self.assertIn("variance_quantity", review)
        self.assertIn("RECOUNT_REQUIRED", recount)
        self.assertIn("pending_recount_authorized_by", recount)
        self.assertIn("InventoryLock.released_at.is_(None)", cancel)
        self.assertNotIn("InventoryMovement", cancel)

    def test_cp4_non_final_stocktake_deactivation_blocker_is_still_present(self):
        source = inspect.getsource(warehouse_locations.deactivate_warehouse_location)
        self.assertIn('"OPEN_STOCKTAKE"', source)
        self.assertIn("StocktakeSession.status.in_", source)
        self.assertNotIn("StocktakeSession.status == 'POSTED'", source)
        self.assertNotIn("StocktakeSession.status == 'CANCELLED'", source)


if __name__ == "__main__":
    unittest.main()
