from __future__ import annotations

import ast
from pathlib import Path
import unittest

from fastapi import HTTPException

from api.commercial_policy import _require
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "commercial_policy.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


class FakeSession:
    def __init__(self, scalar=None):
        self.scalar_results = list(scalar or [])
        self.scalar_statements = []

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar() call")
        return self.scalar_results.pop(0)


def _subject(*, owner=False, locator=903):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=locator,
    )


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"function not found: {name}")


class CommercialPolicyCanonicalAuthCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_uses_canonical_full_capability_semantics(self):
        class NoDB:
            def __getattr__(self, name):
                raise AssertionError(f"Owner authority unexpectedly touched DB: {name}")

        access = BackofficeCapabilityAccess(
            NoDB(),
            _subject(owner=True, locator=None),
        )
        await _require(access, "pricing.view")
        await _require(access, "pricing.manage")
        await _require(access, "pricing.approve")

    async def test_ordinary_company_grant_can_read(self):
        db = FakeSession(scalar=[True])
        access = BackofficeCapabilityAccess(db, _subject())
        await _require(access, "pricing.view")

        self.assertEqual(len(db.scalar_statements), 1)
        compiled = db.scalar_statements[0].compile()
        values = list(compiled.params.values())
        self.assertIn(77, values)
        self.assertIn(903, values)
        self.assertNotIn(101, values)
        self.assertNotIn(202, values)

    async def test_publish_requires_manage_and_approve(self):
        access = BackofficeCapabilityAccess(FakeSession(scalar=[True, True]), _subject())
        await _require(access, "pricing.manage")
        await _require(access, "pricing.approve")

        for grants, denied_at in (([False], "manage"), ([True, False], "approve")):
            with self.subTest(denied_at=denied_at):
                denied = BackofficeCapabilityAccess(FakeSession(scalar=grants), _subject())
                with self.assertRaises(HTTPException) as caught:
                    await _require(denied, "pricing.manage")
                    await _require(denied, "pricing.approve")
                self.assertEqual(caught.exception.status_code, 403)
                self.assertEqual(
                    caught.exception.detail,
                    "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
                )

    def test_read_route_is_driver_free_and_uses_canonical_company(self):
        body = _function_source("get_rounding_policy")
        self.assertIn("get_current_backoffice_capability_access", body)
        self.assertIn('await _require(access, "pricing.view")', body)
        self.assertIn("company_id=access.company_id", body)
        self.assertNotIn("get_current_backoffice_legacy_driver", body)
        self.assertNotIn("legacy_actor", body)
        self.assertNotIn("Driver", body)

    def test_publish_uses_both_capabilities_and_mapped_driver_only_for_provenance(self):
        body = _function_source("publish_rounding_policy")
        self.assertIn('await _require(access, "pricing.manage")', body)
        self.assertIn('await _require(access, "pricing.approve")', body)
        self.assertLess(
            body.index('await _require(access, "pricing.manage")'),
            body.index('await _require(access, "pricing.approve")'),
        )
        self.assertIn("get_current_backoffice_legacy_driver", body)
        self.assertIn("company_id = access.company_id", body)
        self.assertGreaterEqual(body.count("actor_id=legacy_actor.id"), 2)
        self.assertIn("admin_id=legacy_actor.id", body)
        self.assertNotIn("legacy_actor.company_id", body)
        self.assertNotIn("legacy_actor.is_admin", body)

    def test_no_legacy_authority_or_identity_alias_assumption(self):
        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "actor.company_id",
            "legacy_actor.company_id",
            "principal_id ==",
            "backoffice_user_id ==",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, SOURCE)

    def test_cross_company_isolation_comes_from_canonical_access(self):
        read_body = _function_source("get_rounding_policy")
        publish_body = _function_source("publish_rounding_policy")
        self.assertIn("company_id=access.company_id", read_body)
        self.assertIn("company_id = access.company_id", publish_body)
        self.assertIn("company_id=company_id", publish_body)
        self.assertNotIn("company_id=legacy_actor", publish_body)
        self.assertNotIn("company_id=actor", SOURCE)

    def test_business_idempotency_audit_and_error_contracts_are_preserved(self):
        for marker in (
            'COMMERCIAL_ROUNDING_POLICY_CODE',
            'Literal["HALF_UP", "HALF_EVEN"]',
            'expected_revision',
            'COMMERCIAL_ROUNDING_NOT_CONFIGURED',
            'begin_idempotent_operation(',
            'operation="COMMERCIAL_ROUNDING_PUBLISH"',
            'request_hash=_request_hash(payload)',
            'publish_commercial_rounding_policy(',
            'SystemAuditLog(',
            'action_type="COMMERCIAL_ROUNDING_PUBLISHED"',
            'complete_idempotent_operation(operation, response)',
            'await db.commit()',
            'await db.rollback()',
            'except CommercialPolicyError as exc:',
            'except InventoryMutationError as exc:',
            'except IntegrityError as exc:',
            '"IDEMPOTENCY_CONFLICT"',
            '"COMMERCIAL_ROUNDING_CONFLICT"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, SOURCE)

    def test_independent_identity_ids_and_driver_admin_flag_are_irrelevant(self):
        subject = _subject()
        self.assertEqual(subject.principal_id, 101)
        self.assertEqual(subject.backoffice_user_id, 202)
        self.assertEqual(subject.legacy_grant_driver_id, 903)
        self.assertEqual(len({101, 202, 903}), 3)
        self.assertNotIn(".is_admin", SOURCE)
        self.assertNotIn("principal_id == legacy_actor.id", SOURCE)
        self.assertNotIn("backoffice_user_id == legacy_actor.id", SOURCE)


if __name__ == "__main__":
    unittest.main()
