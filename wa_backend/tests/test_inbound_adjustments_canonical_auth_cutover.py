from __future__ import annotations

import hashlib
import inspect
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from api.warehouse import inbound_adjustments as module
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from models import SystemAuditLog
from quantity import canonical_quantity
from schemas import AdjustWarehouseEntryRequest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "warehouse" / "inbound_adjustments.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


def _subject(*, owner: bool = False, locator: int | None = 903):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=None if owner else locator,
    )


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class _ScalarSession:
    def __init__(self, values):
        self.values = list(values)
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError("unexpected scalar call")
        return self.values.pop(0)


class _Result:
    def __init__(self, value=None, rows=()):
        self.value = value
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _ScriptedDB:
    def __init__(self, *, execute=(), scalar=()):
        self.execute_values = list(execute)
        self.scalar_values = list(scalar)
        self.execute_statements = []
        self.scalar_statements = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if not self.execute_values:
            raise AssertionError("unexpected execute call")
        value = self.execute_values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_values:
            raise AssertionError("unexpected scalar call")
        value = self.scalar_values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

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


def _movement(
    *,
    reference_type="INBOUND_SUPPLIER",
    quantity="10",
    source_location_id=None,
    destination_location_id=501,
    source_stock_status=None,
    destination_stock_status="AVAILABLE",
):
    return SimpleNamespace(
        id=41,
        company_id=77,
        product_variant_id=301,
        batch_id=701,
        quantity=Decimal(quantity),
        movement_kind="PHYSICAL",
        reference_type=reference_type,
        reference_id="INV-9",
        source_location_id=source_location_id,
        destination_location_id=destination_location_id,
        source_stock_status=source_stock_status,
        destination_stock_status=destination_stock_status,
    )


