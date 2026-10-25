import ast
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TRANSFERS_PATH = BACKEND_ROOT / "api" / "warehouse" / "transfers.py"
POLICY_PATH = BACKEND_ROOT / "api" / "warehouse" / "transfer_policy.py"

TRANSFERS_SOURCE = TRANSFERS_PATH.read_text(encoding="utf-8")
POLICY_SOURCE = POLICY_PATH.read_text(encoding="utf-8")
TRANSFERS_TREE = ast.parse(TRANSFERS_SOURCE)
POLICY_TREE = ast.parse(POLICY_SOURCE)


TRANSFER_ROUTES = {
    "change_batch_disposition",
    "change_inventory_status",
    "list_unified_transfer_locations",
    "get_unified_transfer_source_inventory",
    "get_unified_transfer_override_options",
    "list_unified_transfers",
    "get_unified_transfer_detail",
    "special_transfer_dispatch",
    "stage_inventory_quality_handling",
    "confirm_inventory_disposal",
    "confirm_inventory_vendor_handover",
    "unified_transfer_dispatch",
    "unified_transfer_receive",
    "unified_transfer_cancel",
    "unified_transfer_reject",
}

TRANSFER_MUTATIONS = {
    "change_batch_disposition",
    "change_inventory_status",
    "special_transfer_dispatch",
    "stage_inventory_quality_handling",
    "confirm_inventory_disposal",
    "confirm_inventory_vendor_handover",
    "unified_transfer_dispatch",
    "unified_transfer_receive",
    "unified_transfer_cancel",
    "unified_transfer_reject",
}

TRANSFER_READS = TRANSFER_ROUTES - TRANSFER_MUTATIONS

POLICY_ROUTES = {
    "get_transfer_destination_policy",
    "save_transfer_destination_policy",
    "publish_transfer_destination_policy_endpoint",
}
POLICY_MUTATIONS = {
    "save_transfer_destination_policy",
    "publish_transfer_destination_policy_endpoint",
}


def _function_map(tree: ast.AST) -> dict[str, ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }


def _segment(source: str, node: ast.AST) -> str:
    segment = ast.get_source_segment(source, node)
    assert segment is not None
    return segment


def _arg_names(node: ast.AsyncFunctionDef) -> set[str]:
    return {
        arg.arg
        for arg in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        )
    }


def _call_count(tree: ast.AST, name: str) -> int:
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == name:
            count += 1
        elif isinstance(node.func, ast.Attribute) and node.func.attr == name:
            count += 1
    return count


