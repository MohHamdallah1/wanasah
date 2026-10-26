from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from api import suppliers as supplier_api
from api.warehouse import inbound, whole_product_quality
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.suppliers.errors import SupplierError
from domains.suppliers import public as supplier_public


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATHS = (
    ROOT / "api" / "suppliers.py",
    ROOT / "domains" / "suppliers" / "public.py",
    ROOT / "domains" / "suppliers" / "application.py",
    ROOT / "api" / "warehouse" / "inbound.py",
    ROOT / "api" / "warehouse" / "whole_product_quality.py",
)


class _ScalarDB:
    def __init__(self, *values):
        self.values = list(values)
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError("Unexpected scalar query")
        return self.values.pop(0)


class _NoDB:
    def __getattr__(self, name):
        raise AssertionError(f"Canonical Owner must not need grant storage: {name}")


class _SupplierDB:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.row


def _subject(*, owner: bool, company_id: int = 77):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=company_id,
        is_company_owner=owner,
        legacy_grant_driver_id=None if owner else 909,
    )


def _owner_access(*, company_id: int = 77):
    return BackofficeCapabilityAccess(
        db=_NoDB(),
        subject=_subject(owner=True, company_id=company_id),
    )


def _ordinary_access(db, *, company_id: int = 77):
    return BackofficeCapabilityAccess(
        db=db,
        subject=_subject(owner=False, company_id=company_id),
    )


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class SupplierCanonicalAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_owner_requires_no_supplier_grant_row(self):
        access = _owner_access()
        await supplier_public.require_supplier_permission(access, "supplier.read")
        await supplier_public.require_supplier_permission(access, "supplier.manage")
        self.assertEqual(access.company_id, 77)

    async def test_ordinary_supplier_grant_and_missing_grant(self):
        allowed_db = _ScalarDB(True)
        access = _ordinary_access(allowed_db)
        await supplier_public.require_supplier_permission(access, "supplier.read")
        self.assertEqual(len(allowed_db.statements), 1)

        denied_db = _ScalarDB(False)
        denied = _ordinary_access(denied_db)
        with self.assertRaises(SupplierError) as caught:
            await supplier_public.require_supplier_permission(denied, "supplier.manage")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.code, "SUPPLIER_PERMISSION_DENIED")
        self.assertEqual(caught.exception.context["permission"], "supplier.manage")

    async def test_active_selection_rejects_inactive_but_historical_snapshot_keeps_it(self):
        inactive = SimpleNamespace(id=31, name="Historical Supplier", code="SUP-31", is_active=False)

        active_db = _SupplierDB(inactive)
        with self.assertRaises(SupplierError) as caught:
            await supplier_public.select_active_supplier(
                active_db,
                access=_owner_access(company_id=77),
                supplier_id=31,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.code, "SUPPLIER_INACTIVE")
        self.assertIn("suppliers.company_id = 77", _sql(active_db.statements[0]))
        self.assertIn("suppliers.id = 31", _sql(active_db.statements[0]))
        self.assertIn("FOR SHARE", _sql(active_db.statements[0]))

        history_db = _SupplierDB(inactive)
        snapshot = await supplier_public.select_supplier_snapshot(
            history_db,
            access=_owner_access(company_id=77),
            supplier_id=31,
        )
        self.assertEqual((snapshot.id, snapshot.name, snapshot.code), (31, "Historical Supplier", "SUP-31"))
        self.assertIn("suppliers.company_id = 77", _sql(history_db.statements[0]))
        self.assertIn("FOR SHARE", _sql(history_db.statements[0]))

    def test_supplier_routes_keep_read_driver_free_and_mutations_use_legacy_provenance(self):
        reads = (supplier_api.suppliers, supplier_api.supplier)
        mutations = (
            supplier_api.create_supplier,
            supplier_api.update_supplier,
            supplier_api.supplier_state,
        )
        for route in reads:
            params = inspect.signature(route).parameters
            self.assertIn("access", params)
            self.assertNotIn("legacy_actor", params)
            self.assertIs(
                params["access"].default.dependency,
                get_current_backoffice_capability_access,
            )
        for route in mutations:
            params = inspect.signature(route).parameters
            self.assertIs(
                params["access"].default.dependency,
                get_current_backoffice_capability_access,
            )
            self.assertIs(
                params["legacy_actor"].default.dependency,
                get_current_backoffice_legacy_driver,
            )


class InboundCanonicalAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_and_ordinary_exact_location_authority(self):
        owner_db = _ScalarDB(41)
        owner = BackofficeCapabilityAccess(
            db=owner_db,
            subject=_subject(owner=True, company_id=77),
        )
        await inbound._require_inbound_access(owner, "inbound.create", 41)
        self.assertEqual(len(owner_db.statements), 1)
        self.assertIn("inventory_locations.company_id = 77", _sql(owner_db.statements[0]))
        self.assertIn("inventory_locations.id = 41", _sql(owner_db.statements[0]))

        ordinary_db = _ScalarDB(41, True)
        ordinary = _ordinary_access(ordinary_db)
        await inbound._require_inbound_access(ordinary, "inbound.create", 41)
        self.assertEqual(len(ordinary_db.statements), 2)

    async def test_missing_capability_is_403_and_foreign_location_is_404(self):
        denied_db = _ScalarDB(41, False, 41)
        denied = _ordinary_access(denied_db)
        with self.assertRaises(HTTPException) as denied_error:
            await inbound._require_inbound_access(denied, "inbound.create", 41)
        self.assertEqual(denied_error.exception.status_code, 403)

        foreign_db = _ScalarDB(None, None)
        foreign = _ordinary_access(foreign_db)
        with self.assertRaises(HTTPException) as foreign_error:
            await inbound._require_inbound_access(foreign, "inbound.create", 999)
        self.assertEqual(foreign_error.exception.status_code, 404)
        for statement in foreign_db.statements:
            sql = _sql(statement)
            self.assertIn("inventory_locations.company_id = 77", sql)
            self.assertIn("inventory_locations.id = 999", sql)

    async def test_company_any_location_semantics_remain_capability_gated(self):
        allowed_db = _ScalarDB(True)
        allowed = _ordinary_access(allowed_db)
        await inbound._require_inbound_access(
            allowed,
            "inbound.create",
            any_location=True,
        )

        denied_db = _ScalarDB(False)
        denied = _ordinary_access(denied_db)
        with self.assertRaises(HTTPException) as caught:
            await inbound._require_inbound_access(
                denied,
                "inbound.create",
                any_location=True,
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_read_only_inbound_routes_do_not_load_legacy_driver(self):
        for route in (inbound.warehouse_inbound_options, inbound.warehouse_costing_policy):
            params = inspect.signature(route).parameters
            self.assertIn("access", params)
            self.assertNotIn("legacy_actor", params)
            self.assertIs(
                params["access"].default.dependency,
                get_current_backoffice_capability_access,
            )
        for route in (
            inbound.update_warehouse_costing_policy,
            inbound.finalize_warehouse_opening_valuation,
            inbound.warehouse_inbound,
        ):
            params = inspect.signature(route).parameters
            self.assertIs(
                params["access"].default.dependency,
                get_current_backoffice_capability_access,
            )
            self.assertIs(
                params["legacy_actor"].default.dependency,
                get_current_backoffice_legacy_driver,
            )


class WholeProductQualityCanonicalAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_affected_location_permission_bundle(self):
        terminal = "inventory.disposal.confirm"

        class Access:
            async def codes_by_location(self, location_ids):
                self.location_ids = list(location_ids)
                return {
                    11: ["inventory.read", "transfer.send", terminal],
                    12: ["inventory.read", "transfer.send", terminal],
                }

        allowed = Access()
        await whole_product_quality._require_location_authority(
            allowed,
            [11, 12],
            {11: "A", 12: "B"},
            terminal,
        )
        self.assertEqual(allowed.location_ids, [11, 12])

        class DeniedAccess:
            async def codes_by_location(self, location_ids):
                return {
                    11: ["inventory.read", "transfer.send", terminal],
                    12: ["inventory.read", terminal],
                }

        with self.assertRaises(HTTPException) as caught:
            await whole_product_quality._require_location_authority(
                DeniedAccess(),
                [11, 12],
                {11: "A", 12: "B"},
                terminal,
            )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(
            caught.exception.detail["code"],
            "WHOLE_PRODUCT_QUALITY_LOCATION_PERMISSION_DENIED",
        )
        self.assertEqual(
            caught.exception.detail["context"]["locations"],
            [{"location_id": 12, "location_name": "B"}],
        )

    async def test_special_transfer_permission_missing_is_403(self):
        permission = whole_product_quality.SPECIAL_TRANSFER_PERMISSION["DISPOSAL"]
        allowed_db = _ScalarDB(True)
        await whole_product_quality._require_quality_access(
            _ordinary_access(allowed_db),
            permission,
        )

        denied_db = _ScalarDB(False)
        with self.assertRaises(HTTPException) as caught:
            await whole_product_quality._require_quality_access(
                _ordinary_access(denied_db),
                permission,
            )
        self.assertEqual(caught.exception.status_code, 403)


class CanonicalCutoverSourceProofTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            path: path.read_text(encoding="utf-8")
            for path in RUNTIME_PATHS
        }
        self.all_source = "\n".join(self.sources.values())

    def test_zero_legacy_request_authority_patterns(self):
        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "actor.company_id",
            "current_admin.company_id",
            "legacy_actor.company_id",
        ):
            self.assertNotIn(forbidden, self.all_source, forbidden)

    def test_canonical_company_and_independent_legacy_provenance_are_explicit(self):
        supplier_api_source = self.sources[ROOT / "api" / "suppliers.py"]
        application_source = self.sources[ROOT / "domains" / "suppliers" / "application.py"]
        inbound_source = self.sources[ROOT / "api" / "warehouse" / "inbound.py"]
        quality_source = self.sources[ROOT / "api" / "warehouse" / "whole_product_quality.py"]

        self.assertIn("list_suppliers(db, access.company_id", supplier_api_source)
        self.assertIn("load_supplier(db, access.company_id", supplier_api_source)
        self.assertIn("company_id = int(access.company_id)", application_source)
        self.assertIn("actor_id = int(legacy_actor.id)", inbound_source)
        self.assertIn("company_id = int(access.company_id)", inbound_source)
        self.assertIn("actor_id = int(legacy_actor.id)", quality_source)
        self.assertIn("company_id = int(access.company_id)", quality_source)
        self.assertNotIn("principal_id", inbound_source)
        self.assertNotIn("backoffice_user_id", inbound_source)
        self.assertNotIn("principal_id", quality_source)
        self.assertNotIn("backoffice_user_id", quality_source)

    def test_exact_capability_mapping_is_preserved(self):
        supplier_source = (
            self.sources[ROOT / "api" / "suppliers.py"]
            + self.sources[ROOT / "domains" / "suppliers" / "public.py"]
            + self.sources[ROOT / "domains" / "suppliers" / "application.py"]
        )
        inbound_source = self.sources[ROOT / "api" / "warehouse" / "inbound.py"]
        quality_source = self.sources[ROOT / "api" / "warehouse" / "whole_product_quality.py"]

        self.assertIn('permission="supplier.read"', supplier_source)
        self.assertIn('"supplier.manage"', supplier_source)
        self.assertIn("'inbound.create'", inbound_source)
        self.assertIn("'inventory.costing.manage'", inbound_source)
        self.assertIn("require_supplier_permission(access)", inbound_source)
        self.assertIn("SPECIAL_TRANSFER_PERMISSION[purpose]", quality_source)
        self.assertIn('{"inventory.read", "transfer.send", terminal_permission}', quality_source)
        self.assertIn('"inventory.disposal.confirm"', quality_source)
        self.assertIn('"inventory.vendor_return.confirm"', quality_source)
        self.assertIn("require_supplier_permission(access)", quality_source)

    def test_mutation_legacy_driver_is_only_provenance_and_confirmation_is_canonical(self):
        supplier_source = self.sources[ROOT / "api" / "suppliers.py"]
        inbound_source = self.sources[ROOT / "api" / "warehouse" / "inbound.py"]
        quality_source = self.sources[ROOT / "api" / "warehouse" / "whole_product_quality.py"]

        self.assertEqual(supplier_source.count("legacy_actor.id"), 3)
        tree = ast.parse(inbound_source)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        permitted = {
            "update_warehouse_costing_policy": {
                ("begin_idempotent_operation", "actor_id"),
                ("set_cost_policy", "actor_id"),
            },
            "finalize_warehouse_opening_valuation": {
                ("begin_idempotent_operation", "actor_id"),
                ("finalize_opening_valuation", "actor_id"),
            },
            "warehouse_inbound": {
                ("begin_idempotent_operation", "actor_id"),
                ("_ensure_first_inbound_product_locations", "actor_id"),
                ("activate_costing_for_first_receipt", "actor_id"),
                ("apply_inventory_movements_batch", "performed_by"),
            },
        }
        provenance_functions = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name) or node.id != "legacy_actor":
                continue
            # No aliasing, whole-actor forwarding or legacy attributes beyond ID.
            attribute = parents[node]
            self.assertIsInstance(attribute, ast.Attribute)
            self.assertEqual(attribute.attr, "id")
            conversion = parents[attribute]
            self.assertIsInstance(conversion, ast.Call)
            self.assertEqual(ast.unparse(conversion), "int(legacy_actor.id)")
            assignment = parents[conversion]
            self.assertIsInstance(assignment, ast.Assign)
            self.assertEqual([ast.unparse(target) for target in assignment.targets], ["actor_id"])
            function = assignment
            while not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = parents[function]
            self.assertIn(function.name, permitted)
            provenance_functions.add(function.name)
        self.assertEqual(provenance_functions, set(permitted))

        functions = {node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}
        for name, allowed_sinks in permitted.items():
            function = functions[name]
            company_assignments = [
                node for node in ast.walk(function) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "company_id"
                        for target in node.targets)
            ]
            self.assertEqual(len(company_assignments), 1)
            self.assertEqual(ast.unparse(company_assignments[0].value), "int(access.company_id)")
            # Authorization must execute before entering the mutation transaction.
            prefix = function.body[:next(i for i, node in enumerate(function.body)
                                         if isinstance(node, ast.Try))]
            prefix_statements = {ast.dump(node) for node in prefix}
            guards = (
                ["await _require_inbound_access(access, 'inbound.create', any_location=True)",
                 "await _require_inbound_access(access, 'inbound.create', payload.location_id)"]
                if name == "warehouse_inbound" else
                ["await _require_inbound_access(access, 'inventory.costing.manage')"]
            )
            for guard in guards:
                self.assertIn(ast.dump(ast.parse(guard).body[0]), prefix_statements)
            for node in ast.walk(function):
                if not (isinstance(node, ast.Name) and node.id == "actor_id"
                        and isinstance(node.ctx, ast.Load)):
                    continue
                keyword = parents[node]
                self.assertIsInstance(keyword, ast.keyword)
                call = parents[keyword]
                self.assertIsInstance(call, ast.Call)
                self.assertIsInstance(call.func, ast.Name)
                self.assertIn((call.func.id, keyword.arg), allowed_sinks)
        self.assertEqual(quality_source.count("legacy_actor.id"), 1)
        self.assertIn("verify_quality_confirmation(db, access,", quality_source)
        self.assertNotIn("verify_actor_password(legacy_actor", quality_source)
        for source in (supplier_source, inbound_source, quality_source):
            self.assertNotIn("legacy_actor.company_id", source)
            self.assertNotIn("legacy_actor.is_admin", source)

    def test_supplier_pagination_locking_and_state_contracts_remain(self):
        api_source = self.sources[ROOT / "api" / "suppliers.py"]
        public_source = self.sources[ROOT / "domains" / "suppliers" / "public.py"]
        app_source = self.sources[ROOT / "domains" / "suppliers" / "application.py"]

        for token in (
            "search: str | None = Query(None, min_length=2, max_length=100)",
            "active: bool | None = Query(None)",
            "cursor: str | None = Query(None, max_length=512)",
            "limit: int = Query(30, ge=1, le=100)",
        ):
            self.assertIn(token, api_source)
        self.assertIn("with_for_update(read=True)", public_source)
        self.assertIn("load_supplier(db, company_id, supplier_id, lock=True)", app_source)
        self.assertIn("SUPPLIER_VERSION_CONFLICT", app_source)
        self.assertIn("SUPPLIER_DATA_CONFLICT", app_source)

    def test_inbound_business_guards_idempotency_and_transactions_remain(self):
        source = self.sources[ROOT / "api" / "warehouse" / "inbound.py"]
        for token in (
            "_require_active_warehouse_setup",
            "_resolve_inbound_uom_options",
            "_ensure_first_inbound_product_locations",
            "pg_advisory_xact_lock",
            "INBOUND_REFERENCE_DUPLICATE",
            "acquire_product_lifecycle_guards",
            "INBOUND_EXPIRY_REQUIRED",
            "INBOUND_BATCH_EXPIRED",
            "activate_costing_for_first_receipt",
            "record_supplier_evidence",
            "apply_inventory_movements_batch",
            "begin_idempotent_operation",
            "complete_idempotent_operation",
            "await db.commit()",
            "await db.rollback()",
        ):
            self.assertIn(token, source)
        self.assertIn("if replay_response is not None", source)
        self.assertIn("actor_id=actor_id", source)
        self.assertIn("performed_by=actor_id", source)

    def test_quality_business_guards_replay_terminal_hold_and_transactions_remain(self):
        source = self.sources[ROOT / "api" / "warehouse" / "whole_product_quality.py"]
        for token in (
            "verify_quality_confirmation(db, access,",
            'operational_hold or "").upper() != "RECALL"',
            "resolve_current_stock_suppliers",
            "acquire_product_lifecycle_guards",
            "acquire_inventory_location_guards",
            "validate_special_transfer_source_items_locked",
            "stage_quality_handling_direct",
            "confirm_final_disposal",
            "confirm_vendor_handover",
            "close_recall_after_terminal_resolution",
            "target_hold=payload.post_resolution_hold",
            "record_supplier_evidence",
            "begin_idempotent_operation",
            "complete_idempotent_operation",
            "await db.commit()",
            "await db.rollback()",
        ):
            self.assertIn(token, source)
        self.assertIn("if replay is not None", source)
        self.assertIn("await _require_location_authority(\n                access, sorted(replay_names)", source)

    def test_all_runtime_files_parse(self):
        for path, source in self.sources.items():
            with self.subTest(path=path.name):
                ast.parse(source)


if __name__ == "__main__":
    unittest.main()
