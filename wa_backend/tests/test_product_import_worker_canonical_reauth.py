from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from domains.simple_products.imports.infrastructure import repository


ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, *values):
        self.values = list(values)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError("unexpected canonical identity query")
        return _Result(self.values.pop(0))


def _bridge(*, company_id=7, legacy_driver_id=55, principal_id=701, user_id=802):
    return SimpleNamespace(
        company_id=company_id,
        legacy_driver_id=legacy_driver_id,
        backoffice_principal_id=principal_id,
        backoffice_user_id=user_id,
    )


def _principal(*, company_id=7, principal_id=701, active=True):
    return SimpleNamespace(
        company_id=company_id,
        id=principal_id,
        principal_type="BACKOFFICE",
        is_active=active,
        auth_revision=11,
    )


def _profile(*, company_id=7, user_id=802, principal_id=701):
    return SimpleNamespace(
        company_id=company_id,
        id=user_id,
        principal_id=principal_id,
        principal_type="BACKOFFICE",
    )


def _owner(*, company_id=7, user_id=802):
    return SimpleNamespace(
        company_id=company_id,
        backoffice_user_id=user_id,
    )


class ProductImportWorkerCanonicalReverseMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reverse_mapping_keeps_legacy_principal_and_user_ids_independent(self):
        db = _Db(
            _bridge(legacy_driver_id=55, principal_id=701, user_id=802),
            _principal(principal_id=701),
            _profile(user_id=802, principal_id=701),
            _owner(user_id=802),
        )

        context = await repository.load_active_backoffice_context_for_legacy_actor(
            db,
            company_id=7,
            legacy_driver_id=55,
        )

        self.assertIsNotNone(context)
        self.assertEqual(context.company_id, 7)
        self.assertEqual(context.principal_id, 701)
        self.assertEqual(context.backoffice_user_id, 802)
        self.assertEqual(context.auth_revision, 11)
        self.assertTrue(context.is_company_owner)
        self.assertEqual(len({55, context.principal_id, context.backoffice_user_id}), 3)
        first_params = list(db.statements[0].compile().params.values())
        self.assertIn(7, first_params)
        self.assertIn(55, first_params)

    async def test_inactive_principal_fails_closed(self):
        db = _Db(
            _bridge(),
            _principal(active=False),
            _profile(),
            _owner(),
        )
        context = await repository.load_active_backoffice_context_for_legacy_actor(
            db,
            company_id=7,
            legacy_driver_id=55,
        )
        self.assertIsNone(context)

    async def test_profile_company_or_principal_mismatch_fails_closed(self):
        for profile in (
            _profile(company_id=8),
            _profile(principal_id=999),
        ):
            with self.subTest(profile=profile):
                db = _Db(
                    _bridge(),
                    _principal(),
                    profile,
                    _owner(),
                )
                context = await repository.load_active_backoffice_context_for_legacy_actor(
                    db,
                    company_id=7,
                    legacy_driver_id=55,
                )
                self.assertIsNone(context)

    async def test_owner_state_comes_only_from_persisted_owner_relation(self):
        db = _Db(
            _bridge(),
            _principal(),
            _profile(),
            _owner(user_id=999),
        )
        context = await repository.load_active_backoffice_context_for_legacy_actor(
            db,
            company_id=7,
            legacy_driver_id=55,
        )
        self.assertIsNotNone(context)
        self.assertFalse(context.is_company_owner)


class ProductImportWorkerCanonicalSourceAuditTests(unittest.TestCase):
    def test_execution_service_has_no_legacy_authorization_fallback(self):
        source = (
            ROOT
            / "domains/simple_products/imports/application/execution_service.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "InventoryAccess",
            "actor.company_id",
            ".is_admin",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("load_active_backoffice_context_for_legacy_actor", source)
        self.assertIn("resolve_backoffice_authorization_subject", source)
        self.assertIn("BackofficeCapabilityAccess", source)
        self.assertIn('"catalog.manage"', source)
        self.assertIn('"catalog.publish"', source)
        self.assertIn('"pricing.manage"', source)
        self.assertIn("any_location=True", source)
        self.assertIn("company_id=int(\n                company_id\n            )", source)
        self.assertIn("actor_id=int(\n                actor.id\n            )", source)

    def test_catalog_boundaries_have_no_inventory_access_or_actor_tenant_authority(self):
        for relative in (
            "domains/inventory_catalog_presence.py",
            "domains/inventory_batch_restrictions/queries.py",
            "domains/simple_products/service.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertNotIn("InventoryAccess", source)
                self.assertNotIn("actor.company_id", source)


if __name__ == "__main__":
    unittest.main()
