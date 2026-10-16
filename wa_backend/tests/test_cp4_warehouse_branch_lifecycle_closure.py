import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from api import branches
from api.warehouse import locations


def _business_code(exc: HTTPException) -> str | None:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        return code if isinstance(code, str) else None
    return None


class _ExecuteResult:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class CP4WarehouseBranchLifecycleContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_branch_relation_is_tenant_opaque_and_inactive_is_machine_readable(self):
        missing_db = SimpleNamespace(execute=AsyncMock(return_value=_ExecuteResult(None)))
        with self.assertRaises(HTTPException) as missing:
            await locations._get_warehouse_branch(
                missing_db,
                company_id=10,
                branch_id=77,
                require_active=True,
            )
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(_business_code(missing.exception), "WAREHOUSE_BRANCH_NOT_FOUND")

        inactive = SimpleNamespace(id=7, name="Legacy branch", is_active=False)
        inactive_db = SimpleNamespace(execute=AsyncMock(return_value=_ExecuteResult(inactive)))
        with self.assertRaises(HTTPException) as blocked:
            await locations._get_warehouse_branch(
                inactive_db,
                company_id=10,
                branch_id=7,
                require_active=True,
            )
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertEqual(_business_code(blocked.exception), "WAREHOUSE_BRANCH_INACTIVE")

        preserved = await locations._get_warehouse_branch(
            inactive_db,
            company_id=10,
            branch_id=7,
            require_active=False,
        )
        self.assertIs(preserved, inactive)

    def test_new_association_requires_active_but_reactivation_does_not(self):
        create_source = inspect.getsource(locations.create_warehouse_location)
        update_source = inspect.getsource(locations.update_warehouse_location)
        activate_source = inspect.getsource(locations.activate_warehouse_location)

        self.assertIn("require_active=True", create_source)
        self.assertIn('if "branch_id" in payload.model_fields_set', update_source)
        explicit_assignment = update_source.split('if "branch_id" in payload.model_fields_set', 1)[1]
        self.assertIn("require_active=True", explicit_assignment)
        self.assertIn("require_active=False", activate_source)
        self.assertNotIn("require_active=True", activate_source)

    def test_existing_inactive_relation_is_preserved_when_branch_is_not_reassigned(self):
        source = inspect.getsource(locations.update_warehouse_location)
        current_relation, reassignment = source.split('if "branch_id" in payload.model_fields_set', 1)
        self.assertIn("require_active=False", current_relation)
        self.assertIn("require_active=True", reassignment)
        self.assertIn("location.branch_id = payload.branch_id", reassignment)

    def test_location_version_conflict_exposes_bounded_refresh_context(self):
        for handler in (
            locations.update_warehouse_location,
            locations.activate_warehouse_location,
            locations.deactivate_warehouse_location,
        ):
            source = inspect.getsource(handler)
            self.assertIn('"LOCATION_VERSION_CONFLICT"', source)
            self.assertIn('"resource_id": int(location.id)', source)
            self.assertIn('"expected_version": int(payload.expected_version)', source)
            self.assertIn('"current_version": int(location.version)', source)

    def test_all_known_deactivation_blockers_remain_machine_readable_without_product_location(self):
        source = inspect.getsource(locations.deactivate_warehouse_location)
        expected = {
            "INVENTORY_BALANCE",
            "OPEN_TRANSFER",
            "INVENTORY_LOCK",
            "OPEN_STOCKTAKE",
            "PUBLISHED_OPERATIONAL_POLICY",
            "OPEN_DISPATCH_ROUTE",
        }
        for blocker in expected:
            self.assertIn(f'"blocker_type": "{blocker}"', source)
        self.assertEqual(source.count('"LOCATION_DEACTIVATION_BLOCKED"'), len(expected))
        self.assertNotIn("ProductLocation", source)
        self.assertNotIn("PRODUCT_LOCATION", source)

    def test_branch_state_is_row_locked_idempotent_and_non_cascading(self):
        loader = inspect.getsource(branches._load_locked_branch)
        state = inspect.getsource(branches._change_branch_state)
        self.assertIn("with_for_update()", loader)
        self.assertIn("begin_idempotent_operation", state)
        self.assertIn('operation = "BRANCH_ACTIVATE" if activate else "BRANCH_DEACTIVATE"', state)
        self.assertIn("branch.is_active = activate", state)
        self.assertIn("complete_idempotent_operation", state)
        self.assertNotIn("InventoryLocation", state)
        self.assertNotIn("warehouse", state.lower())

    def test_branch_options_exclude_inactive_and_branch_has_no_version_concurrency_contract(self):
        options = inspect.getsource(branches.list_branch_options)
        update = inspect.getsource(branches.update_branch)
        state = inspect.getsource(branches._change_branch_state)
        self.assertIn("include_inactive=False", options)
        self.assertNotIn("expected_version", update)
        self.assertNotIn("expected_version", state)
        self.assertNotIn("LOCATION_VERSION_CONFLICT", update)
        self.assertNotIn("LOCATION_VERSION_CONFLICT", state)


if __name__ == "__main__":
    unittest.main()
