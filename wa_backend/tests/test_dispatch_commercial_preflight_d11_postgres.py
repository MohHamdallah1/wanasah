"""D11 genuine restricted PG16 and Backoffice Bearer advisory, no launch side effects."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from models import (
    InventoryLock, PricePublication, StocktakeSession, TaxRuleComponent,
    TaxRuleSetVersion, TenantOperationalPolicy,
)
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
        assert components and all(str(c.rate) == "0.000000" for c in components)
        # Anonymous is never allowed to see company readiness.
        anonymous = await client.get(_path(body))
        assert anonymous.status_code == 401
        # A real FIELD login must not gain Dispatch Execute through this read.
        field = await _seed_mobile_uom_and_field(pg, tenant)
        field_auth = await _token(client, pg, tenant, field, "SyntheticFixture123")
        denied = await client.get(_path(body), headers=field_auth)
        assert denied.status_code == 403
    assert await _state(pg, tenant, key, vehicle_location) == before


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d11_real_409_authorities_price_tax_rounding_and_full_audit_lock(pg):
    tenant = pg.tenants[0]
    key, body, vehicle_location = await _prepared_route(pg, tenant)
    before = await _state(pg, tenant, key, vehicle_location)
    future = datetime.now(timezone.utc) + timedelta(days=2)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        # Missing published tax is NOT valid 0%; use real current revision.
        async with pg.session() as db:
            version = await db.scalar(select(TaxRuleSetVersion).where(
                TaxRuleSetVersion.company_id == tenant.company_id,
                TaxRuleSetVersion.status == "PUBLISHED",
            ))
            assert version is not None
            original_tax_at = version.published_at
            version.published_at = future
            await db.commit()
        no_tax = await client.get(_path(body), headers=owner)
        assert no_tax.status_code == 200 and no_tax.json()["ready"] is False
        assert no_tax.json()["checks"]["tax"]["code"] == "TAX_CONFIGURATION_REQUIRED"
        assert no_tax.json()["checks"]["pricing"]["ready"] is True
        async with pg.session() as db:
            version = await db.get(TaxRuleSetVersion, version.id)
            version.published_at = original_tax_at
            await db.commit()

        async with pg.session() as db:
            publication = await db.scalar(select(PricePublication).where(
                PricePublication.company_id == tenant.company_id,
                PricePublication.status == "PUBLISHED",
            ))
            assert publication is not None
            original_price_at = publication.published_at
            publication.published_at = future
            await db.commit()
        no_price = await client.get(_path(body), headers=owner)
        assert no_price.status_code == 200 and no_price.json()["ready"] is False
        assert no_price.json()["checks"]["pricing"]["code"] == "PRICE_NOT_RESOLVED"
        async with pg.session() as db:
            publication = await db.get(PricePublication, publication.id)
            publication.published_at = original_price_at
            await db.commit()

        async with pg.session() as db:
            rounding = await db.scalar(select(TenantOperationalPolicy).where(
                TenantOperationalPolicy.company_id == tenant.company_id,
                TenantOperationalPolicy.status == "PUBLISHED",
            ))
            assert rounding is not None
            original_end = rounding.effective_to
            rounding.effective_to = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        no_rounding = await client.get(_path(body), headers=owner)
        assert no_rounding.status_code == 200 and no_rounding.json()["ready"] is False
        assert no_rounding.json()["checks"]["rounding"]["code"] == "COMMERCIAL_ROUNDING_NOT_CONFIGURED"
        async with pg.session() as db:
            rounding = await db.get(TenantOperationalPolicy, rounding.id)
            rounding.effective_to = original_end
            await db.commit()

        async with pg.session() as db:
            stocktake = StocktakeSession(
                company_id=tenant.company_id, location_id=tenant.location_id,
                reference_number="D11-STK-" + uuid4().hex[:12],
                stocktake_type="FULL_COUNT", status="COUNTING",
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
        locked = await client.get(_path(body), headers=owner)
        assert locked.status_code == 200 and locked.json()["ready"] is False
        assert locked.json()["checks"]["warehouse"]["code"] == "SOURCE_WAREHOUSE_AUDIT_LOCK"
        assert locked.json()["checks"]["warehouse"]["context"]["stocktake_reference"].startswith("D11-STK-")
    # No preflight request is a POST, reserves an idempotency key or moves stock.
    assert await _state(pg, tenant, key, vehicle_location) == before
