from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from api.warehouse import inbound_adjustments as module
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.ledger.inbound_adjustment import InboundAdjustmentState, LedgerAdjustmentError
from models import SystemAuditLog
from schemas import AdjustWarehouseEntryRequest


ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = (ROOT / "api" / "warehouse" / "inbound_adjustments.py").read_text(encoding="utf-8")
DOMAIN_SOURCE = (ROOT / "domains" / "ledger" / "inbound_adjustment.py").read_text(encoding="utf-8")


def _subject(*, owner: bool = False, locator: int | None = 903):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=None if owner else locator,
    )


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _ScalarSession:
    def __init__(self, values):
        self.values = list(values)
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError("unexpected scalar call")
        return self.values.pop(0)


class _DB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _LegacyActor:
    id = 903
    password_hash = "mapped-password-hash"

    @property
    def company_id(self):
        raise AssertionError("legacy Driver must not provide tenant authority")

    @property
    def is_admin(self):
        raise AssertionError("legacy Driver admin persona must not authorize adjustment")


def _payload(total="9", uom_id=5):
    return AdjustWarehouseEntryRequest(
        password="secret",
        new_total_quantity=total,
        uom_id=uom_id,
        notes="focused canonical cutover",
    )


def _state(total="10"):
    return InboundAdjustmentState(
        entry_id=41,
        reference="INV-9",
        normalized_reference="inv-9",
        product_variant_id=301,
        batch_id=701,
        warehouse_location_id=501,
        current_total_quantity=Decimal(total),
        base_uom_id=5,
        base_uom_code="EACH",
    )


