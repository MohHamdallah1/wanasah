"""D11 genuine restricted PG16 and Backoffice Bearer advisory, no launch side effects."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from decimal import Decimal
from models import InventoryLock, StocktakeSession
from domains.taxation.models import TaxRuleComponent, TaxRuleSetVersion
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import (
    _prepared_route, _state,
)
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _owner, _real_http, _token,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import _seed_mobile_uom_and_field

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_D11_PG_GATE") != "1",
        reason="Requires disposable restricted PG16 and real Backoffice Bearer D11 gate",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _path(body: dict) -> str:
    return (
        "/dispatch/route/commercial-preflight"
        f"?zone_id={body['zone_id']}&driver_id={body['driver_id']}"
        f"&vehicle_id={body['vehicle_id']}"
        f"&source_location_id={body['source_location_id']}"
    )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d11_authoritative_published_zero_tax_read_no_mutation(pg):
    tenant = pg.tenants[0]
    key, body, vehicle_location = await _prepared_route(pg, tenant)
    before = await _state(pg, tenant, key, vehicle_location)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        response = await client.get(_path(body), headers=owner)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ready"] is True and data["advisory"] is True
        assert data["currency_code"] == "JOD"
        assert data["checks"]["pricing"]["context"]["publication_revision"] > 0
        assert data["checks"]["pricing"]["context"]["assignment_revision"] > 0
        assert data["checks"]["tax"]["context"]["revision"] > 0
        assert data["checks"]["rounding"]["context"]["revision"] > 0
        assert all(x["ready"] is True for x in data["checks"].values())
        async with pg.session() as db:
            components = (await db.scalars(select(TaxRuleComponent).join(
                TaxRuleSetVersion,
                (TaxRuleComponent.tax_rule_set_version_id == TaxRuleSetVersion.id)
                & (TaxRuleComponent.company_id == TaxRuleSetVersion.company_id),
            ).where(
                TaxRuleSetVersion.company_id == tenant.company_id,
                TaxRuleSetVersion.status == "PUBLISHED",
            ))).all()
        assert components and all(c.rate == Decimal("0") for c in components)
        # Anonymous is never allowed to see company readiness.
        anonymous = await client.get(_path(body))
        assert anonymous.status_code == 401
        # A real FIELD login must not gain Dispatch Execute through this read.
        field = await _seed_mobile_uom_and_field(pg, tenant)
        field_auth = await _token(client, pg, tenant, field, "SyntheticFixture123")
        denied = await client.get(_path(body), headers=field_auth)
        assert denied.status_code == 401  # Field JWT is not a Backoffice credential
        ordinary = await _token(client, pg, tenant, tenant.ordinary, "SyntheticFixture123")
        forbidden = await client.get(_path(body), headers=ordinary)
        assert forbidden.status_code == 403  # valid non-owner, no dispatch.execute
    assert await _state(pg, tenant, key, vehicle_location) == before


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d11_missing_canonical_publications_are_not_assumed_zero(pg):
    # No prices are ever published for this tenant before the read.
    # Never UPDATE immutable published Pricing/Tax history just for a test.
    from models import Zone
    from tests.test_dispatch_p0_route_stock_safety_postgres import _vehicle
    tenant = pg.tenants[0]
    field = await _seed_mobile_uom_and_field(pg, tenant)
    vehicle, _ = await _vehicle(pg, tenant)
    async with pg.session() as db:
        zone = Zone(
            company_id=tenant.company_id, name="D11 unconfigured " + uuid4().hex[:8],
            is_active=True,
        )
        db.add(zone)
        await db.flush()
        zone_id = int(zone.id)
        await db.commit()
    body = {
        "zone_id": zone_id, "driver_id": int(field.driver.id),
        "vehicle_id": vehicle, "source_location_id": tenant.location_id,
    }
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        unconfigured = await client.get(_path(body), headers=owner)
        assert unconfigured.status_code == 200, unconfigured.text
        checks = unconfigured.json()["checks"]
        assert unconfigured.json()["ready"] is False
        assert checks["pricing"]["code"] == "PRICE_NOT_RESOLVED"
        assert checks["tax"]["code"] == "TAX_CONFIGURATION_REQUIRED"
        assert checks["rounding"]["code"] == "COMMERCIAL_ROUNDING_NOT_CONFIGURED"
        assert checks["warehouse"]["ready"] is True
        assert checks["vehicle"]["ready"] is True


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d11_real_full_warehouse_audit_lock_blocks_launch_without_side_effect(pg):
    tenant = pg.tenants[0]
    key, body, vehicle_location = await _prepared_route(pg, tenant)
    before = await _state(pg, tenant, key, vehicle_location)
    async with pg.session() as db:
        stocktake = StocktakeSession(
            company_id=tenant.company_id, location_id=tenant.location_id,
            reference_number="D11-STK-" + uuid4().hex[:12],
            stocktake_type="FULL_COUNT", status="DRAFT",
            started_by=tenant.owner.driver_id,
        )
        db.add(stocktake)
        await db.flush()
        db.add(InventoryLock(
            company_id=tenant.company_id,
            stocktake_session_id=stocktake.id,
            location_id=tenant.location_id,
            product_variant_id=None, batch_id=None,
            created_by=tenant.owner.driver_id,
        ))
        await db.commit()
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        locked = await client.get(_path(body), headers=owner)
        assert locked.status_code == 200 and locked.json()["ready"] is False
        assert locked.json()["checks"]["warehouse"]["code"] == "SOURCE_WAREHOUSE_AUDIT_LOCK"
        assert locked.json()["checks"]["warehouse"]["context"]["stocktake_reference"].startswith("D11-STK-")
    assert await _state(pg, tenant, key, vehicle_location) == before
