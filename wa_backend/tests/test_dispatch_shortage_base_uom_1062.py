"""#1062 contract: real signed PG16 shortage quantity uses SKU canonical base UOM.

Opt-in only against migrated disposable localhost:55439/
wanasah_no_lot_contract_test, restricted non-BYPASSRLS runtime and separate
fixture migrator. Synthetic tenants only, no POST implementation or stock writes.
"""
from __future__ import annotations

import os
from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dispatch_product_schemas import DispatchProductPageResponse
from database import engine as http_engine
from domains.uom_authority import build_variant_uom_authority
from models import (
    InventoryBalance, InventoryMovement, ProductUomConversion,
    ProductVariant, ShortageRequest, UOM, Visit, utc_now,
)
from schemas import CreateShortageItem
from tests.test_dispatch_shop_finance_edit_v1_postgres import _add_shop, _owner, _real_http, _zone
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_SHORTAGE_1062_PG_GATE") != "1",
    reason="Only explicit restricted PG16 55439 #1062 signed-HTTP acceptance",
)


def test_schema_quantity_and_wire_shape_are_unchanged():
    descriptor = CreateShortageItem.model_json_schema(by_alias=True)["properties"]["quantity"]
    assert "canonical base stock UOM" in descriptor["description"]
    assert "50 PACK" in descriptor["description"]
    assert descriptor["default"] == 1
    payload = dict(shopId=1, zoneId=2, productId=3, quantity=10)
    assert CreateShortageItem.model_validate(payload).quantity == 10
    assert CreateShortageItem.model_validate({k: v for k, v in payload.items() if k != "quantity"}).quantity == 1
    for bad in (0, -1):
        with pytest.raises(ValueError):
            CreateShortageItem.model_validate({**payload, "quantity": bad})
    with pytest.raises(ValueError):
        CreateShortageItem.model_validate({**payload, "uomId": 7})
    assert not {"uomId", "uom_id", "base_uom_code"} & set(
        CreateShortageItem.model_json_schema(by_alias=True)["properties"]
    )

    # Preserve the old LOAD JSON fields exactly, especially load:null.
    load = DispatchProductPageResponse.model_validate({
        "items": [dict(id="7", name="Load", load=None)],
        "has_more": False, "next_cursor": None,
    }).model_dump(mode="json")
    assert load["items"] == [dict(id="7", name="Load", load=None)]
    shortage = DispatchProductPageResponse.model_validate({
        "items": [dict(id="8", name="Shortage", load=None, base_uom_code="PACK")],
        "has_more": False, "next_cursor": None,
    }).model_dump(mode="json")
    assert shortage["items"] == [
        dict(id="8", name="Shortage", load=None, base_uom_code="PACK"),
    ]


async def _check_pg():
    async with http_engine.connect() as db:
        row = (await db.execute(text(
            "SELECT current_database(),current_user,inet_server_port(),"
            "rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(row) == ("wanasah_no_lot_contract_test", "wanasah_app", 55439, False, False)
        for name in ("product_variants", "product_uom_conversions", "shortage_requests"):
            flags = (await db.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:name)"
            ), {"name": name})).one()
            assert tuple(flags) == (True, True), name
    await http_engine.dispose()


async def _pack_50(gate, home):
    # UOM is a global shared catalog; SKU is tenant-owned and determines its base.
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        ids = {}
        for code in ("PACK", "CARTON"):
            uom = await db.scalar(select(UOM).where(UOM.code == code))
            if uom is None:
                uom = UOM(code=code, name="1062 " + code + " " + uuid4().hex[:8])
                db.add(uom)
                await db.flush()
            ids[code] = int(uom.id)
        await db.commit()
    async with gate.session() as db:
        variant = await db.get(ProductVariant, home.variant_id)
        variant.base_uom_id = ids["PACK"]
        variant.quantity_scale = 0
        variant.quantity_step = Decimal("1")
        db.add(ProductUomConversion(
            company_id=home.company_id, product_variant_id=home.variant_id,
            from_uom_id=ids["CARTON"], to_uom_id=ids["PACK"],
            numerator=Decimal("50"), denominator=Decimal("1"), quantity_scale=0,
        ))
        await db.commit()
    async with gate.session() as db:
        variant = await db.get(ProductVariant, home.variant_id)
        conversions = (await db.scalars(select(ProductUomConversion).where(
            ProductUomConversion.company_id == home.company_id,
            ProductUomConversion.product_variant_id == home.variant_id,
        ))).all()
        authority = build_variant_uom_authority(variant, conversions)
        assert authority.base_uom_id == ids["PACK"]
        assert authority.factor_to_base(ids["PACK"]) == Fraction(1)
        assert authority.factor_to_base(ids["CARTON"]) == Fraction(50)
    return ids