class WarehouseTransfersCanonicalAuthCutoverTests(unittest.TestCase):
    def test_runtime_files_have_no_legacy_request_authority(self):
        forbidden = (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            "current_admin",
            ".is_admin",
            "legacy_actor.company_id",
        )
        for path, source in (
            (TRANSFERS_PATH, TRANSFERS_SOURCE),
            (POLICY_PATH, POLICY_SOURCE),
        ):
            with self.subTest(path=path.name):
                for token in forbidden:
                    self.assertNotIn(token, source)
                self.assertIn(
                    "get_current_backoffice_capability_access",
                    source,
                )
                self.assertIn("BackofficeCapabilityAccess", source)

    def test_all_routes_use_canonical_access_and_only_mutations_load_legacy_actor(self):
        transfer_functions = _function_map(TRANSFERS_TREE)
        self.assertTrue(TRANSFER_ROUTES <= set(transfer_functions))
        for name in TRANSFER_ROUTES:
            args = _arg_names(transfer_functions[name])
            self.assertIn("access", args, name)
            if name in TRANSFER_MUTATIONS:
                self.assertIn("legacy_actor", args, name)
            else:
                self.assertNotIn("legacy_actor", args, name)

        policy_functions = _function_map(POLICY_TREE)
        self.assertTrue(POLICY_ROUTES <= set(policy_functions))
        for name in POLICY_ROUTES:
            args = _arg_names(policy_functions[name])
            self.assertIn("access", args, name)
            if name in POLICY_MUTATIONS:
                self.assertIn("legacy_actor", args, name)
            else:
                self.assertNotIn("legacy_actor", args, name)

    def test_tenant_authority_is_canonical_access_and_ids_are_not_aliased(self):
        combined = TRANSFERS_SOURCE + "\n" + POLICY_SOURCE
        self.assertIn("company_id = access.company_id", TRANSFERS_SOURCE)
        self.assertIn("company_id=access.company_id", POLICY_SOURCE)
        self.assertNotIn("company_id=legacy_actor", combined)
        self.assertNotIn("legacy_actor.company_id", combined)
        self.assertNotIn("principal_id", combined)
        self.assertNotIn("backoffice_user_id", combined)

        for tree in (TRANSFERS_TREE, POLICY_TREE):
            attrs = {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "legacy_actor"
            }
            self.assertLessEqual(attrs, {"id"})

    def test_canonical_owner_and_ordinary_grants_share_same_authority_path(self):
        combined = TRANSFERS_SOURCE + "\n" + POLICY_SOURCE
        self.assertNotIn("is_company_owner", combined)
        self.assertNotIn("is_admin", combined)
        self.assertNotIn("manager", combined.lower())
        self.assertNotIn("supervisor", combined.lower())
        self.assertIn("await access.require(", TRANSFERS_SOURCE)
        self.assertIn("await access.require(", POLICY_SOURCE)
        self.assertIn("BackofficeCapabilityAccessRejected", combined)

    def test_transfer_scope_guards_and_read_filter_are_canonical(self):
        functions = _function_map(TRANSFERS_TREE)
        list_segment = _segment(
            TRANSFERS_SOURCE,
            functions["list_unified_transfers"],
        )
        detail_segment = _segment(
            TRANSFERS_SOURCE,
            functions["get_unified_transfer_detail"],
        )
        receive_segment = _segment(
            TRANSFERS_SOURCE,
            functions["unified_transfer_receive"],
        )
        cancel_segment = _segment(
            TRANSFERS_SOURCE,
            functions["unified_transfer_cancel"],
        )
        reject_segment = _segment(
            TRANSFERS_SOURCE,
            functions["unified_transfer_reject"],
        )

        self.assertIn("transfer_filter(access)", list_segment)
        self.assertIn(
            "_require_transfer_document(access, 'transfer.read', header_id)",
            detail_segment,
        )
        self.assertIn(
            "'transfer.receive', payload.transfer_header_id, 'destination'",
            receive_segment,
        )
        self.assertIn(
            "'transfer.cancel', header_id, 'source'",
            cancel_segment,
        )
        self.assertIn(
            "'transfer.reject', header_id, 'destination'",
            reject_segment,
        )

    def test_exact_direct_capability_mapping_is_preserved(self):
        direct_capabilities = {
            "batch.disposition",
            "inventory.status_change",
            "inventory.transfer_policy.manage",
            "transfer.read",
            "transfer.send",
            "transfer.receive",
            "transfer.cancel",
            "transfer.reject",
            "transfer.destination",
            "inventory.fefo_override",
            "inventory.disposal.confirm",
            "inventory.vendor_return.confirm",
            "transfer.warehouse_balancing_override",
        }
        combined = TRANSFERS_SOURCE + "\n" + POLICY_SOURCE
        for capability in direct_capabilities:
            with self.subTest(capability=capability):
                double = f'"{capability}"'
                single = f"'{capability}'"
                self.assertTrue(double in combined or single in combined)

        # Special-purpose capabilities retain the existing centralized mapping;
        # this cutover must not duplicate or rename that catalog.
        self.assertIn("SPECIAL_TRANSFER_PERMISSION", TRANSFERS_SOURCE)
        functions = _function_map(TRANSFERS_TREE)
        for name in (
            "special_transfer_dispatch",
            "stage_inventory_quality_handling",
            "unified_transfer_receive",
            "unified_transfer_cancel",
            "unified_transfer_reject",
        ):
            self.assertIn(
                "SPECIAL_TRANSFER_PERMISSION",
                _segment(TRANSFERS_SOURCE, functions[name]),
                name,
            )

    def test_transfer_policy_manage_keeps_any_location_and_location_read_semantics(self):
        functions = _function_map(POLICY_TREE)
        for name in POLICY_ROUTES:
            segment = _segment(POLICY_SOURCE, functions[name])
            self.assertIn(
                '"inventory.transfer_policy.manage"',
                segment,
                name,
            )
            self.assertIn("any_location=True", segment, name)

        helper = _segment(
            POLICY_SOURCE,
            functions["_require_transfer_policy_location_access"],
        )
        self.assertIn('"location.read"', helper)

    def test_legacy_driver_is_operational_provenance_only(self):
        required_provenance = (
            "actor_id=legacy_actor.id",
            "performed_by=legacy_actor.id",
            "dispatched_by=legacy_actor.id",
            "admin_id=legacy_actor.id",
            "override_actor_id = legacy_actor.id",
            "header.received_by = legacy_actor.id",
            "header.cancelled_by = legacy_actor.id",
            "header.dispatched_by == legacy_actor.id",
        )
        for token in required_provenance:
            self.assertIn(token, TRANSFERS_SOURCE)

        self.assertIn("actor_id=legacy_actor.id", POLICY_SOURCE)
        self.assertNotIn(
            "access = BackofficeCapabilityAccess(db, legacy_actor)",
            TRANSFERS_SOURCE,
        )
        self.assertNotIn(
            "access = BackofficeCapabilityAccess(db, legacy_actor)",
            POLICY_SOURCE,
        )

    def test_read_endpoints_do_not_load_operational_driver(self):
        transfer_functions = _function_map(TRANSFERS_TREE)
        for name in TRANSFER_READS:
            segment = _segment(TRANSFERS_SOURCE, transfer_functions[name])
            self.assertNotIn(
                "get_current_backoffice_legacy_driver",
                segment,
                name,
            )
            self.assertNotIn("legacy_actor", segment, name)

        policy_read = _segment(
            POLICY_SOURCE,
            _function_map(POLICY_TREE)["get_transfer_destination_policy"],
        )
        self.assertNotIn("legacy_actor", policy_read)
        self.assertNotIn("get_current_backoffice_legacy_driver", policy_read)

    def test_owner_cannot_bypass_structural_business_invariants(self):
        structural_markers = (
            "_verify_location_ownership(",
            "acquire_product_lifecycle_guards(",
            "acquire_inventory_location_guards(",
            "allocate_fefo_inventory_batch(",
            "batch_sellability_predicate(",
            "_load_locked_in_transit_transfer(",
            "validate_special_transfer_policy_snapshot(",
        )
        for marker in structural_markers:
            self.assertIn(marker, TRANSFERS_SOURCE)
        self.assertNotIn("if access.subject.is_company_owner", TRANSFERS_SOURCE)
        self.assertNotIn("if access.is_company_owner", TRANSFERS_SOURCE)

    def test_locking_idempotency_state_machine_and_sod_contracts_are_preserved(self):
        self.assertEqual(
            _call_count(TRANSFERS_TREE, "begin_idempotent_operation"),
            10,
        )
        self.assertEqual(
            _call_count(TRANSFERS_TREE, "complete_idempotent_operation"),
            11,
        )
        self.assertEqual(_call_count(TRANSFERS_TREE, "with_for_update"), 3)
        self.assertEqual(
            _call_count(POLICY_TREE, "begin_idempotent_operation"),
            2,
        )
        self.assertEqual(
            _call_count(POLICY_TREE, "complete_idempotent_operation"),
            2,
        )

        for state in ("IN_TRANSIT", "POSTED", "CANCELLED", "REJECTED"):
            self.assertIn(state, TRANSFERS_SOURCE)
        self.assertIn(
            "header.dispatched_by == legacy_actor.id",
            TRANSFERS_SOURCE,
        )

    def test_cross_company_and_wrong_location_fail_closed_sources_remain(self):
        self.assertIn(
            "InventoryLocation.company_id == access.company_id",
            TRANSFERS_SOURCE,
        )
        self.assertIn(
            "InventoryLocation.company_id == access.company_id",
            POLICY_SOURCE,
        )
        self.assertIn(
            "InventoryLocation.company_id == company_id",
            TRANSFERS_SOURCE,
        )
        self.assertIn("company_id=company_id", TRANSFERS_SOURCE)
        self.assertIn("status_code=403", TRANSFERS_SOURCE)
        self.assertIn("status_code=404", TRANSFERS_SOURCE)


if __name__ == "__main__":
    unittest.main()
