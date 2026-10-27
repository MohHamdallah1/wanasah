"""Exact active-route deltas and terminal custody plans; never carton conversion."""
import os
import asyncio
import unittest
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from api import dispatch, driver
from domains.dispatch_route_load import canonical_adjustment_target
from domains.dispatch_transfer_quantity import CANONICAL_BASE_V1, canonical_field_base_quantity, is_canonical_base_handshake
from domains.uom_authority import UomAuthorityError, _build_authority
from models import (DispatchRoute, DispatchLoadPlanLine, InventoryBalance, InventoryMovement,
    InventoryTransferHeader, InventoryTransferLine, ProductUomConversion, ProductVariant,
    UOM, WorkSession, Zone, utc_now)
from schemas import (AdjustRouteInventoryRequest, RouteLiveInventoryItemResponse,
    TransferResponseRequest, BatchTransferResponseRequest, ForceCancelHandshakeRequest,
    PendingTransferItem, PendingBatchResponse, GetVisitsContract, PendingTransferMinResponse)
from tests import test_vehicle_load_v1_postgres as vehicle_fixture


class AdjustmentContractTests(unittest.TestCase):
    def test_legacy_pending_response_additions_do_not_change_historical_json(self):
        legacy = dict(real_transfer_id=17, product_name="Legacy", delta_cartons=1, delta_packs=0)
        self.assertEqual(PendingTransferItem.model_validate(legacy).model_dump(mode="json"), legacy)
        minimal = dict(transfer_id=17, product_variant_id=7, quantity_packs=8, status="pending", created_at=None)
        self.assertEqual(PendingTransferMinResponse.model_validate(minimal).model_dump(mode="json"), minimal)

    def test_marker_is_explicit_and_fractional_projection_never_truncates(self):
        for context in (None, {}, {"quantity_contract": "LEGACY"}):
            self.assertFalse(is_canonical_base_handshake(SimpleNamespace(commercial_context=context)))
        self.assertTrue(is_canonical_base_handshake(SimpleNamespace(commercial_context={"quantity_contract": CANONICAL_BASE_V1})))
        self.assertEqual(canonical_field_base_quantity(Decimal(8)), 8)
        self.assertEqual(canonical_field_base_quantity(Decimal(-5)), -5)
        with self.assertRaises(UomAuthorityError) as caught:
            canonical_field_base_quantity(Decimal("0.5"))
        self.assertEqual(caught.exception.code, "DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED")

    def test_exact_signed_base_and_legacy_are_distinct(self):
        legacy = AdjustRouteInventoryRequest(request_id=uuid4(), deltas=[dict(product_id=7, delta_cartons=1)])
        exact = AdjustRouteInventoryRequest(request_id=uuid4(), deltas=[dict(product_id=7, delta_base="0.50")])
        self.assertEqual(legacy.deltas[0].delta_cartons, 1)
        self.assertIsNone(legacy.deltas[0].delta_base)
        self.assertEqual(exact.model_dump(mode="json")["deltas"][0]["delta_base"], "0.5")
        for rows in ([dict(product_id=7, delta_base="0")],
                     [dict(product_id=7, delta_base="1", delta_cartons=1)],
                     [dict(product_id=7, delta_base="1"), dict(product_id=8, delta_cartons=1)],
                     [dict(product_id=7, delta_base=0.5)],
                     [dict(product_id=7, delta_base="NaN")],
                     [dict(product_id=7, delta_base="1"), dict(product_id=7, delta_base="2")]):
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                AdjustRouteInventoryRequest(request_id=uuid4(), deltas=rows)

    def test_targets_retain_remainders_and_pending_is_already_base(self):
        authority = _build_authority(SimpleNamespace(id=7, base_uom_id=1, quantity_scale=0, quantity_step=Decimal(1)), [])
        for delta in (1, -1, 5, -5, 8, -8):
            self.assertEqual(canonical_adjustment_target(current=Decimal(25), pending=Decimal(8),
                delta=Decimal(delta), authority=authority), Decimal(33 + delta))


