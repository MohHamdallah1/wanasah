from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import api.reconciliation as reconciliation


ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, *, one=None, rows=None):
        self.one = one
        self.rows = [] if rows is None else rows

    def scalar_one_or_none(self):
        return self.one

    def all(self):
        return self.rows

    def scalars(self):
        return self


class _Db:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.results:
            raise AssertionError("Unexpected reconciliation query")
        return self.results.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def add(self, value):
        self.added.append(value)


class _ScopedSessionDb(_Db):
    def __init__(self, *, session, company_id, driver_id):
        super().__init__([])
        self.session = session
        self.company_id = company_id
        self.driver_id = driver_id

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) > 1:
            return _Result(one=None)
        values = list(statement.compile().params.values())
        allowed = (
            self.company_id in values
            and self.driver_id in values
            and self.session.id in values
        )
        return _Result(one=self.session if allowed else None)


def _field_context(*, company_id=101, principal_id=7001, representative_id=8002):
    return SimpleNamespace(
        company_id=company_id,
        principal=SimpleNamespace(id=principal_id),
        representative=SimpleNamespace(id=representative_id),
    )


def _legacy_driver(*, driver_id=9003, company_id=999999, is_admin=False):
    return SimpleNamespace(id=driver_id, company_id=company_id, is_admin=is_admin)


def _work_session(*, session_id=71, reconciled=False):
    return SimpleNamespace(
        id=session_id,
        end_time=datetime(2026, 10, 12, tzinfo=timezone.utc),
        is_settled=False,
        inventory_reconciled_at=(
            datetime(2026, 10, 12, tzinfo=timezone.utc) if reconciled else None
        ),
        inventory_reconciled_by=9003 if reconciled else None,
    )


def _payload(counts=None):
    return reconciliation.VehicleReconciliationRequest(counts=counts or [])


def _params(statement):
    return list(statement.compile().params.values())


class ReconciliationFieldCanonicalAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_field_company_and_mapped_driver_are_independent(self):
        db = _ScopedSessionDb(
            session=_work_session(), company_id=101, driver_id=9003,
        )
        field = _field_context(
            company_id=101, principal_id=7001, representative_id=8002,
        )
        actor = _legacy_driver(driver_id=9003, company_id=444, is_admin=True)

        with self.assertRaises(HTTPException) as caught:
            await reconciliation.reconcile_driver_end_of_day(
                71, _payload(), db, field, actor,
            )

        self.assertEqual(caught.exception.status_code, 409)
        first = _params(db.statements[0])
        self.assertIn(101, first)
        self.assertIn(9003, first)
        self.assertNotIn(7001, first)
        self.assertNotIn(8002, first)
        self.assertNotIn(444, first)
        self.assertEqual(db.rollbacks, 1)

    async def test_driver_is_admin_has_zero_authority_effect(self):
        field = _field_context(company_id=101)
        statements = []
        for flag in (False, True):
            db = _ScopedSessionDb(
                session=_work_session(), company_id=101, driver_id=5555,
            )
            with self.assertRaises(HTTPException) as caught:
                await reconciliation.reconcile_driver_end_of_day(
                    71,
                    _payload(),
                    db,
                    field,
                    _legacy_driver(driver_id=9003, company_id=101, is_admin=flag),
                )
            self.assertEqual(caught.exception.status_code, 404)
            statements.append(_params(db.statements[0]))
            self.assertEqual(db.rollbacks, 1)
        self.assertEqual(statements[0], statements[1])

    async def test_other_driver_and_cross_company_session_fail_closed(self):
        session = _work_session()
        cases = (
            (_field_context(company_id=101), _legacy_driver(driver_id=9004)),
            (_field_context(company_id=202), _legacy_driver(driver_id=9003)),
        )
        for field, actor in cases:
            with self.subTest(company=field.company_id, driver=actor.id):
                db = _ScopedSessionDb(
                    session=session, company_id=101, driver_id=9003,
                )
                with self.assertRaises(HTTPException) as caught:
                    await reconciliation.reconcile_driver_end_of_day(
                        71, _payload(), db, field, actor,
                    )
                self.assertEqual(caught.exception.status_code, 404)
                self.assertEqual(db.rollbacks, 1)

    async def test_existing_reconciliation_replay_is_preserved(self):
        db = _Db([_Result(one=_work_session(reconciled=True))])
        result = await reconciliation.reconcile_driver_end_of_day(
            71, _payload(), db, _field_context(), _legacy_driver(),
        )
        self.assertTrue(result["already_reconciled"])
        self.assertFalse(result["requires_audit"])
        self.assertEqual(db.rollbacks, 1)
        self.assertEqual(db.commits, 0)
        self.assertEqual(len(db.statements), 1)

    async def test_open_vehicle_recon_reuse_and_location_guard_are_preserved(self):
        db = _Db([
            _Result(one=_work_session()),
            _Result(one=SimpleNamespace(vehicle_id=55)),
            _Result(one=SimpleNamespace(
                id=88, status="COUNTING", reference_number="VR-88",
            )),
        ])
        with patch.object(
            reconciliation, "validate_vehicle_recon_work_session", AsyncMock()
        ) as validate, patch.object(
            reconciliation,
            "resolve_vehicle_custody_location_id",
            AsyncMock(side_effect=[66, 66]),
        ) as resolve_custody, patch.object(
            reconciliation, "acquire_inventory_location_guard", AsyncMock()
        ) as guard, patch.object(
            reconciliation, "open_vehicle_reconciliation_stocktake", AsyncMock()
        ) as open_stocktake:
            result = await reconciliation.reconcile_driver_end_of_day(
                71, _payload(), db, _field_context(), _legacy_driver(),
            )

        self.assertEqual(result["stocktake_session_id"], 88)
        self.assertEqual(result["stocktake_status"], "COUNTING")
        self.assertEqual(db.rollbacks, 1)
        validate.assert_awaited_once_with(
            db, company_id=101, work_session_id=71, vehicle_id=55,
        )
        self.assertEqual(resolve_custody.await_count, 2)
        self.assertEqual(
            resolve_custody.await_args_list[0].kwargs,
            {"company_id": 101, "vehicle_id": 55, "require_active": True},
        )
        self.assertEqual(
            resolve_custody.await_args_list[1].kwargs,
            {
                "company_id": 101,
                "vehicle_id": 55,
                "require_active": True,
                "expected_location_id": 66,
            },
        )
        guard.assert_awaited_once_with(db, 101, 66, exclusive=True)
        open_stocktake.assert_not_awaited()

    async def test_conflicting_inventory_lock_fails_closed(self):
        db = _Db([
            _Result(one=_work_session()),
            _Result(one=SimpleNamespace(vehicle_id=55)),
            _Result(one=None),
            _Result(one=444),
        ])
        with patch.object(
            reconciliation, "validate_vehicle_recon_work_session", AsyncMock()
        ), patch.object(
            reconciliation,
            "resolve_vehicle_custody_location_id",
            AsyncMock(side_effect=[66, 66]),
        ) as resolve_custody, patch.object(
            reconciliation, "acquire_inventory_location_guard", AsyncMock()
        ) as guard:
            with self.assertRaises(HTTPException) as caught:
                await reconciliation.reconcile_driver_end_of_day(
                    71, _payload(), db, _field_context(), _legacy_driver(),
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("inventory_locks", str(db.statements[-1]))
        self.assertEqual(resolve_custody.await_count, 2)
        guard.assert_awaited_once_with(db, 101, 66, exclusive=True)
        self.assertEqual(db.rollbacks, 1)
        self.assertEqual(db.commits, 0)

    async def test_exact_match_uses_canonical_company_and_mapped_driver_provenance(self):
        db = _Db([
            _Result(one=_work_session()),
            _Result(one=SimpleNamespace(vehicle_id=55)),
            _Result(one=None),
            _Result(one=None),
            _Result(rows=[]),
        ])
        finalized = SimpleNamespace(
            inventory_reconciled_at=datetime(2026, 10, 12, tzinfo=timezone.utc)
        )
        with patch.object(
            reconciliation, "validate_vehicle_recon_work_session", AsyncMock()
        ), patch.object(
            reconciliation,
            "resolve_vehicle_custody_location_id",
            AsyncMock(side_effect=[66, 66]),
        ) as resolve_custody, patch.object(
            reconciliation, "acquire_inventory_location_guard", AsyncMock()
        ) as guard, patch.object(
            reconciliation,
            "finalize_vehicle_inventory_reconciliation",
            AsyncMock(return_value=finalized),
        ) as finalize:
            result = await reconciliation.reconcile_driver_end_of_day(
                71,
                _payload(),
                db,
                _field_context(
                    company_id=101, principal_id=7001, representative_id=8002,
                ),
                _legacy_driver(driver_id=9003, company_id=404, is_admin=True),
            )

        self.assertFalse(result["requires_audit"])
        self.assertFalse(result["already_reconciled"])
        self.assertEqual(resolve_custody.await_count, 2)
        guard.assert_awaited_once_with(db, 101, 66, exclusive=True)
        finalize.assert_awaited_once_with(
            db,
            company_id=101,
            work_session_id=71,
            vehicle_location_id=66,
            settled_by=9003,
        )
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        audits = [
            row for row in db.added
            if isinstance(row, reconciliation.SystemAuditLog)
        ]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].company_id, 101)
        self.assertEqual(audits[0].admin_id, 9003)
        self.assertEqual(
            audits[0].action_type, "VEHICLE_INVENTORY_RECONCILED",
        )

    async def test_variance_opens_vehicle_recon_with_mapped_driver_provenance(self):
        variant = SimpleNamespace(
            id=501, quantity_scale=6, quantity_step=Decimal("1"),
        )
        balance = SimpleNamespace(
            product_variant_id=501,
            on_hand_quantity=Decimal("2"),
            reserved_quantity=Decimal("0"),
        )
        db = _Db([
            _Result(one=_work_session()),
            _Result(one=SimpleNamespace(vehicle_id=55)),
            _Result(one=None),
            _Result(one=None),
            _Result(rows=[variant]),
            _Result(rows=[balance]),
        ])
        stocktake = SimpleNamespace(
            id=99, reference_number="VR-99", status="COUNTING",
        )
        with patch.object(
            reconciliation, "validate_vehicle_recon_work_session", AsyncMock()
        ), patch.object(
            reconciliation,
            "resolve_vehicle_custody_location_id",
            AsyncMock(side_effect=[66, 66]),
        ) as resolve_custody, patch.object(
            reconciliation, "acquire_inventory_location_guard", AsyncMock()
        ) as guard, patch.object(
            reconciliation, "validate_variant_quantity", return_value=Decimal("1")
        ) as validate_quantity, patch.object(
            reconciliation,
            "open_vehicle_reconciliation_stocktake",
            AsyncMock(return_value=(stocktake, True)),
        ) as open_stocktake:
            result = await reconciliation.reconcile_driver_end_of_day(
                71,
                _payload([{"product_variant_id": 501, "actual_quantity": "1"}]),
                db,
                _field_context(company_id=101),
                _legacy_driver(driver_id=9003, company_id=404),
            )

        self.assertTrue(result["requires_audit"])
        self.assertEqual(resolve_custody.await_count, 2)
        guard.assert_awaited_once_with(db, 101, 66, exclusive=True)
        self.assertEqual(result["variance_product_ids"], [501])
        self.assertEqual(result["variance_count"], 1)
        validate_quantity.assert_called_once()
        call = open_stocktake.await_args.kwargs
        self.assertEqual(call["company_id"], 101)
        self.assertEqual(call["started_by"], 9003)
        self.assertEqual(call["work_session_id"], 71)
        self.assertEqual(call["vehicle_location_id"], 66)
        self.assertEqual(call["product_variant_ids"], [501])
        self.assertEqual(db.commits, 1)
        audits = [
            row for row in db.added
            if isinstance(row, reconciliation.SystemAuditLog)
        ]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].company_id, 101)
        self.assertEqual(audits[0].admin_id, 9003)
        self.assertEqual(
            audits[0].action_type, "VEHICLE_RECON_VARIANCE_DETECTED",
        )