async def _physical(pg_gate, tenant):
    async with pg_gate.session() as db:
        result = []
        for model in (InventoryMovement, InventoryBalance, Visit):
            value = await db.scalar(select(func.count()).select_from(model).where(
                model.company_id == tenant.company_id,
            ))
            result.append(int(value or 0))
        return tuple(result)


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_pack_carton_signed_discovery_and_actual_post_stores_ten_pack(pg):
    await _check_pg()
    home, foreign = pg.tenants
    units = await _pack_50(pg, home)
    async with pg.session(1) as db:
        other_base = await db.scalar(select(ProductVariant.base_uom_id).where(
            ProductVariant.company_id == foreign.company_id,
            ProductVariant.id == foreign.variant_id,
        ))
        assert other_base != units["PACK"]
    zone = await _zone(pg, home)
    initial = await _physical(pg, home)
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        outsider = await _owner(client, pg, foreign)
        assert (await client.get("/dispatch/products", params={"purpose": "SHORTAGE"})).status_code == 401
        catalog = await client.get("/dispatch/products", headers=owner,
                                   params={"purpose": "SHORTAGE", "limit": 80})
        assert catalog.status_code == 200, catalog.text
        option = next(item for item in catalog.json()["items"] if item["id"] == str(home.variant_id))
        assert option == {
            "id": str(home.variant_id), "name": "No-lot SKU",
            "load": None, "base_uom_code": "PACK",
        }
        assert catalog.json()["has_more"] is False
        foreign_catalog = await client.get("/dispatch/products", headers=outsider,
                                           params={"purpose": "SHORTAGE", "limit": 80})
        assert foreign_catalog.status_code == 200
        assert str(home.variant_id) not in {
            x["id"] for x in foreign_catalog.json()["items"]
        }
        other_option = next(x for x in foreign_catalog.json()["items"]
                            if x["id"] == str(foreign.variant_id))
        assert other_option["base_uom_code"] == "EACH"

        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        before = await _physical(pg, home)
        created = await client.post("/dispatch/shortages", headers=owner, json=[{
            "shopId": shop, "zoneId": zone,
            "productId": home.variant_id, "quantity": 10,
        }])
        assert created.status_code == 201, created.text
        shortage_list = await client.get("/dispatch/shortages", headers=owner)
        assert shortage_list.status_code == 200, shortage_list.text
        entries = [x for x in shortage_list.json()
                   if x["shopId"] == str(shop) and x["productId"] == str(home.variant_id)]
        assert len(entries) == 1 and entries[0]["quantity"] == 10
        async with pg.session() as db:
            saved = (await db.scalars(select(ShortageRequest).where(
                ShortageRequest.company_id == home.company_id,
                ShortageRequest.shop_id == shop,
                ShortageRequest.product_variant_id == home.variant_id,
            ))).all()
        assert len(saved) == 1 and saved[0].quantity == 10  # PACK, not 500 PACK
        assert await _physical(pg, home) == before == initial
        foreign_shortages = await client.get("/dispatch/shortages", headers=outsider)
        assert foreign_shortages.status_code == 200
        assert entries[0]["id"] not in {x["id"] for x in foreign_shortages.json()}


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_82_stockless_products_signed_80_cursor_no_n_plus_one(pg):
    await _check_pg()
    home, foreign = pg.tenants
    unit = await _pack_50(pg, home)
    product_ids = [int(home.variant_id)]
    async with pg.session() as db:
        template = await db.get(ProductVariant, home.variant_id)
        values = []
        for _ in range(81):
            code = "U1062-" + uuid4().hex[:14]
            values.append(dict(
                company_id=home.company_id, product_id=template.product_id,
                name="1062 stockless " + code, sku=code,
                base_uom_id=unit["PACK"], quantity_scale=0, quantity_step=Decimal(1),
                lot_control_mode="OPTIONAL", expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE", operational_hold="NONE", published_at=utc_now(),
            ))
        created_ids = (await db.scalars(
            insert(ProductVariant).returning(ProductVariant.id), values,
        )).all()
        product_ids.extend(map(int, created_ids))
        await db.commit()
    assert len(product_ids) == len(set(product_ids)) == 82
    before = await _physical(pg, home)
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        outsider = await _owner(client, pg, foreign)
        all_items, counts = [], []
        cursor = None
        original_cursor = None
        for wanted in (80, 2):
            statements = []
            def record(conn, cursor, statement, params, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)
            event.listen(http_engine.sync_engine, "before_cursor_execute", record)
            try:
                params = {"purpose": "SHORTAGE", "limit": 80}
                if cursor:
                    params["cursor"] = cursor
                response = await client.get("/dispatch/products", headers=owner, params=params)
            finally:
                event.remove(http_engine.sync_engine, "before_cursor_execute", record)
            assert response.status_code == 200, response.text
            page = response.json()
            assert len(page["items"]) == wanted
            assert all(x["load"] is None and x["base_uom_code"] == "PACK"
                       for x in page["items"])
            all_items += page["items"]
            joins = [sql for sql in statements if
                     "FROM product_variants" in sql and "JOIN uom" in sql]
            assert len(joins) == 1, ("Unbounded or missing UOM join", len(joins))
            counts.append(len(statements))
            cursor = page["next_cursor"]
            if wanted == 80:
                original_cursor = cursor
                assert page["has_more"] is True and cursor
            else:
                assert page["has_more"] is False and cursor is None
        assert {x["id"] for x in all_items} == set(map(str, product_ids))
        assert counts[0] <= counts[1] + 3, counts
        assert await _physical(pg, home) == before
        foreign_cursor = await client.get("/dispatch/products", headers=outsider,
            params={"purpose": "SHORTAGE", "limit": 80, "cursor": original_cursor})
        assert foreign_cursor.status_code == 400
        assert foreign_cursor.json()["error"]["code"] == "DISPATCH_PRODUCT_CURSOR_INVALID"
        forged = await client.get("/dispatch/products", headers=owner,
            params={"purpose": "SHORTAGE", "limit": 80, "cursor": original_cursor + "x"})
        assert forged.status_code == 400
        assert forged.json()["error"]["code"] == "DISPATCH_PRODUCT_CURSOR_INVALID"
        assert (await client.get("/dispatch/products", headers=owner,
            params={"purpose": "SHORTAGE", "limit": 81})).status_code == 422
