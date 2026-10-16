"""CP3.4: migrated PostgreSQL 16, real RLS, canonical actors and movement authority.

Reuse the accepted CP8 disposable gate, including its strict URL/role guard and
overlapping A1/A2/B1 fixtures. No stock balance is written by this suite.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import inventory_permissions
from api.warehouse import live_stock, transfers, transfer_policy, whole_product_quality as whole
from api.warehouse import whole_product_quality_preview as preview
from domains.identity.models import CompanyPrincipal
from domains.inventory_quality_confirmation import verify_quality_confirmation
from domains import inventory_terminal_quality as disposal_domain
from domains import inventory_terminal_vendor as vendor_domain
from domains.inventory_supplier_evidence import InventorySupplierEvidence, record_supplier_evidence
from domains.suppliers.models import Supplier
from models import (
    InventoryBalance, InventoryMovement, InventoryTransferHeader, ProductBatch,
    ProductLocation, ProductVariant, Permission, Role, UserRole, UserLocationAccess,
    role_permissions, utc_now,
)
from schemas import (
    SpecialTransferDispatchRequest, TerminalDisposalConfirmRequest, TerminalVendorHandoverRequest,
    TransferDestinationPolicySaveRequest, TransferDestinationPolicyPublishRequest, UnifiedReceiveRequest,
    WarehouseBatchStockSourcesResponse,
)
from services import apply_inventory_movement, SPECIAL_TRANSFER_PERMISSION
from tests.test_cp8_transfers_postgres import pg, _grant_location

pytestmark = [pytest.mark.skipif(os.getenv("WANASAH_CP8_PG_GATE") != "1", reason="Disposable CP8 PostgreSQL fixture only"),
              pytest.mark.asyncio(loop_scope="function")]
PASSWORD = "CanonicalQualityPassword123"


async def grant_company(db, tenant, *codes):
    role = Role(company_id=tenant.company_id, name="CP34 " + uuid4().hex)
    db.add(role)
    await db.flush()
    for code in codes:
        permission = await db.scalar(select(Permission.id).where(Permission.code == code))
        assert permission is not None, code
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id, role_id=role.id, permission_id=permission))
    db.add(UserRole(company_id=tenant.company_id, role_id=role.id, driver_id=tenant.ordinary.driver_id))


async def prepare(pg):
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        from domains.authorization.capabilities import PERMISSIONS
        needed = set(SPECIAL_TRANSFER_PERMISSION.values()) | {
            "inventory.read", "inventory.disposal.confirm", "inventory.vendor_return.confirm", "supplier.read"}
        assert needed <= PERMISSIONS
        found = set((await db.scalars(select(Permission.code).where(Permission.code.in_(needed)))).all())
        db.add_all([Permission(code=code) for code in needed - found])
        await db.flush()
        await grant_company(db, pg.a, *SPECIAL_TRANSFER_PERMISSION.values(), "supplier.read")
        await _grant_location(db, pg.a, pg.a.locations[0], "inventory.read", "inventory.disposal.confirm", "inventory.vendor_return.confirm")
        await _grant_location(db, pg.a, pg.a.quarantine_id, "inventory.read", "transfer.destination",
                              "inventory.disposal.confirm", "inventory.vendor_return.confirm")
        original = pg.a.ordinary
        pg.a.ordinary = pg.a.receiver
        await grant_company(db, pg.a, *SPECIAL_TRANSFER_PERMISSION.values())
        await _grant_location(db, pg.a, pg.a.quarantine_id, "transfer.read", "transfer.receive")
        pg.a.ordinary = original
        for tenant in (pg.a, pg.b):
            for actor in (tenant.owner, tenant.ordinary):
                principal = await db.get(CompanyPrincipal, actor.context.principal_id)
                principal.password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
                assert len({actor.context.principal_id, actor.context.backoffice_user_id, actor.driver_id}) == 3
        await db.commit()
    actor = pg.a.owner
    async with pg.session(pg.a) as db:
        draft = await transfer_policy.save_transfer_destination_policy(
            TransferDestinationPolicySaveRequest(request_id=uuid4(), payload={
                "quarantine_location_id": pg.a.quarantine_id,
                "disposal_location_id": pg.a.quarantine_id,
                "vendor_return_staging_location_id": pg.a.quarantine_id}),
            db, actor.access(db), actor.operational_driver)
        await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"],
            TransferDestinationPolicyPublishRequest(request_id=uuid4(), expected_revision=draft["policy"]["revision"]),
            db, actor.access(db), actor.operational_driver)


def special(tenant, purpose="DISPOSAL", quantity="4", **changes):
    values = dict(request_id=uuid4(), source_location_id=tenant.locations[0],
        transfer_purpose=purpose, notes="CP34 staged stock",
        items=[dict(product_variant_id=tenant.variant_id, batch_id=tenant.expired_batch_id,
                    source_status="AVAILABLE", quantity=quantity, uom_id=tenant.uom_id)])
    values.update(changes)
    return SpecialTransferDispatchRequest(**values)


async def dispatch(pg, payload):
    actor = pg.a.ordinary
    async with pg.session(pg.a) as db:
        return await transfers.special_transfer_dispatch(payload, db, actor.access(db), actor.operational_driver)


async def stage(pg, purpose):
    if purpose == "RECALL_RETURN":
        async with pg.session(pg.a) as db:
            variant = await db.get(ProductVariant, pg.a.variant_id)
            variant.operational_hold = "RECALL"
            await db.commit()
    sent = await dispatch(pg, special(pg.a, purpose))
    receiver = pg.a.receiver
    async with pg.session(pg.a) as db:
        await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=uuid4(),
            transfer_header_id=sent["header_id"], destination_location_id=pg.a.quarantine_id),
            db, receiver.access(db), receiver.operational_driver)
    return sent


def terminal_payload(pg, action, **changes):
    values = dict(request_id=uuid4(), source_location_id=pg.a.quarantine_id,
        product_variant_id=pg.a.variant_id, batch_id=pg.a.expired_batch_id, quantity="2")
    if action == "DISPOSAL":
        values["reason"] = "Physical destruction confirmed by operator"
        model = TerminalDisposalConfirmRequest
    else:
        values.update(source_status="QUARANTINED", vendor_name="Receiving vendor",
                      vendor_reference="RMA-34", handover_reference="HANDOVER-34")
        model = TerminalVendorHandoverRequest
    values.update(changes)
    return model(**values)


async def terminal(pg, action, payload, actor=None):
    actor = actor or pg.a.ordinary
    method = transfers.confirm_inventory_disposal if action == "DISPOSAL" else transfers.confirm_inventory_vendor_handover
    async with pg.session(pg.a) as db:
        return await method(payload, db, actor.access(db), actor.operational_driver)


async def quantity(pg, *, variant=None):
    async with pg.session(pg.a) as db:
        return await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == pg.a.company_id,
            InventoryBalance.product_variant_id == (variant or pg.a.variant_id)))


async def movement_snapshot(pg):
    async with pg.session(pg.a) as db:
        return {row.id: tuple(row) for row in (await db.execute(select(
            InventoryMovement.id, InventoryMovement.quantity, InventoryMovement.source_location_id,
            InventoryMovement.destination_location_id, InventoryMovement.reference_type,
            InventoryMovement.reference_id, InventoryMovement.transfer_header_id,
        ).where(InventoryMovement.company_id == pg.a.company_id))).all()}


@pytest.mark.parametrize("purpose,status", [
    ("QUARANTINE", "QUARANTINED"), ("RECALL_RETURN", "RECALLED"),
    ("RETURN_TO_VENDOR", "QUARANTINED"), ("DISPOSAL", "DISPOSAL_PENDING"),
])
async def test_exact_special_capabilities_stage_stock_without_terminal_exit(pg, purpose, status):
    await prepare(pg)
    assert SPECIAL_TRANSFER_PERMISSION[purpose] == "transfer.special." + purpose.lower()
    sent = await stage(pg, purpose)
    assert await quantity(pg) == 180
    async with pg.session(pg.a) as db:
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.status == "POSTED" and header.transfer_purpose == purpose
        stock = await db.scalar(select(InventoryBalance).where(
            InventoryBalance.company_id == pg.a.company_id, InventoryBalance.location_id == pg.a.quarantine_id,
            InventoryBalance.batch_id == pg.a.expired_batch_id, InventoryBalance.stock_status == status))
        assert stock.on_hand_quantity == 4
        exits = await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.destination_location_id.is_(None)))
        assert exits == 0


@pytest.mark.parametrize("purpose", list(SPECIAL_TRANSFER_PERMISSION))
async def test_each_special_purpose_rejects_reserved_quantity_and_exact_capability_revocation(pg, purpose):
    await prepare(pg)
    if purpose == "RECALL_RETURN":
        async with pg.session(pg.a) as db:
            (await db.get(ProductVariant, pg.a.variant_id)).operational_hold = "RECALL"
            await db.commit()
    async with pg.session(pg.a) as db:
        await apply_inventory_movement(db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
            product_variant_id=pg.a.variant_id, batch_id=pg.a.expired_batch_id, quantity=Decimal("19"),
            movement_kind="RESERVATION", reservation_action="RESERVE", reference_type="CP34_RESERVE",
            reference_id="other-operation", idempotency_key=str(uuid4()), source_location_id=pg.a.locations[0],
            destination_location_id=pg.a.locations[0], source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE")
        await db.commit()
    before = await movement_snapshot(pg)
    with pytest.raises(HTTPException) as blocked:
        await dispatch(pg, special(pg.a, purpose, quantity="2"))
    assert blocked.value.status_code == 409
    assert await movement_snapshot(pg) == before
    async with AsyncSession(pg.admin_engine) as db:
        permission = await db.scalar(select(Permission.id).where(Permission.code == SPECIAL_TRANSFER_PERMISSION[purpose]))
        await db.execute(role_permissions.delete().where(role_permissions.c.company_id == pg.a.company_id,
            role_permissions.c.permission_id == permission))
        await db.commit()
    with pytest.raises(HTTPException) as denied:
        await dispatch(pg, special(pg.a, purpose, quantity="1"))
    assert denied.value.status_code == 403


async def test_source_discovery_and_special_foreign_ids_are_opaque_and_location_bound(pg):
    await prepare(pg)
    async with pg.session(pg.a) as db:
        access = pg.a.ordinary.access(db)
        source = WarehouseBatchStockSourcesResponse.model_validate(
            await live_stock.get_batch_stock_sources(pg.a.expired_batch_id, db, access)).model_dump(mode="json")
        assert {s["location_id"] for s in source["sources"]} == {pg.a.locations[0]}
        assert source["sources"][0]["statuses"][0]["reservation_evidence"]["coverage"] == "NONE"
        for batch in (pg.b.expired_batch_id, 2147483647):
            with pytest.raises(HTTPException) as opaque:
                await live_stock.get_batch_stock_sources(batch, db, access)
            assert opaque.value.status_code == 404
    before = await movement_snapshot(pg)
    errors = []
    for variant, batch in ((pg.b.variant_id, pg.b.expired_batch_id), (2147483647, 2147483647)):
        payload = special(pg.a, items=[dict(product_variant_id=variant, batch_id=batch,
            source_status="AVAILABLE", quantity="1", uom_id=pg.a.uom_id)])
        with pytest.raises(HTTPException) as opaque:
            await dispatch(pg, payload)
        errors.append((opaque.value.status_code, opaque.value.detail["code"]))
    assert errors[0] == errors[1]
    for location, expected_status in ((pg.a.locations[1], 403), (pg.b.locations[0], 404), (2147483647, 404)):
        with pytest.raises(HTTPException) as denied:
            await dispatch(pg, special(pg.a, source_location_id=location))
        assert denied.value.status_code == expected_status
    assert await movement_snapshot(pg) == before


@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_terminal_opacity_exact_location_and_batch_product(pg, action):
    await prepare(pg)
    before = await movement_snapshot(pg)
    errors = []
    for batch in (pg.b.expired_batch_id, 2147483647):
        with pytest.raises(HTTPException) as opaque:
            await terminal(pg, action, terminal_payload(pg, action, batch_id=batch), pg.a.owner)
        errors.append((opaque.value.status_code, opaque.value.detail["code"]))
    assert errors[0] == errors[1]
    for location, expected_status in ((pg.a.locations[1], 403), (pg.b.locations[0], 404), (2147483647, 404)):
        with pytest.raises(HTTPException) as denied:
            await terminal(pg, action, terminal_payload(pg, action, source_location_id=location))
        assert denied.value.status_code == expected_status
    assert await movement_snapshot(pg) == before


@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_terminal_exit_is_exact_idempotent_concurrent_atomic_and_provenanced(pg, action):
    await prepare(pg)
    sent = await stage(pg, action)
    before = await movement_snapshot(pg)
    payload = terminal_payload(pg, action)
    domain = disposal_domain if action == "DISPOSAL" else vendor_domain
    real = domain.apply_inventory_movements_batch

    async def fail_after_movement(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("CP34 injected failure after real movement")

    with patch.object(domain, "apply_inventory_movements_batch", fail_after_movement):
        with pytest.raises(HTTPException) as failed:
            await terminal(pg, action, payload)
        assert failed.value.status_code == 500
    assert await quantity(pg) == 180 and await movement_snapshot(pg) == before
    one, two = await asyncio.gather(terminal(pg, action, payload), terminal(pg, action, payload))
    assert one == two == await terminal(pg, action, payload)
    assert one["origin_transfer_header_ids"] == [sent["header_id"]]
    assert await quantity(pg) == 178
    history = await movement_snapshot(pg)
    assert all(history[key] == row for key, row in before.items())
    async with pg.session(pg.a) as db:
        movements = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.id.in_(one["movement_ids"])))).all()
        assert len(movements) == 1
        exit = movements[0]
        assert exit.quantity == 2 and exit.destination_location_id is None
        assert exit.source_location_id == pg.a.quarantine_id and exit.movement_kind == "PHYSICAL"
        assert exit.reference_type == ("FINAL_DISPOSAL" if action == "DISPOSAL" else "FINAL_VENDOR_HANDOVER")
    with pytest.raises(HTTPException) as mismatch:
        await terminal(pg, action, payload.model_copy(update={"quantity": Decimal("1")}))
    assert mismatch.value.status_code == 409
    permission_code = "inventory.disposal.confirm" if action == "DISPOSAL" else "inventory.vendor_return.confirm"
    async with AsyncSession(pg.admin_engine) as db:
        permission = await db.scalar(select(Permission.id).where(Permission.code == permission_code))
        await db.execute(role_permissions.delete().where(role_permissions.c.company_id == pg.a.company_id,
            role_permissions.c.permission_id == permission))
        await db.commit()
    with pytest.raises(HTTPException) as revoked:
        await terminal(pg, action, payload)
    assert revoked.value.status_code == 403
    assert await movement_snapshot(pg) == history


@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_terminal_staging_rejects_reservation_shape_and_overconsumption(pg, action):
    from services import InventoryMutationError
    await prepare(pg)
    await stage(pg, action)
    status = "DISPOSAL_PENDING" if action == "DISPOSAL" else "QUARANTINED"
    before = await movement_snapshot(pg)
    async with pg.session(pg.a) as db:
        with pytest.raises(InventoryMutationError):
            await apply_inventory_movement(db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
                product_variant_id=pg.a.variant_id, batch_id=pg.a.expired_batch_id, quantity=Decimal("3"),
                movement_kind="RESERVATION", reservation_action="RESERVE", reference_type="CP34_RESERVE",
                reference_id="invalid-staging-reservation", idempotency_key=str(uuid4()), source_location_id=pg.a.quarantine_id,
                destination_location_id=pg.a.quarantine_id, source_stock_status=status, destination_stock_status=status)
        await db.rollback()
    with pytest.raises(HTTPException) as blocked:
        await terminal(pg, action, terminal_payload(pg, action, quantity="5"))
    assert blocked.value.status_code == 409
    assert await movement_snapshot(pg) == before


async def whole_stock(pg):
    """Independent fractional-quality product at A1/A2 and overlapping B1."""
    result = []
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        for tenant in (pg.a, pg.b):
            parent = await db.get(ProductVariant, tenant.variant_id)
            variant = ProductVariant(company_id=tenant.company_id, product_id=parent.product_id,
                name="Quality overlap", sku="QUALITY-OVERLAP", base_uom_id=tenant.uom_id,
                quantity_scale=6, quantity_step=Decimal("0.000001"), lot_control_mode="REQUIRED",
                expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE", operational_hold="NONE",
                published_at=utc_now())
            db.add(variant)
            supplier = Supplier(company_id=tenant.company_id, name="Receiving Supplier", code="QUALITY-SUPPLIER",
                created_by=tenant.owner.driver_id, updated_by=tenant.owner.driver_id)
            db.add(supplier)
            await db.flush()
            batch = ProductBatch(company_id=tenant.company_id, product_variant_id=variant.id, batch_number="QUALITY-LOT")
            db.add(batch)
            for location in tenant.locations:
                db.add(ProductLocation(company_id=tenant.company_id, location_id=location,
                    product_variant_id=variant.id, created_by=tenant.owner.driver_id))
            await db.flush()
            result.append(NS(variant=variant.id, batch=batch.id, supplier=supplier.id, snapshot=NS(
                id=supplier.id, name=supplier.name, code=supplier.code)))
        await db.commit()
    for tenant, case in zip((pg.a, pg.b), result):
        async with pg.session(tenant) as db:
            for location, amount in zip(tenant.locations, ("0.125001", "0.374999")):
                movement = await apply_inventory_movement(db, company_id=tenant.company_id,
                    performed_by=tenant.owner.driver_id, product_variant_id=case.variant, batch_id=case.batch,
                    quantity=Decimal(amount), movement_kind="PHYSICAL", reference_type="INBOUND_SUPPLIER",
                    reference_id="QUALITY-RECEIPT", idempotency_key=str(uuid4()),
                    source_location_id=None, destination_location_id=location, source_stock_status=None,
                    destination_stock_status="AVAILABLE")
                record_supplier_evidence(db, company_id=tenant.company_id, movement_ids=[movement.id],
                    supplier=case.snapshot, request_id=uuid4())
            (await db.get(ProductVariant, case.variant)).operational_hold = "RECALL"
            await db.commit()
    return result


def whole_payload(action="DISPOSE", **changes):
    values = dict(request_id=uuid4(), action=action, reason="Confirmed product quality issue",
                  confirmation_password=PASSWORD, post_resolution_hold="NONE")
    values.update(changes)
    return whole.WholeProductQualityResolveRequest(**values)


async def resolve(pg, case, payload, actor=None):
    actor = actor or pg.a.owner
    async with pg.session(pg.a) as db:
        return await whole.resolve_whole_product_quality(case.variant, payload, db, actor.access(db), actor.operational_driver)


async def test_canonical_password_and_whole_preview_resolve_isolation_are_real(pg):
    await prepare(pg)
    a, b = await whole_stock(pg)
    actor = pg.a.owner
    async with pg.session(pg.a) as db:
        access = actor.access(db)
        contract = await inventory_permissions.capabilities(None, db, access)
        assert contract["backoffice_user_id"] == actor.context.backoffice_user_id
        assert contract["principal_id"] != contract["backoffice_user_id"] != actor.driver_id
        assert await verify_quality_confirmation(db, access, PASSWORD)
        assert not await verify_quality_confirmation(db, access, "CP8FixturePassword123")
        data = await preview.get_whole_product_quality_preview(a.variant, db, access)
        assert Decimal(data["total_quantity"]) == Decimal("0.5")
        assert {row["location_id"] for row in data["locations"]} == set(pg.a.locations)
        assert data["supplier_resolution"] == "SINGLE"
        assert data["supplier_candidates"][0]["supplier_id"] == a.supplier
        ordinary = pg.a.ordinary.access(db)
        candidates = await live_stock.get_quality_batch_candidates(a.variant, None, 25, db, ordinary)
        assert {row["batch_id"] for row in candidates["items"]} == {a.batch}
        assert {source["location_id"] for row in candidates["items"] for source in row["sources_preview"]} == {pg.a.locations[0]}
        issue = await live_stock.get_whole_product_quality_issue_sources(a.variant, None, 25, db, ordinary)
        assert {row["batch_id"] for row in issue["batches"]} == {a.batch}
        assert {source["location_id"] for row in issue["batches"] for source in row["sources"]} == {pg.a.locations[0]}
    for variant in (b.variant, 2147483647):
        async with pg.session(pg.a) as db:
            with pytest.raises(HTTPException) as opaque:
                await preview.get_whole_product_quality_preview(variant, db, actor.access(db))
            assert opaque.value.status_code == 404
            for read in (live_stock.get_quality_batch_candidates, live_stock.get_whole_product_quality_issue_sources):
                with pytest.raises(HTTPException) as hidden:
                    await read(variant, None, 25, db, actor.access(db))
                assert hidden.value.status_code == 404
        with pytest.raises(HTTPException) as opaque:
            await resolve(pg, NS(variant=variant), whole_payload())
        assert opaque.value.status_code == 404
    async with pg.session(pg.a) as db:
        with pytest.raises(HTTPException) as denied:
            await preview.get_whole_product_quality_preview(a.variant, db, pg.a.ordinary.access(db))
        assert denied.value.status_code == 403
    before = await movement_snapshot(pg)
    with pytest.raises(HTTPException) as denied:
        await resolve(pg, a, whole_payload(), pg.a.ordinary)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as wrong_password:
        await resolve(pg, a, whole_payload(confirmation_password="CP8FixturePassword123"))
    assert wrong_password.value.detail["code"] == "SUPERVISOR_CONFIRMATION_FAILED"
    assert await movement_snapshot(pg) == before


@pytest.mark.parametrize("action", ["DISPOSE", "RETURN_TO_VENDOR"])
async def test_whole_product_resolve_fractional_movement_replay_supplier_and_rollback(pg, action):
    await prepare(pg)
    a, b = await whole_stock(pg)
    payload = whole_payload(action, supplier_id=a.supplier if action == "RETURN_TO_VENDOR" else None)
    before = await movement_snapshot(pg)
    real = whole.confirm_final_disposal if action == "DISPOSE" else whole.confirm_vendor_handover
    name = "confirm_final_disposal" if action == "DISPOSE" else "confirm_vendor_handover"
    async def fail_after_terminal(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("CP34 failure after actual terminal exit")
    with patch.object(whole, name, fail_after_terminal):
        with pytest.raises(HTTPException) as failed:
            await resolve(pg, a, payload)
        assert failed.value.status_code == 500
    assert await movement_snapshot(pg) == before
    assert await quantity(pg, variant=a.variant) == Decimal("0.5")
    first, duplicate = await asyncio.gather(resolve(pg, a, payload), resolve(pg, a, payload))
    assert first == duplicate == await resolve(pg, a, payload)
    assert first["total_quantity"] == "0.5" and first["location_count"] == 2
    assert await quantity(pg, variant=a.variant) == 0
    async with pg.session(pg.a) as db:
        variant = await db.get(ProductVariant, a.variant)
        assert variant.operational_hold == "NONE"
        exits = (await db.scalars(select(InventoryMovement).where(InventoryMovement.company_id == pg.a.company_id,
            InventoryMovement.product_variant_id == a.variant, InventoryMovement.destination_location_id.is_(None)))).all()
        assert sum((row.quantity for row in exits), Decimal(0)) == Decimal("0.5")
        assert len(exits) == 2
        if action == "RETURN_TO_VENDOR":
            snapshots = (await db.scalars(select(InventorySupplierEvidence).where(
                InventorySupplierEvidence.company_id == pg.a.company_id,
                InventorySupplierEvidence.movement_id.in_([row.id for row in exits])))).all()
            assert len(snapshots) == 2 and {row.supplier_id for row in snapshots} == {a.supplier}
    async with pg.session(pg.b) as db:
        assert await db.scalar(select(func.sum(InventoryBalance.on_hand_quantity)).where(
            InventoryBalance.company_id == pg.b.company_id, InventoryBalance.product_variant_id == b.variant)) == Decimal("0.125001")
    history = await movement_snapshot(pg)
    assert all(history[key] == row for key, row in before.items())
    with pytest.raises(HTTPException) as changed:
        await resolve(pg, a, payload.model_copy(update={"reason": "changed"}))
    assert changed.value.status_code == 409


async def test_whole_product_current_authorization_is_rechecked_on_completed_replay(pg):
    await prepare(pg)
    a, _ = await whole_stock(pg)
    async with AsyncSession(pg.admin_engine) as db:
        await _grant_location(db, pg.a, pg.a.locations[1],
            "inventory.read", "transfer.send", "inventory.disposal.confirm")
        await db.commit()
    payload = whole_payload()
    await resolve(pg, a, payload, pg.a.ordinary)
    before = await movement_snapshot(pg)
    async with AsyncSession(pg.admin_engine) as db:
        await db.execute(UserLocationAccess.__table__.delete().where(
            UserLocationAccess.company_id == pg.a.company_id,
            UserLocationAccess.driver_id == pg.a.ordinary.driver_id,
            UserLocationAccess.location_id == pg.a.locations[1]))
        await db.commit()
    with pytest.raises(HTTPException) as revoked:
        await resolve(pg, a, payload, pg.a.ordinary)
    assert revoked.value.status_code == 403
    assert await movement_snapshot(pg) == before


@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_different_concurrent_terminal_commands_cannot_overallocate_one_origin(pg, action):
    await prepare(pg)
    first = await stage(pg, action)
    second = await stage(pg, action)
    one, two = await asyncio.gather(
        terminal(pg, action, terminal_payload(pg, action, quantity="3")),
        terminal(pg, action, terminal_payload(pg, action, quantity="3")))
    assert one["movement_ids"] != two["movement_ids"]
    assert await quantity(pg) == 174
    async with pg.session(pg.a) as db:
        consumed = dict((await db.execute(select(InventoryMovement.transfer_header_id,
            func.sum(InventoryMovement.quantity)).where(
                InventoryMovement.company_id == pg.a.company_id,
                InventoryMovement.transfer_header_id.in_([first["header_id"], second["header_id"]]),
                InventoryMovement.destination_location_id.is_(None)
            ).group_by(InventoryMovement.transfer_header_id))).all())
        assert sorted(consumed.values()) == [Decimal("2"), Decimal("4")]


async def test_whole_reserved_stock_blocks_atomic_quality_and_changed_supplier_is_rejected(pg):
    await prepare(pg)
    a, b = await whole_stock(pg)
    with pytest.raises(HTTPException) as changed:
        await resolve(pg, a, whole_payload("RETURN_TO_VENDOR", supplier_id=b.supplier))
    assert changed.value.detail["code"] == "WHOLE_PRODUCT_RETURN_SUPPLIER_CHANGED"
    async with pg.session(pg.a) as db:
        await apply_inventory_movement(db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
            product_variant_id=a.variant, batch_id=a.batch, quantity=Decimal("0.000001"),
            movement_kind="RESERVATION", reservation_action="RESERVE", reference_type="CP34_RESERVE",
            reference_id="whole-quality-reservation", idempotency_key=str(uuid4()),
            source_location_id=pg.a.locations[0], destination_location_id=pg.a.locations[0],
            source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE")
        await db.commit()
    before = await movement_snapshot(pg)
    with pytest.raises(HTTPException) as reserved:
        await resolve(pg, a, whole_payload())
    assert reserved.value.detail["code"] == "WHOLE_PRODUCT_QUALITY_RESERVED_STOCK"
    assert await movement_snapshot(pg) == before


@pytest.mark.parametrize("method", ["MOVING_AVERAGE", "FIFO"])
@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_active_costing_transfers_preserve_value_and_only_terminal_exit_consumes_value(pg, method, action):
    from datetime import date, timedelta
    from models import Company, InventoryLocation, Product, InventoryCostState, InventoryCostEvent
    from domains.inventory_costing.service import set_cost_policy, activate_costing_for_first_receipt, build_purchase_cost_input
    from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        company = Company(name="Costed quality", company_code="CP34C-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD")
        db.add(company)
        await db.flush()
        owner = await seed_company_owner_fixture(db, company.id, password=PASSWORD)
        ordinary = await seed_ordinary_backoffice_fixture(db, company.id)
        receiver = await seed_ordinary_backoffice_fixture(db, company.id)
        product = Product(company_id=company.id, code="QUALITY-COST", name="Costed quality")
        db.add(product)
        await db.flush()
        variant = ProductVariant(company_id=company.id, product_id=product.id, name="Costed quality",
            sku="QUALITY-COST", base_uom_id=pg.a.uom_id, quantity_scale=0, quantity_step=Decimal("1"),
            lot_control_mode="REQUIRED", expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE", published_at=utc_now())
        db.add(variant)
        warehouses = [InventoryLocation(company_id=company.id, name="Costed warehouse", code="COST-" + str(i),
            location_type="WAREHOUSE") for i in range(3)]
        db.add_all(warehouses)
        await db.flush()
        batch = ProductBatch(company_id=company.id, product_variant_id=variant.id, batch_number="COST-LOT",
            expiry_date=date.today() - timedelta(days=1))
        db.add(batch)
        await db.flush()
        for location in warehouses:
            db.add(ProductLocation(company_id=company.id, location_id=location.id,
                product_variant_id=variant.id, created_by=owner.driver_id))
        tenant = NS(company_id=company.id, owner=owner, ordinary=ordinary, receiver=receiver,
            locations=[warehouses[0].id, warehouses[1].id], quarantine_id=warehouses[2].id,
            variant_id=variant.id, batch_id=batch.id, expired_batch_id=batch.id, uom_id=pg.a.uom_id)
        await db.commit()
    gate = NS(a=tenant, b=pg.b, admin_engine=pg.admin_engine, session=pg.session)
    await prepare(gate)
    async with gate.session(tenant) as db:
        await _grant_location(db, tenant, tenant.locations[0], "transfer.send")
        await set_cost_policy(db, company_id=tenant.company_id, actor_id=owner.driver_id,
            method=method, expected_version=0)
        await activate_costing_for_first_receipt(db, company_id=tenant.company_id, actor_id=owner.driver_id)
        from services import apply_inventory_movements_batch
        await apply_inventory_movements_batch(db, company_id=tenant.company_id, performed_by=owner.driver_id,
            movements=[dict(product_variant_id=tenant.variant_id, batch_id=tenant.batch_id, quantity=Decimal("20"),
                movement_kind="PHYSICAL", reference_type="INBOUND_SUPPLIER", reference_id="COSTED-RECEIPT",
                idempotency_key=str(uuid4()), source_location_id=None, destination_location_id=tenant.locations[0],
                source_stock_status=None, destination_stock_status="AVAILABLE",
                inventory_cost_input=build_purchase_cost_input(input_uom_id=tenant.uom_id,
                    input_quantity=Decimal("20"), input_unit_cost=Decimal("2"), base_quantity=Decimal("20")))])
        await db.commit()
    async def cost():
        async with gate.session(tenant) as db:
            state = await db.scalar(select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id, InventoryCostState.product_variant_id == tenant.variant_id))
            events = (await db.scalars(select(InventoryCostEvent).where(
                InventoryCostEvent.company_id == tenant.company_id).order_by(InventoryCostEvent.id))).all()
            return state.quantity, state.inventory_value, [(row.id, row.total_cost) for row in events]
    before = await cost()
    assert before[:2] == (Decimal("20"), Decimal("40"))
    await stage(gate, action)
    assert await cost() == before
    await terminal(gate, action, terminal_payload(gate, action))
    after = await cost()
    assert after[:2] == (Decimal("18"), Decimal("36"))
    assert after[2][0] == before[2][0] and len(after[2]) == 2
    assert after[2][-1][1] == Decimal("4")