class ReconciliationCanonicalSourceAuditTests(unittest.TestCase):
    def test_final_source_has_only_canonical_field_authority(self):
        source = (ROOT / "api/reconciliation.py").read_text(encoding="utf-8")
        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "current_driver.company_id",
            "current_driver.id",
            "legacy_actor.company_id",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("get_current_field_context", source)
        self.assertIn("get_current_field_legacy_driver", source)
        self.assertIn("company_id = int(field_context.company_id)", source)
        self.assertIn("driver_id = int(legacy_actor.id)", source)

    def test_business_guards_and_transaction_contract_remain_present(self):
        source = (ROOT / "api/reconciliation.py").read_text(encoding="utf-8")
        required = (
            "company_id=company_id",
            "driver_id=driver_id",
            "inventory_reconciled_at",
            "work_session.is_settled",
            "DispatchRoute",
            "resolve_vehicle_custody_location_id",
            "require_active=True",
            "expected_location_id=vehicle_location_id",
            "acquire_inventory_location_guard",
            'stocktake_type == "VEHICLE_RECON"',
            "InventoryLock.company_id == company_id",
            "ProductVariant.company_id == company_id",
            "validate_variant_quantity",
            "_MAX_RECON_COUNTS = 5000",
            "_MAX_RECON_BALANCE_ROWS = 10000",
            "finalize_vehicle_inventory_reconciliation",
            "open_vehicle_reconciliation_stocktake",
            "admin_id=driver_id",
            "await db.commit()",
            "await db.rollback()",
            "except VehicleError",
            "except InventoryMutationError",
            "except IntegrityError",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
