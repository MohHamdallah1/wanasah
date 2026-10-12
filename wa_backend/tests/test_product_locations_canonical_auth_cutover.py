from __future__ import annotations

import ast
import inspect
from pathlib import Path
import re
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException

from api import product_locations
from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccessRejected,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "product_locations.py"


class _Access:
    def __init__(self, *, company_id: int = 77, reject: bool = False):
        self.company_id = company_id
        self.reject = reject
        self.calls: list[tuple[str, int | None, bool]] = []
        self.db = type("DB", (), {})()
        self.db.scalar = AsyncMock(return_value=1)

    async def require(
        self,
        code: str,
        location_id: int | None = None,
        *,
        any_location: bool = False,
    ) -> None:
        self.calls.append((code, location_id, any_location))
        if self.reject:
            raise BackofficeCapabilityAccessRejected


class ProductLocationsCanonicalAuthCutoverTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_transport_adapter_uses_exact_canonical_scope(self):
        access = _Access()

        await product_locations._require_product_location_access(
            access,
            "product_location.manage",
            55,
        )

        self.assertEqual(
            access.calls,
            [("product_location.manage", 55, False)],
        )
        access.db.scalar.assert_not_awaited()

    async def test_transport_adapter_preserves_missing_location_404(self):
        access = _Access(reject=True)
        access.db.scalar = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as caught:
            await product_locations._require_product_location_access(
                access,
                "product_location.manage",
                55,
            )

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(
            caught.exception.detail,
            "الموقع غير موجود أو غير متاح.",
        )
        self.assertEqual(
            access.calls,
            [("product_location.manage", 55, False)],
        )

    async def test_transport_adapter_preserves_location_denial_403(self):
        access = _Access(reject=True)

        with self.assertRaises(HTTPException) as caught:
            await product_locations._require_product_location_access(
                access,
                "product_location.read",
                55,
            )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(
            caught.exception.detail,
            "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
        )
        self.assertEqual(
            access.calls,
            [("product_location.read", 55, False)],
        )

    async def test_any_location_denial_stays_403_without_location_probe(self):
        access = _Access(reject=True)

        with self.assertRaises(HTTPException) as caught:
            await product_locations._require_product_location_access(
                access,
                "product_location.read",
                any_location=True,
            )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(
            caught.exception.detail,
            "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
        )
        access.db.scalar.assert_not_awaited()
        self.assertEqual(
            access.calls,
            [("product_location.read", None, True)],
        )

    def test_read_endpoint_does_not_load_legacy_driver(self):
        params = inspect.signature(
            product_locations.list_product_locations
        ).parameters

        self.assertIn("access", params)
        self.assertNotIn("legacy_actor", params)
        depends = params["access"].default
        self.assertIs(
            depends.dependency,
            get_current_backoffice_capability_access,
        )
        self.assertTrue(depends.use_cache)

    def test_mutations_use_canonical_access_and_legacy_provenance(self):
        for endpoint in (
            product_locations.create_product_location,
            product_locations.update_product_location,
            product_locations.delete_product_location,
        ):
            params = inspect.signature(endpoint).parameters
            access_depends = params["access"].default
            actor_depends = params["legacy_actor"].default
            self.assertIs(
                access_depends.dependency,
                get_current_backoffice_capability_access,
            )
            self.assertIs(
                actor_depends.dependency,
                get_current_backoffice_legacy_driver,
            )
            self.assertTrue(access_depends.use_cache)
            self.assertTrue(actor_depends.use_cache)

    def test_source_has_zero_legacy_request_authority(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for forbidden in (
            "get_current_driver",
            "InventoryAccess",
            ".is_admin",
            "actor.company_id",
            "legacy_actor.company_id",
        ):
            self.assertNotIn(forbidden, source)

        self.assertFalse(
            any(
                isinstance(node, ast.Attribute)
                and node.attr == "is_admin"
                for node in ast.walk(tree)
            )
        )

    def test_tenant_authority_is_access_company_id(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        self.assertGreaterEqual(
            source.count("access.company_id"),
            20,
        )
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertEqual(source.count("legacy_actor.id"), 7)

    def test_list_keeps_location_filter_before_pagination(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        filter_pos = source.index(
            'access.location_filter(\n'
            '                "product_location.read",\n'
            "                ProductLocation.location_id,"
        )
        limit_pos = source.index(".limit(limit + 1)")
        self.assertLess(filter_pos, limit_pos)

    def test_only_exact_product_location_capabilities_are_used(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        capabilities = set(
            re.findall(r'"(product_location\.[a-z_]+)"', source)
        )
        self.assertEqual(
            capabilities,
            {
                "product_location.read",
                "product_location.manage",
            },
        )

    def test_lifecycle_idempotency_events_locks_and_transactions_remain(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        for expected in (
            "acquire_product_lifecycle_guards",
            "product_location_delete_blockers",
            "begin_idempotent_operation",
            "complete_idempotent_operation",
            "record_domain_event",
            ".with_for_update()",
            ".with_for_update(read=True)",
            "await db.commit()",
            "await db.rollback()",
        ):
            self.assertIn(expected, source)

    def test_delete_replay_reauthorizes_saved_location(self):
        source = inspect.getsource(
            product_locations.delete_product_location
        )

        self.assertIn(
            'replay.get(\n                "location_id",',
            source,
        )
        self.assertIn(
            'await _require_product_location_access(\n'
            "                    access,\n"
            '                    "product_location.manage",\n'
            "                    replay_location_id,",
            source,
        )


if __name__ == "__main__":
    unittest.main()