class InboundAdjustmentsCanonicalAuthCutoverTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_source_has_zero_legacy_request_authority(self):
        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "current_admin.company_id",
            "legacy_actor.company_id",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, SOURCE)

        self.assertIn("get_current_backoffice_capability_access", SOURCE)
        self.assertIn("get_current_backoffice_legacy_driver", SOURCE)
        self.assertIn("company_id = access.company_id", SOURCE)

    def test_route_dependencies_are_canonical_and_legacy_driver_is_operational_only(self):
        parameters = inspect.signature(module.adjust_warehouse_entry).parameters
        access_dep = parameters["access"].default
        actor_dep = parameters["legacy_actor"].default
        self.assertIs(
            access_dep.dependency,
            get_current_backoffice_capability_access,
        )
        self.assertTrue(access_dep.use_cache)
        self.assertIs(
            actor_dep.dependency,
            get_current_backoffice_legacy_driver,
        )
        self.assertTrue(actor_dep.use_cache)

        legacy_attributes = {
            node.attr
            for node in __import__("ast").walk(__import__("ast").parse(SOURCE))
            if isinstance(node, __import__("ast").Attribute)
            and isinstance(node.value, __import__("ast").Name)
            and node.value.id == "legacy_actor"
        }
        self.assertEqual(legacy_attributes, {"id", "password_hash"})
        self.assertEqual(len({101, 202, _LegacyActor.id}), 3)

    async def test_company_owner_is_authorized_only_through_canonical_subject(self):
        db = _ScalarSession([501, 501])
        access = BackofficeCapabilityAccess(db, _subject(owner=True))
        await module._require_inbound_adjustment_access(access, 41)
        self.assertEqual(len(db.statements), 2)
        self.assertIn("inventory_movements.company_id = 77", _sql(db.statements[0]))
        self.assertIn("inventory_locations.company_id = 77", _sql(db.statements[1]))

    async def test_ordinary_user_requires_ledger_adjust_at_exact_destination_warehouse(self):
        db = _ScalarSession([501, 501, True])
        access = BackofficeCapabilityAccess(db, _subject())
        await module._require_inbound_adjustment_access(access, 41)
        self.assertEqual(len(db.statements), 3)
        authorization_sql = _sql(db.statements[2])
        self.assertIn("ledger.adjust", authorization_sql)
        self.assertIn("user_location_access.location_id = 501", authorization_sql)
        self.assertIn("user_location_access.driver_id = 903", authorization_sql)

    async def test_missing_capability_and_wrong_location_scope_fail_closed_as_403(self):
        for label in ("missing capability", "grant only at another warehouse"):
            with self.subTest(label=label):
                db = _ScalarSession([501, 501, False])
                access = BackofficeCapabilityAccess(db, _subject())
                with self.assertRaises(HTTPException) as caught:
                    await module._require_inbound_adjustment_access(access, 41)
                self.assertEqual(caught.exception.status_code, 403)
                self.assertEqual(
                    caught.exception.detail,
                    "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
                )
                authorization_sql = _sql(db.statements[2])
                self.assertIn("user_location_access.location_id = 501", authorization_sql)
                self.assertIn("ledger.adjust", authorization_sql)

    async def test_cross_company_or_missing_supplier_movement_remains_hidden_as_404(self):
        db = _ScalarSession([None])
        access = BackofficeCapabilityAccess(db, _subject())
        with self.assertRaises(HTTPException) as caught:
            await module._require_inbound_adjustment_access(access, 41)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(
            caught.exception.detail,
            "حركة التوريد غير موجودة أو غير متاحة.",
        )
        self.assertEqual(len(db.statements), 1)
        self.assertIn("inventory_movements.company_id = 77", _sql(db.statements[0]))
        self.assertIn("INBOUND_SUPPLIER", _sql(db.statements[0]))

    async def test_password_failure_audit_uses_canonical_company_and_mapped_driver_only(self):
        db = _ScriptedDB()
        access = SimpleNamespace(company_id=77)
        legacy_actor = _LegacyActor()
        with patch.object(
            module,
            "_require_inbound_adjustment_access",
            new=AsyncMock(),
        ), patch.object(
            module.asyncio,
            "to_thread",
            new=AsyncMock(return_value=False),
        ) as password_check:
            with self.assertRaises(HTTPException) as caught:
                await module.adjust_warehouse_entry(
                    41,
                    _payload(),
                    db=db,
                    access=access,
                    legacy_actor=legacy_actor,
                )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(
            caught.exception.detail,
            "كلمة المرور غير صحيحة. تم رفض العملية وتوثيق المحاولة.",
        )
        password_check.assert_awaited_once()
        self.assertEqual(password_check.await_args.args[2], b"mapped-password-hash")
        self.assertEqual((db.commits, db.rollbacks), (1, 0))
        self.assertEqual(len(db.added), 1)
        audit = db.added[0]
        self.assertIsInstance(audit, SystemAuditLog)
        self.assertEqual((audit.company_id, audit.admin_id), (77, 903))
        self.assertEqual(audit.action_type, "UNAUTHORIZED_ADJUSTMENT")
        self.assertEqual(audit.old_value, "Wrong Password")
        self.assertEqual(audit.new_value, "Rejected")

    async def test_historical_reconstruction_and_negative_correction_use_legacy_actor_provenance(self):
        original = _movement()
        positive = _movement(
            reference_type="INBOUND_CORRECTION",
            quantity="2",
        )
        negative = _movement(
            reference_type="INBOUND_CORRECTION",
            quantity="1",
            source_location_id=501,
            destination_location_id=None,
            source_stock_status="AVAILABLE",
            destination_stock_status=None,
        )
        db = _ScriptedDB(
            execute=(
                _Result(value=original),
                _Result(),
                _Result(value=original),
                _Result(rows=[original]),
                _Result(value=501),
                _Result(rows=[original, positive, negative]),
            ),
            scalar=(5,),
        )
        access = SimpleNamespace(company_id=77)
        legacy_actor = _LegacyActor()
        correction = SimpleNamespace(id=9901)

        with patch.object(
            module,
            "_require_inbound_adjustment_access",
            new=AsyncMock(),
        ), patch.object(
            module.asyncio,
            "to_thread",
            new=AsyncMock(return_value=True),
        ), patch.object(
            module,
            "apply_inventory_movement",
            new=AsyncMock(return_value=correction),
        ) as apply_movement:
            response = await module.adjust_warehouse_entry(
                41,
                _payload(total="9"),
                db=db,
                access=access,
                legacy_actor=legacy_actor,
            )

        self.assertIn("-2", response["message"])
        apply_movement.assert_awaited_once()
        kwargs = apply_movement.await_args.kwargs
        self.assertEqual(kwargs["company_id"], 77)
        self.assertEqual(kwargs["performed_by"], 903)
        self.assertEqual(kwargs["quantity"], Decimal("2"))
        self.assertEqual(kwargs["reference_type"], "INBOUND_CORRECTION")
        self.assertEqual(kwargs["reference_id"], "INV-9")
        self.assertEqual(kwargs["source_location_id"], 501)
        self.assertIsNone(kwargs["destination_location_id"])
        self.assertEqual(kwargs["source_stock_status"], "AVAILABLE")
        self.assertIsNone(kwargs["destination_stock_status"])

        expected_raw = (
            f"77|inv-9|301|701|{canonical_quantity(Decimal('11'))}|"
            f"{canonical_quantity(Decimal('9'))}"
        )
        self.assertEqual(
            kwargs["idempotency_key"],
            "ADJ-" + hashlib.sha256(expected_raw.encode("utf-8")).hexdigest(),
        )
        self.assertEqual((db.commits, db.rollbacks), (1, 0))
        audit = db.added[-1]
        self.assertEqual((audit.company_id, audit.admin_id), (77, 903))
        self.assertEqual(audit.action_type, "INBOUND_ADJUSTMENT")
        self.assertEqual(json.loads(audit.old_value)["total_quantity"], "11")
        self.assertEqual(json.loads(audit.new_value)["delta"], "-2")

    async def test_base_uom_mismatch_preserves_422_and_rolls_back(self):
        original = _movement()
        db = _ScriptedDB(execute=(_Result(value=original),), scalar=(8,))
        with patch.object(
            module,
            "_require_inbound_adjustment_access",
            new=AsyncMock(),
        ), patch.object(
            module.asyncio,
            "to_thread",
            new=AsyncMock(return_value=True),
        ):
            with self.assertRaises(HTTPException) as caught:
                await module.adjust_warehouse_entry(
                    41,
                    _payload(uom_id=5),
                    db=db,
                    access=SimpleNamespace(company_id=77),
                    legacy_actor=_LegacyActor(),
                )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["code"], "UOM_MISMATCH")
        self.assertEqual(caught.exception.detail["context"]["expected_uom_id"], 8)
        self.assertEqual((db.commits, db.rollbacks), (0, 1))

    async def test_concurrent_integrity_conflict_preserves_409_and_rollback(self):
        conflict = IntegrityError("adjust", {}, Exception("concurrent conflict"))
        db = _ScriptedDB(execute=(conflict,))
        with patch.object(
            module,
            "_require_inbound_adjustment_access",
            new=AsyncMock(),
        ), patch.object(
            module.asyncio,
            "to_thread",
            new=AsyncMock(return_value=True),
        ):
            with self.assertRaises(HTTPException) as caught:
                await module.adjust_warehouse_entry(
                    41,
                    _payload(),
                    db=db,
                    access=SimpleNamespace(company_id=77),
                    legacy_actor=_LegacyActor(),
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            caught.exception.detail,
            "حدث تعارض متزامن أثناء التعديل. لم يتم حفظ تصحيح جزئي.",
        )
        self.assertEqual((db.commits, db.rollbacks), (0, 1))

    def test_business_guards_append_only_locking_and_http_contract_markers_are_preserved(self):
        required = (
            "InventoryMovement.reference_type == 'INBOUND_SUPPLIER'",
            "ProductVariant.company_id == company_id",
            "InventoryLocation.id).filter_by(",
            "location_type='WAREHOUSE'",
            "len(batch_ids) != 1",
            "len(destination_ids) != 1 or None in destination_ids",
            "func.pg_advisory_xact_lock(",
            "reference_type.in_([",
            "'INBOUND_CORRECTION'",
            "is_positive_correction",
            "is_negative_correction",
            "current_total_quantity < 0",
            "idempotency_key = (",
            '"ADJ-"',
            "apply_inventory_movement(",
            "except InventoryMutationError as e:",
            "except IntegrityError as e:",
            "except Exception as e:",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, SOURCE)

        for status in (400, 403, 404, 409, 422, 500):
            self.assertIn(f"status_code={status}", SOURCE)

        self.assertIn("await db.commit()", SOURCE)
        self.assertIn("await db.rollback()", SOURCE)
        self.assertNotIn("is_company_owner", SOURCE)
        self.assertNotIn("principal_id", SOURCE)
        self.assertNotIn("backoffice_user_id", SOURCE)


if __name__ == "__main__":
    unittest.main()
