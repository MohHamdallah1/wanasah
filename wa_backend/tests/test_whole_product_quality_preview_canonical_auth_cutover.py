from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.warehouse import whole_product_quality_preview as preview
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "warehouse" / "whole_product_quality_preview.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


class _ExecuteResult:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = list(rows or [])

    def one_or_none(self):
        return self._one

    def all(self):
        return list(self._rows)


class _RouteDB:
    def __init__(self, execute_results, scalar_results=()):
        self.execute_results = list(execute_results)
        self.scalar_results = list(scalar_results)
        self.execute_statements = []
        self.scalar_statements = []

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if not self.execute_results:
            raise AssertionError("unexpected execute call")
        return self.execute_results.pop(0)

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar call")
        return self.scalar_results.pop(0)


class _ScalarsResult:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class _OwnerCapabilityDB:
    def __init__(self, visible_locations):
        self.visible_locations = list(visible_locations)
        self.scalar_queries = []

    async def scalars(self, statement):
        self.scalar_queries.append(statement)
        return _ScalarsResult(self.visible_locations)


class _OrdinaryAccess:
    def __init__(
        self,
        *,
        company_id=77,
        location_codes=None,
        company_codes=(),
        principal_id=101,
        backoffice_user_id=202,
        grant_driver_id=903,
    ):
        self.company_id = company_id
        self.location_codes = dict(location_codes or {})
        self.company_codes = list(company_codes)
        self.location_calls = []
        self.codes_calls = 0
        self.subject = SimpleNamespace(
            principal_id=principal_id,
            backoffice_user_id=backoffice_user_id,
            company_id=company_id,
            is_company_owner=False,
            legacy_grant_driver_id=grant_driver_id,
        )

    async def codes_by_location(self, location_ids):
        ids = list(location_ids)
        self.location_calls.append(ids)
        return {
            location_id: list(self.location_codes.get(location_id, ()))
            for location_id in ids
            if location_id in self.location_codes
        }

    async def codes(self):
        self.codes_calls += 1
        return list(self.company_codes)

    @property
    def is_admin(self):
        raise AssertionError("legacy/admin persona must not participate in authority")


def _variant(*, hold="RECALL", revision=4):
    return SimpleNamespace(id=501, operational_hold=hold, lifecycle_revision=revision)


def _row(
    *,
    location_id=11,
    batch_id=41,
    quantity="2",
    reserved="0",
    location_type="WAREHOUSE",
    location_active=True,
    location_name=None,
    batch_number=None,
):
    return SimpleNamespace(
        location_id=location_id,
        batch_id=batch_id,
        on_hand_quantity=Decimal(quantity),
        reserved_quantity=Decimal(reserved),
        location_name=location_name or f"Location {location_id}",
        location_type=location_type,
        location_active=location_active,
        batch_number=batch_number or f"B-{batch_id}",
    )


def _full_db(rows, *, state=None):
    scalars = [SimpleNamespace(currency_code="JOD")]
    if state is not None:
        scalars.append(state)
    return _RouteDB(
        [
            _ExecuteResult(one=_variant()),
            _ExecuteResult(rows=rows),
        ],
        scalar_results=scalars,
    )


async def _run_full_preview(
    *,
    db,
    access,
    policy=None,
    supplier_resolution=None,
):
    supplier_mock = AsyncMock(return_value=supplier_resolution)
    with (
        patch.object(
            preview,
            "_current_recall_reason",
            new=AsyncMock(return_value="recall reason"),
        ),
        patch.object(preview, "get_cost_policy", new=AsyncMock(return_value=policy)),
        patch.object(
            preview,
            "resolve_current_stock_suppliers",
            new=supplier_mock,
        ),
    ):
        response = await preview.get_whole_product_quality_preview(
            product_variant_id=501,
            db=db,
            access=access,
        )
    return response, supplier_mock


