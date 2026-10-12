from __future__ import annotations

import inspect
from pathlib import Path
import re
import unittest

from api import pricing
from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "pricing.py"


def _dependency(function, parameter):
    default = inspect.signature(function).parameters[parameter].default
    return default.dependency, default.use_cache


class PricingCanonicalAuthCutoverTests(unittest.TestCase):
    def test_source_has_zero_legacy_request_authority(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        forbidden = (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "actor.company_id",
            "legacy_actor.company_id",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

        self.assertIn("get_current_backoffice_capability_access", source)
        self.assertIn("get_current_backoffice_legacy_driver", source)
        self.assertIn("company_id=access.company_id", source)

    def test_all_pricing_routes_use_canonical_backoffice_access(self):
        endpoints = (
            pricing.get_pricing_policy,
            pricing.list_books,
            pricing.add_book,
            pricing.list_publications,
            pricing.add_publication,
            pricing.list_entries,
            pricing.add_entry,
            pricing.edit_entry,
            pricing.remove_entry,
            pricing.submit,
            pricing.approve,
            pricing.publish,
            pricing.cancel,
            pricing.list_assignments,
            pricing.add_assignment,
            pricing.resolve_preview,
        )
        for endpoint in endpoints:
            dependency, use_cache = _dependency(endpoint, "access")
            self.assertIs(dependency, get_current_backoffice_capability_access)
            self.assertTrue(use_cache)

    def test_read_only_routes_do_not_load_legacy_driver(self):
        endpoints = (
            pricing.get_pricing_policy,
            pricing.list_books,
            pricing.list_publications,
            pricing.list_entries,
            pricing.list_assignments,
            pricing.resolve_preview,
        )
        for endpoint in endpoints:
            self.assertNotIn("legacy_actor", inspect.signature(endpoint).parameters)

    def test_mutations_keep_legacy_driver_only_for_operational_provenance(self):
        endpoints = (
            pricing.add_book,
            pricing.add_publication,
            pricing.add_entry,
            pricing.edit_entry,
            pricing.remove_entry,
            pricing.submit,
            pricing.approve,
            pricing.publish,
            pricing.cancel,
            pricing.add_assignment,
        )
        for endpoint in endpoints:
            dependency, use_cache = _dependency(endpoint, "legacy_actor")
            self.assertIs(dependency, get_current_backoffice_legacy_driver)
            self.assertTrue(use_cache)

        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertIn("actor_id=legacy_actor.id", source)
        self.assertIn("legacy_actor.id", source)
        self.assertNotIn("legacy_actor.company_id", source)

    def test_exact_capability_mapping_is_preserved(self):
        expected = {
            pricing.get_pricing_policy: "pricing.view",
            pricing.list_books: "pricing.view",
            pricing.add_book: "pricing.manage",
            pricing.list_publications: "pricing.view",
            pricing.add_publication: "pricing.manage",
            pricing.list_entries: "pricing.view",
            pricing.add_entry: "pricing.manage",
            pricing.edit_entry: "pricing.manage",
            pricing.remove_entry: "pricing.manage",
            pricing.submit: "pricing.manage",
            pricing.approve: "pricing.approve",
            pricing.publish: "pricing.manage",
            pricing.cancel: "pricing.manage",
            pricing.list_assignments: "pricing.view",
            pricing.add_assignment: "pricing.manage",
            pricing.resolve_preview: "pricing.view",
        }
        for endpoint, capability in expected.items():
            self.assertIn(capability, inspect.getsource(endpoint), msg=endpoint.__name__)

        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            set(re.findall(r'"(pricing\.[a-z.]+)"', source)),
            {"pricing.view", "pricing.manage", "pricing.approve"},
        )

    def test_any_location_semantics_remain_company_wide(self):
        body = inspect.getsource(pricing._require)
        self.assertIn("await access.require(permission, any_location=True)", body)

    def test_tenant_authority_and_audit_are_separated(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertIn("company_id=access.company_id", source)
        self.assertIn("access.company_id,\n            legacy_actor.id,", source)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("actor.company_id", source)


if __name__ == "__main__":
    unittest.main()