class InboundAdjustmentsCanonicalAuthCutoverTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_has_zero_legacy_request_authority(self):
        combined = API_SOURCE + DOMAIN_SOURCE
        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "current_admin.company_id",
            "legacy_actor.company_id",
            "actor.company_id",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)
        self.assertIn("company_id = access.company_id", API_SOURCE)
        self.assertIn("require_inbound_adjustment(access, entry_id)", API_SOURCE)
        self.assertIn("apply_inventory_movement(", DOMAIN_SOURCE)

    def test_route_dependencies_are_canonical_and_legacy_driver_is_operational_only(self):
        parameters = inspect.signature(module.adjust_warehouse_entry).parameters
        self.assertIs(parameters["access"].default.dependency, get_current_backoffice_capability_access)
        self.assertIs(parameters["legacy_actor"].default.dependency, get_current_backoffice_legacy_driver)
        legacy_attributes = {
            node.attr
            for node in ast.walk(ast.parse(API_SOURCE))
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "legacy_actor"
        }
        self.assertEqual(legacy_attributes, {"id", "password_hash"})

    async def test_owner_and_non_owner_authority_still_resolve_exact_destination(self):
        owner_db = _ScalarSession([501, 501])
        await module._require_inbound_adjustment_access(
            BackofficeCapabilityAccess(owner_db, _subject(owner=True)), 41
        )
        self.assertIn("inventory_movements.company_id = 77", _sql(owner_db.statements[0]))
        self.assertIn("inventory_locations.company_id = 77", _sql(owner_db.statements[1]))

        user_db = _ScalarSession([501, 501, True])
        await module._require_inbound_adjustment_access(
            BackofficeCapabilityAccess(user_db, _subject()), 41
        )
        authorization_sql = _sql(user_db.statements[2])
        self.assertIn("ledger.adjust", authorization_sql)
        self.assertIn("user_location_access.location_id = 501", authorization_sql)
        self.assertIn("user_location_access.driver_id = 903", authorization_sql)

    async def test_missing_capability_is_structured_403_and_foreign_source_is_opaque_404(self):
        denied = _ScalarSession([501, 501, False])
        with self.assertRaises(HTTPException) as caught:
            await module._require_inbound_adjustment_access(
                BackofficeCapabilityAccess(denied, _subject()), 41
            )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["code"], "LEDGER_ADJUST_FORBIDDEN")

        foreign = _ScalarSession([None])
        with self.assertRaises(HTTPException) as hidden:
            await module._require_inbound_adjustment_access(
                BackofficeCapabilityAccess(foreign, _subject()), 41
            )
        self.assertEqual(hidden.exception.status_code, 404)
        self.assertIn("inventory_movements.company_id = 77", _sql(foreign.statements[0]))

    async def test_password_failure_audit_uses_canonical_company_and_legacy_actor_only_for_provenance(self):
        db = _DB()
        with (
            patch.object(module, "_require_inbound_adjustment_access", new=AsyncMock()),
            patch.object(module.asyncio, "to_thread", new=AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as caught:
                await module.adjust_warehouse_entry(
                    41,
                    _payload(),
                    db=db,
                    access=NS(company_id=77),
                    legacy_actor=_LegacyActor(),
                )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["code"], "LEDGER_ADJUSTMENT_PASSWORD_INVALID")
        self.assertEqual((db.commits, db.rollbacks), (1, 0))
        self.assertEqual(len(db.added), 1)
        audit = db.added[0]
        self.assertIsInstance(audit, SystemAuditLog)
        self.assertEqual((audit.company_id, audit.admin_id), (77, 903))
        self.assertEqual(audit.action_type, "UNAUTHORIZED_ADJUSTMENT")

    async def test_route_delegates_append_only_command_and_preserves_structured_domain_errors(self):
        db = _DB()
        command = AsyncMock(return_value=(_state("11"), Decimal("-2"), 9901))
        with (
            patch.object(module, "_require_inbound_adjustment_access", new=AsyncMock()),
            patch.object(module.asyncio, "to_thread", new=AsyncMock(return_value=True)),
            patch.object(module, "apply_inbound_adjustment", new=command),
        ):
            response = await module.adjust_warehouse_entry(
                41,
                _payload(total="9"),
                db=db,
                access=NS(company_id=77),
                legacy_actor=_LegacyActor(),
            )
        command.assert_awaited_once_with(
            db,
            company_id=77,
            entry_id=41,
            actor_id=903,
            new_total_quantity=Decimal("9"),
            uom_id=5,
            notes="focused canonical cutover",
        )
        self.assertIn("-2", response["message"])
        self.assertEqual((db.commits, db.rollbacks), (1, 0))

        failing = _DB()
        with (
            patch.object(module, "_require_inbound_adjustment_access", new=AsyncMock()),
            patch.object(module.asyncio, "to_thread", new=AsyncMock(return_value=True)),
            patch.object(
                module,
                "apply_inbound_adjustment",
                new=AsyncMock(side_effect=LedgerAdjustmentError(422, "UOM_MISMATCH", "wrong", context={"expected_uom_id": 8})),
            ),
        ):
            with self.assertRaises(HTTPException) as mismatch:
                await module.adjust_warehouse_entry(
                    41,
                    _payload(),
                    db=failing,
                    access=NS(company_id=77),
                    legacy_actor=_LegacyActor(),
                )
        self.assertEqual(mismatch.exception.status_code, 422)
        self.assertEqual(mismatch.exception.detail["code"], "UOM_MISMATCH")
        self.assertEqual(failing.rollbacks, 1)

    def test_append_only_locking_idempotency_and_no_history_rewrite_markers(self):
        required = (
            "func.pg_advisory_xact_lock(",
            'reference_type.in_(["INBOUND_SUPPLIER", "INBOUND_CORRECTION"])',
            '"ADJ-" + hashlib.sha256',
            "apply_inventory_movement(",
            'reference_type="INBOUND_CORRECTION"',
            "SystemAuditLog(",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, DOMAIN_SOURCE)
        for forbidden in (
            "InventoryMovement.__table__.update",
            "InventoryMovement.__table__.delete",
            "InventoryBalance.__table__.update",
        ):
            self.assertNotIn(forbidden, DOMAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()