class WholeProductQualityPreviewCanonicalAuthCutoverTests(
    unittest.IsolatedAsyncioTestCase
):
    def test_source_has_only_canonical_read_authority(self):
        self.assertIn("get_current_backoffice_capability_access", SOURCE)
        self.assertIn("BackofficeCapabilityAccess", SOURCE)
        self.assertIn("company_id = int(access.company_id)", SOURCE)
        self.assertNotIn("get_current_driver", SOURCE)
        self.assertNotIn("get_current_admin", SOURCE)
        self.assertNotIn("get_current_backoffice_legacy_driver", SOURCE)
        self.assertNotIn("InventoryAccess", SOURCE)
        self.assertNotIn("current_admin", SOURCE)
        self.assertNotIn(".is_admin", SOURCE)
        self.assertNotIn("actor.company_id", SOURCE)
        self.assertNotIn("legacy_actor.company_id", SOURCE)
        self.assertNotIn("principal_id ==", SOURCE)
        self.assertNotIn("backoffice_user_id ==", SOURCE)

    def test_route_dependency_is_canonical_and_never_resolves_legacy_driver(self):
        parameters = inspect.signature(
            preview.get_whole_product_quality_preview
        ).parameters
        self.assertIn("access", parameters)
        dependency = parameters["access"].default
        self.assertIs(
            dependency.dependency,
            get_current_backoffice_capability_access,
        )
        self.assertNotIn("current_admin", parameters)
        self.assertNotIn("legacy_actor", parameters)

    async def test_company_owner_uses_canonical_owner_authority(self):
        subject = BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=True,
            legacy_grant_driver_id=None,
        )
        access = BackofficeCapabilityAccess(
            db=_OwnerCapabilityDB([11]),
            subject=subject,
        )
        db = _full_db([_row()])
        supplier_resolution = SimpleNamespace(status="UNKNOWN", candidates=[])

        response, supplier_mock = await _run_full_preview(
            db=db,
            access=access,
            supplier_resolution=supplier_resolution,
        )

        self.assertEqual(response["product_variant_id"], 501)
        self.assertEqual(response["locations"][0]["location_id"], 11)
        self.assertEqual(access.company_id, 77)
        supplier_mock.assert_awaited_once()

    async def test_ordinary_user_must_read_every_affected_inventory_location(self):
        access = _OrdinaryAccess(
            location_codes={
                11: ["inventory.read"],
                12: ["inventory.read"],
            }
        )
        db = _full_db(
            [
                _row(location_id=12, batch_id=42),
                _row(location_id=11, batch_id=41),
            ]
        )

        response, _ = await _run_full_preview(db=db, access=access)

        self.assertEqual(access.location_calls, [[11, 12]])
        self.assertEqual(
            [item["location_id"] for item in response["locations"]],
            [11, 12],
        )

    async def test_one_unreadable_location_returns_403_without_partial_preview(self):
        access = _OrdinaryAccess(
            location_codes={11: ["inventory.read"], 12: []}
        )
        db = _RouteDB(
            [
                _ExecuteResult(one=_variant()),
                _ExecuteResult(
                    rows=[
                        _row(location_id=11, batch_id=41),
                        _row(location_id=12, batch_id=42),
                    ]
                ),
            ]
        )

        with patch.object(
            preview,
            "_current_recall_reason",
            new=AsyncMock(return_value="recall reason"),
        ):
            with self.assertRaises(HTTPException) as caught:
                await preview.get_whole_product_quality_preview(
                    product_variant_id=501,
                    db=db,
                    access=access,
                )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(
            caught.exception.detail["code"],
            "WHOLE_PRODUCT_QUALITY_LOCATION_PERMISSION_DENIED",
        )
        self.assertEqual(access.location_calls, [[11, 12]])
        self.assertEqual(access.codes_calls, 0)
        self.assertEqual(db.scalar_statements, [])

    async def test_cross_company_product_is_rejected_before_stock_discovery(self):
        access = _OrdinaryAccess(location_codes={11: ["inventory.read"]})
        db = _RouteDB([_ExecuteResult(one=None)])

        with self.assertRaises(HTTPException) as caught:
            await preview.get_whole_product_quality_preview(
                product_variant_id=999,
                db=db,
                access=access,
            )

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(len(db.execute_statements), 1)
        self.assertEqual(access.location_calls, [])
        self.assertIn("ProductVariant.company_id == company_id", SOURCE)

    async def test_independent_identity_ids_and_admin_persona_are_irrelevant(self):
        access = _OrdinaryAccess(
            location_codes={11: ["inventory.read"]},
            principal_id=101,
            backoffice_user_id=202,
            grant_driver_id=903,
        )
        db = _full_db([_row()])

        response, _ = await _run_full_preview(db=db, access=access)

        self.assertEqual(
            {
                access.subject.principal_id,
                access.subject.backoffice_user_id,
                access.subject.legacy_grant_driver_id,
            },
            {101, 202, 903},
        )
        self.assertEqual(response["product_variant_id"], 501)
        self.assertNotIn("Driver", SOURCE)
        self.assertNotIn("is_admin", SOURCE)

    async def test_supplier_read_present_preserves_supplier_candidates(self):
        access = _OrdinaryAccess(
            location_codes={11: ["inventory.read"]},
            company_codes=["supplier.read"],
        )
        db = _full_db([_row()])
        supplier_resolution = SimpleNamespace(
            status="SINGLE",
            candidates=[
                SimpleNamespace(
                    supplier_id=71,
                    supplier_name="Supplier A",
                    supplier_code="SUP-A",
                    quantity=Decimal("2"),
                )
            ],
        )

        response, supplier_mock = await _run_full_preview(
            db=db,
            access=access,
            supplier_resolution=supplier_resolution,
        )

        self.assertEqual(response["supplier_resolution"], "SINGLE")
        self.assertEqual(response["supplier_candidates"][0]["supplier_id"], 71)
        self.assertEqual(
            supplier_mock.await_args.kwargs["company_id"],
            77,
        )

    async def test_supplier_read_absent_allows_preview_but_hides_supplier_data(self):
        access = _OrdinaryAccess(
            location_codes={11: ["inventory.read"]},
            company_codes=[],
        )
        db = _full_db([_row()])

        response, supplier_mock = await _run_full_preview(db=db, access=access)

        self.assertEqual(response["supplier_resolution"], "UNKNOWN")
        self.assertEqual(response["supplier_candidates"], [])
        supplier_mock.assert_not_awaited()

    async def test_recall_lifecycle_guard_is_preserved(self):
        access = _OrdinaryAccess(location_codes={11: ["inventory.read"]})
        db = _RouteDB([_ExecuteResult(one=_variant(hold="NONE"))])

        with self.assertRaises(HTTPException) as caught:
            await preview.get_whole_product_quality_preview(
                product_variant_id=501,
                db=db,
                access=access,
            )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            caught.exception.detail["code"],
            "PRODUCT_QUALITY_ISSUE_NOT_ACTIVE",
        )
        self.assertEqual(access.location_calls, [])

    async def test_moving_average_valuation_and_stock_blockers_are_preserved(self):
        access = _OrdinaryAccess(location_codes={11: ["inventory.read"]})
        state = SimpleNamespace(
            quantity=Decimal("2"),
            average_unit_cost=Decimal("3"),
            inventory_value=Decimal("6"),
        )
        db = _full_db(
            [
                _row(
                    quantity="2",
                    reserved="1",
                    location_type="VEHICLE",
                )
            ],
            state=state,
        )
        policy = SimpleNamespace(is_active=True, method="MOVING_AVERAGE")

        response, _ = await _run_full_preview(
            db=db,
            access=access,
            policy=policy,
        )

        self.assertTrue(response["valuation_available"])
        self.assertEqual(response["costing_method"], "MOVING_AVERAGE")
        self.assertEqual(Decimal(response["total_book_value"]), Decimal("6"))
        self.assertEqual(
            response["blocker_codes"],
            [
                "WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER",
                "WHOLE_PRODUCT_QUALITY_RESERVED_STOCK",
            ],
        )

    def test_capacity_fifo_and_valuation_failure_contracts_remain_in_source(self):
        expected_tokens = (
            "WHOLE_PRODUCT_QUALITY_CAPACITY_EXCEEDED",
            "WHOLE_PRODUCT_QUALITY_LOCATION_CAPACITY_EXCEEDED",
            "WHOLE_PRODUCT_QUALITY_NO_STOCK",
            'valuation_reason = "COSTING_NOT_ACTIVE"',
            'valuation_reason = "COST_STATE_MISSING"',
            'valuation_reason = "COST_STATE_QUANTITY_MISMATCH"',
            'costing_method == "FIFO"',
            'valuation_reason = "FIFO_LAYER_QUANTITY_MISMATCH"',
            'valuation_reason = "FIFO_LAYER_VALUE_MISMATCH"',
            'valuation_reason = "COSTING_METHOD_UNSUPPORTED"',
            'currency_code if company is not None else "JOD"',
        )
        for token in expected_tokens:
            self.assertIn(token, SOURCE)