@unittest.skipUnless(os.environ.get("WANASAH_ADJUST_LOAD_PG_GATE") == "1", "disposable PostgreSQL gate not enabled")
class ActiveRouteAdjustLoadPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Reuse the accepted Vehicle Load fixture in a disposable migrated DB.
        vehicle_fixture.VehicleLoadV1Postgres.raw_url = os.environ["DATABASE_URL_MIGRATION"]
        self.seed = vehicle_fixture.VehicleLoadV1Postgres("runTest")
        await self.seed.asyncSetUp()
        self.addAsyncCleanup(self.seed.asyncTearDown)
        self.db, self.company = self.seed.db, self.seed.company_id
        self.pid, self.vid, self.wh = self.seed.variant_id, self.seed.vehicle_location_id, self.seed.warehouse_a_id
        self.actor = self.seed.owner.operational_driver
        self.actor_id = int(self.actor.id)
        self.cancel_requests = {}
        self.field = SimpleNamespace(company_id=self.company)
        self.seed.variant.packs_per_carton = 8
        pack = await self.db.scalar(select(UOM).where(UOM.name == "PACK"))
        if pack is None:
            pack = UOM(code="P" + uuid4().hex[:10], name="PACK")
            self.db.add(pack)
        await self.db.flush()
        self.db.add(ProductUomConversion(company_id=self.company, product_variant_id=self.pid,
            from_uom_id=pack.id, to_uom_id=self.seed.variant.base_uom_id,
            numerator=8, denominator=1, version=1))
        balance = await self.db.scalar(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.wh, InventoryBalance.product_variant_id == self.pid))
        balance.on_hand_quantity = 100
        self.db.add(InventoryBalance(company_id=self.company, location_id=self.vid, product_variant_id=self.pid,
            batch_id=self.seed.batch_id, stock_status="AVAILABLE", on_hand_quantity=25, reserved_quantity=0))
        zone = Zone(company_id=self.company, name="Adjust " + uuid4().hex[:8])
        self.db.add(zone)
        await self.db.flush()
        self.route = DispatchRoute(company_id=self.company, zone_id=zone.id, driver_id=self.actor_id,
            vehicle_id=self.seed.vehicle_id, source_location_id=self.wh, status="waiting")
        self.db.add(self.route)
        await self.db.flush()
        self.rid = int(self.route.id)
        self.db.add(DispatchLoadPlanLine(company_id=self.company, dispatch_route_id=self.rid,
            product_variant_id=self.pid, target_quantity_packs=25, updated_by=self.actor_id))
        await self.db.commit()

    async def adjust(self, delta=None, *, legacy=None, request_id=None, rows=None):
        payload = AdjustRouteInventoryRequest(request_id=request_id or uuid4(), deltas=rows or [
            dict(product_id=self.pid, **({"delta_cartons": legacy} if legacy is not None else {"delta_base": str(delta)}))])
        return await dispatch.adjust_route_inventory(self.rid, payload, self.db,
            self.seed.owner.access(self.db), self.actor)

    async def physical(self, location=None):
        return Decimal(await self.db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == self.company, InventoryBalance.location_id == (location or self.vid),
            InventoryBalance.product_variant_id == self.pid)) or 0)

    async def plan(self):
        return Decimal(await self.db.scalar(select(DispatchLoadPlanLine.target_quantity_packs).where(
            DispatchLoadPlanLine.company_id == self.company, DispatchLoadPlanLine.dispatch_route_id == self.rid,
            DispatchLoadPlanLine.product_variant_id == self.pid)) or 0)

    async def headers(self):
        return (await self.db.scalars(select(InventoryTransferHeader).where(
            InventoryTransferHeader.company_id == self.company).order_by(InventoryTransferHeader.id))).all()

    async def bind(self):
        self.session = WorkSession(company_id=self.company, driver_id=self.actor_id)
        self.db.add(self.session)
        await self.db.flush()
        self.sid = int(self.session.id)
        self.route.work_session_id = self.sid
        self.route.status = "active"
        await self.db.commit()

    async def test_live_inventory_exact_base_uom_and_legacy_projection(self):
        raw = await dispatch.get_route_live_inventory(self.rid, self.db, self.seed.owner.access(self.db))
        item = next(row for row in raw if row["product_id"] == str(self.pid))
        encoded = RouteLiveInventoryItemResponse.model_validate(item).model_dump(mode="json")
        self.assertEqual(encoded["current_base_quantity"], "25")
        self.assertEqual(encoded["display_factor_to_base"], "8")
        self.assertEqual(encoded["display_uom_name"], "PACK")
        self.assertEqual((encoded["current_cartons"], encoded["current_packs"]), (3, 1))

    async def test_direct_signed_deltas_replay_and_legacy_compatibility(self):
        for delta in (1, -1, 5, -5, 8, -8):
            rid = uuid4()
            result = await self.adjust(delta, request_id=rid)
            self.assertEqual(result["mode"], "DIRECT")
            self.assertEqual(await self.physical(), Decimal(25 + delta))
            self.assertEqual(await self.plan(), Decimal(25 + delta))
            self.assertEqual(await self.adjust(delta, request_id=rid), result)
            with self.assertRaises(HTTPException):
                await self.adjust(delta + 2, request_id=rid)
            self.assertEqual(await self.physical(), Decimal(25 + delta))
            await self.adjust(-delta)
        await self.adjust(legacy=1)
        self.assertEqual(await self.physical(), Decimal(33))
        await self.adjust(-8)
        self.seed.variant.packs_per_carton = 32  # Valid legacy value deliberately disagrees with PACK=8.
        await self.db.commit()
        await self.adjust(1)
        self.assertEqual(await self.physical(), Decimal(26))

    async def test_direct_decimal_step_and_no_truncation(self):
        self.seed.variant.quantity_scale = 2
        self.seed.variant.quantity_step = Decimal("0.25")
        await self.db.commit()
        await self.adjust("0.5")
        self.assertEqual(await self.physical(), Decimal("25.5"))
        await self.adjust("-0.25")
        self.assertEqual(await self.physical(), Decimal("25.25"))
        self.assertEqual(await self.plan(), Decimal("25.25"))
        with self.assertRaises(HTTPException):
            await self.adjust("0.1")
        self.assertEqual(await self.physical(), Decimal("25.25"))

    async def test_fractional_handshake_fails_before_header_or_reservation(self):
        self.seed.variant.quantity_scale = 2
        self.seed.variant.quantity_step = Decimal("0.25")
        await self.db.commit()
        await self.bind()
        with self.assertRaises(HTTPException) as caught:
            await self.adjust("0.5")
        self.assertEqual(caught.exception.detail["code"], "DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED")
        self.assertEqual(await self.headers(), [])
        reserved = await self.db.scalar(select(func.sum(InventoryBalance.reserved_quantity)).where(InventoryBalance.company_id == self.company))
        self.assertEqual(reserved, 0)
        self.assertEqual(await self.physical(), Decimal(25))
        self.assertEqual(await self.plan(), Decimal(25))

    async def test_handshake_line_quantity_is_base_and_field_radar_compatible(self):
        await self.bind()
        for delta in (5, -5, 8):
            request_id = uuid4()
            await self.adjust(delta, request_id=request_id)
            await self.adjust(delta, request_id=request_id)
        self.assertEqual(await self.physical(), Decimal(25))
        lines = (await self.db.scalars(select(InventoryTransferLine).where(
            InventoryTransferLine.company_id == self.company).order_by(InventoryTransferLine.id))).all()
        self.assertEqual([line.quantity for line in lines], [Decimal(5), Decimal(5), Decimal(8)])
        pending = await driver.get_pending_transfers(self.db, self.field, self.actor)
        field_quantities = {(item["delta_cartons"], item["delta_packs"]) for batch in pending for item in batch["items"]}
        self.assertEqual(field_quantities, {(0, 5), (0, -5), (0, 8)})
        contexts = (await self.db.scalars(select(InventoryTransferHeader.commercial_context).where(
            InventoryTransferHeader.company_id == self.company))).all()
        self.assertEqual(len(contexts), 3)
        self.assertTrue(all(context["quantity_contract"] == CANONICAL_BASE_V1 for context in contexts))
        radar = await dispatch.get_route_transfers(self.rid, self.db, self.seed.owner.access(self.db))
        self.assertEqual({row["signed_base_quantity"] for row in radar}, {Decimal(5), Decimal(-5), Decimal(8)})
        self.assertTrue(all(row["display_uom_name"] == "PACK" for row in radar))
        self.assertEqual({(row["delta_cartons"], row["delta_packs"]) for row in radar}, field_quantities)

    async def test_canonical_marker_survives_conflicting_legacy_configuration(self):
        await self.bind()
        await self.adjust(8)
        await self.adjust(-5)
        self.seed.variant.packs_per_carton = 32
        await self.db.commit()
        await self.adjust(8)  # Creation itself also ignores the conflicting legacy factor.
        # Read back persisted JSON independently of the identity-mapped header objects.
        contexts = (await self.db.scalars(select(InventoryTransferHeader.commercial_context).where(
            InventoryTransferHeader.company_id == self.company))).all()
        self.assertEqual(len(contexts), 3)
        self.assertTrue(all(context["quantity_contract"] == CANONICAL_BASE_V1 for context in contexts))
        pending = await driver.get_pending_transfers(self.db, self.field, self.actor)
        self.assertEqual({(item["delta_cartons"], item["delta_packs"]) for batch in pending for item in batch["items"]},
            {(0, 8), (0, -5)})
        radar = await dispatch.get_route_transfers(self.rid, self.db, self.seed.owner.access(self.db))
        self.assertEqual({row["signed_base_quantity"] for row in radar}, {Decimal(8), Decimal(-5)})
        self.assertTrue(all(row["display_factor_to_base"] == "8" and row["display_uom_name"] == "PACK" for row in radar))
        encoded = [PendingBatchResponse.model_validate(batch).model_dump(mode="json") for batch in pending]
        items = [item for batch in encoded for item in batch["items"]]
        self.assertEqual({item["signed_base_quantity"] for item in items}, {"8", "-5"})
        self.assertTrue(all(item["quantity_contract"] == CANONICAL_BASE_V1 and item["display_factor_to_base"] == "8"
            and item["base_uom_name"] and item["quantity_step"] == "1" for item in items))

    async def test_session_refresh_keeps_canonical_pending_display_evidence(self):
        await self.bind()
        await self.adjust(8)
        self.seed.variant.packs_per_carton = 32
        await self.db.commit()
        # This fixture has no commercial sale/pricing context. Leave that separate
        # projection empty while exercising real session, route and pending SQL.
        with patch.object(driver, "_load_vehicle_inventory_projection", AsyncMock(return_value=(self.vid, []))), \
             patch.object(driver, "resolve_driver_display_prices_bulk", AsyncMock(return_value={})):
            raw = await driver.get_driver_visits(self.db, self.field, self.actor)
        encoded = GetVisitsContract.model_validate(raw).model_dump(mode="json")
        item = encoded["pending_transfers"][0]
        self.assertEqual(item["quantity_contract"], CANONICAL_BASE_V1)
        self.assertEqual(item["signed_base_quantity"], "8")
        self.assertEqual((item["delta_cartons"], item["delta_packs"], item["product_name"]), (0, 8, self.seed.variant.variant_name))
        self.assertEqual(item["display_factor_to_base"], "8")

    async def test_canonical_read_projections_do_not_require_legacy_packing(self):
        await self.bind()
        await self.adjust(8)
        real_execute = self.db.execute
        # DB constraints forbid storing 0/NULL. Fault-inject only that obsolete
        # projection column, leaving real headers, lines, UOM and access checks intact.
        for invalid in (0, None):
            async def without_legacy_packing(statement, *args, **kwargs):
                result = await real_execute(statement, *args, **kwargs)
                if any(column.get("name") == "packs_per_carton" for column in getattr(statement, "column_descriptions", ())):
                    rows = [(*row[:-1], invalid) for row in result.all()]
                    return SimpleNamespace(all=lambda: rows)
                return result
            with self.subTest(packing=invalid), patch.object(self.db, "execute", side_effect=without_legacy_packing):
                pending = await driver.get_pending_transfers(self.db, self.field, self.actor)
                self.assertEqual((pending[0]["items"][0]["delta_cartons"], pending[0]["items"][0]["delta_packs"]), (0, 8))
                radar = await dispatch.get_route_transfers(self.rid, self.db, self.seed.owner.access(self.db))
                self.assertEqual((radar[0]["delta_cartons"], radar[0]["delta_packs"], radar[0]["signed_base_quantity"]), (0, 8, Decimal(8)))
                self.assertEqual(radar[0]["display_factor_to_base"], "8")

    async def test_identical_base_quantities_keep_historical_legacy_split_without_marker(self):
        await self.bind()
        await self.adjust(legacy=1)
        await self.adjust(8)
        legacy, canonical = await self.headers()
        self.assertNotIn("quantity_contract", legacy.commercial_context)
        self.assertEqual(canonical.commercial_context["quantity_contract"], CANONICAL_BASE_V1)
        pending = await driver.get_pending_transfers(self.db, self.field, self.actor)
        projected = {item["real_transfer_id"]: (item["delta_cartons"], item["delta_packs"])
            for batch in pending for item in batch["items"]}
        self.assertEqual(projected, {legacy.id: (1, 0), canonical.id: (0, 8)})
        radar = await dispatch.get_route_transfers(self.rid, self.db, self.seed.owner.access(self.db))
        self.assertEqual({row["transfer_id"]: (row["delta_cartons"], row["delta_packs"]) for row in radar}, projected)

    async def terminal(self, header, status, batch=False):
        from sqlalchemy import inspect
        transfer_id = inspect(header).identity[0]  # Replay rollback expires ORM attributes.
        if status == "cancelled":
            payload = ForceCancelHandshakeRequest(request_id=self.cancel_requests.setdefault(transfer_id, uuid4()), reason="Synthetic cancellation")
            return await dispatch.force_cancel_handshake(transfer_id, payload, self.db, self.seed.owner.access(self.db), self.actor)
        if batch:
            payload = BatchTransferResponseRequest(transfers=[dict(transfer_id=transfer_id, status=status,
                reason="Mismatch" if status == "rejected" else None)])
            return await driver.batch_respond_to_transfers(payload, self.db, self.field, self.actor)
        payload = TransferResponseRequest(response=status, reason="Mismatch" if status == "rejected" else None)
        return await driver.respond_to_transfer(transfer_id, payload, self.db, self.field, self.actor)

    async def check_terminal(self, status, batch=False):
        await self.bind()
        await self.adjust(5)
        await self.adjust(8)
        first, remaining = await self.headers()
        await self.terminal(first, status, batch)
        expected_physical = 30 if status == "accepted" else 25
        self.assertEqual(await self.physical(), Decimal(expected_physical))
        self.assertEqual(await self.plan(), Decimal(expected_physical + 8))
        await self.terminal(first, status, batch)  # same decision/request is idempotent
        self.assertEqual(await self.physical(), Decimal(expected_physical))
        await self.terminal(remaining, "accepted", batch)
        self.assertEqual(await self.physical(), Decimal(expected_physical + 8))
        self.assertEqual(await self.plan(), await self.physical())

    async def test_single_accept_plan_with_remaining_pending(self):
        await self.check_terminal("accepted")

    async def test_single_reject_plan_with_remaining_pending(self):
        await self.check_terminal("rejected")

    async def test_cancel_plan_with_remaining_pending(self):
        await self.check_terminal("cancelled")

    async def test_batch_accept_plan_with_remaining_pending(self):
        await self.check_terminal("accepted", True)

    async def test_batch_reject_plan_with_remaining_pending(self):
        await self.check_terminal("rejected", True)

    async def test_batch_mixed_decisions_and_negative_accept_are_exact_once(self):
        await self.bind()
        await self.adjust(5)
        await self.adjust(8)
        first, second = await self.headers()
        payload = BatchTransferResponseRequest(transfers=[
            dict(transfer_id=first.id, status="accepted"),
            dict(transfer_id=second.id, status="rejected", reason="Mismatch"),
        ])
        await driver.batch_respond_to_transfers(payload, self.db, self.field, self.actor)
        await driver.batch_respond_to_transfers(payload, self.db, self.field, self.actor)
        self.assertEqual(await self.physical(), Decimal(30))
        self.assertEqual(await self.plan(), Decimal(30))
        await self.adjust(-5)
        last = (await self.headers())[-1]
        await self.terminal(last, "accepted")
        self.assertEqual(await self.physical(), Decimal(25))
        self.assertEqual(await self.plan(), Decimal(25))

    async def test_remaining_negative_pending_is_subtracted_from_physical_custody(self):
        await self.bind()
        await self.adjust(8)
        await self.adjust(-5)
        first, remaining = await self.headers()
        await self.terminal(first, "accepted")
        self.assertEqual(await self.physical(), Decimal(33))
        self.assertEqual(await self.plan(), Decimal(28))
        await self.terminal(remaining, "rejected")
        self.assertEqual(await self.physical(), Decimal(33))
        self.assertEqual(await self.plan(), Decimal(33))

    async def test_terminal_and_new_adjustment_serialize_before_route_row_lock(self):
        await self.bind()
        await self.adjust(5)
        header = (await self.headers())[0]
        await dispatch.lock_session_load_plan(self.db, company_id=self.company, work_session_id=self.sid)
        other = self.seed.Session()
        try:
            task = asyncio.create_task(dispatch.adjust_route_inventory(self.rid,
                AdjustRouteInventoryRequest(request_id=uuid4(), deltas=[dict(product_id=self.pid, delta_base="8")]),
                other, self.seed.owner.access(other), self.actor))
            await asyncio.sleep(0.15)
            self.assertFalse(task.done())
            await self.terminal(header, "rejected")
            await asyncio.wait_for(task, timeout=8)
            self.assertEqual(await self.physical(), Decimal(25))
            self.assertEqual(await self.plan(), Decimal(33))
        finally:
            await other.close()

    async def test_shortage_and_lock_failures_rollback(self):
        for delta in (101, -26):
            with self.assertRaises(HTTPException):
                await self.adjust(delta)
            self.assertEqual(await self.physical(), Decimal(25))
            self.assertEqual(await self.plan(), Decimal(25))
        with patch.object(dispatch, "check_inventory_lock", AsyncMock(side_effect=HTTPException(409, "locked"))):
            with self.assertRaises(HTTPException):
                await self.adjust(1)
        self.assertEqual(await self.physical(), Decimal(25))
        with patch.object(dispatch, "apply_inventory_movements_batch", AsyncMock(side_effect=RuntimeError("synthetic rollback"))):
            with self.assertRaises(HTTPException):
                await self.adjust(1)
        self.assertEqual(await self.plan(), Decimal(25))

    async def test_non_operational_vehicle_and_reserved_custody_rejected(self):
        from models import Vehicle
        actual = await self.db.get(Vehicle, self.seed.vehicle_id)
        actual.maintenance_status = "In_Maintenance"
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.adjust(1)
        actual = await self.db.get(Vehicle, self.seed.vehicle_id)
        actual.maintenance_status = "Active"
        balance = await self.db.scalar(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.vid, InventoryBalance.product_variant_id == self.pid))
        balance.reserved_quantity = 1
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.adjust(-1)
        self.assertEqual(await self.physical(), Decimal(25))

    async def test_closed_session_and_wrong_company_permission_fail_closed(self):
        from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
        denied = SimpleNamespace(company_id=self.company, db=self.db,
            require=AsyncMock(side_effect=BackofficeCapabilityAccessRejected()))
        with self.assertRaises(HTTPException) as caught:
            await dispatch.adjust_route_inventory(self.rid,
                AdjustRouteInventoryRequest(request_id=uuid4(), deltas=[dict(product_id=self.pid, delta_base="1")]),
                self.db, denied, self.actor)
        self.assertEqual(caught.exception.status_code, 403)
        # Exact access checks are exercised through the real owner scope with an unrelated company.
        other = self.seed.owner.access(self.db)
        from dataclasses import replace
        wrong = replace(other, subject=replace(other.subject, company_id=self.company + 100000))
        with self.assertRaises(HTTPException):
            await dispatch.adjust_route_inventory(self.rid,
                AdjustRouteInventoryRequest(request_id=uuid4(), deltas=[dict(product_id=self.pid, delta_base="1")]),
                self.db, wrong, self.actor)
        await self.bind()
        self.session.end_time = utc_now() + timedelta(seconds=1)
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.adjust(1)

        session = await self.db.get(WorkSession, self.sid)
        session.inventory_reconciled_at = session.end_time + timedelta(seconds=1)
        session.inventory_reconciled_by = self.actor_id
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.adjust(1)
        self.assertEqual(await self.physical(), Decimal(25))

    async def test_direct_return_preserves_or_tightens_source_status(self):
        balance = await self.db.scalar(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.vid, InventoryBalance.product_variant_id == self.pid))
        balance.stock_status = "BLOCKED"
        await self.db.commit()
        raw = await dispatch.get_route_live_inventory(self.rid, self.db, self.seed.owner.access(self.db))
        item = next(row for row in raw if row["product_id"] == str(self.pid))
        self.assertEqual(item["current_base_quantity"], Decimal(25))
        self.assertEqual((item["current_cartons"], item["current_packs"]), (0, 0))
        await self.adjust(-5)
        target = await self.db.scalar(select(InventoryBalance.on_hand_quantity).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.wh, InventoryBalance.product_variant_id == self.pid,
            InventoryBalance.stock_status == "BLOCKED"))
        self.assertEqual(target, Decimal(5))
        self.assertEqual(await self.physical(), Decimal(20))

    async def test_recalled_and_expired_returns_cannot_become_sellable(self):
        self.seed.variant.operational_hold = "RECALL"
        self.seed.variant.lifecycle_revision += 1
        await self.db.commit()
        await self.adjust(-5)
        recalled = await self.db.scalar(select(InventoryBalance.on_hand_quantity).where(
            InventoryBalance.company_id == self.company, InventoryBalance.location_id == self.wh,
            InventoryBalance.product_variant_id == self.pid, InventoryBalance.stock_status == "RECALLED"))
        self.assertEqual(recalled, Decimal(5))
        self.seed.variant.operational_hold = "NONE"
        self.seed.variant.lifecycle_revision += 1
        self.seed.variant.expiry_control_mode = "OPTIONAL"
        self.seed.batch.expiry_date = utc_now().date() - timedelta(days=1)
        balance = await self.db.scalar(select(InventoryBalance).where(
            InventoryBalance.company_id == self.company, InventoryBalance.location_id == self.vid,
            InventoryBalance.product_variant_id == self.pid, InventoryBalance.stock_status == "AVAILABLE"))
        balance.stock_status = "QUARANTINED"
        await self.db.commit()
        await self.adjust(-5)
        available = await self.db.scalar(select(InventoryBalance.on_hand_quantity).where(
            InventoryBalance.company_id == self.company, InventoryBalance.location_id == self.wh,
            InventoryBalance.product_variant_id == self.pid, InventoryBalance.stock_status == "AVAILABLE"))
        self.assertEqual(available, Decimal(100))
        self.assertEqual(await self.physical(), Decimal(15))
