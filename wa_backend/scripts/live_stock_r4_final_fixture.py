"""One accepted R2/R4 synthetic read fixture; bounded representative enrichment."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.models import CompanyPrincipal
from models import Company, InventoryLocation, ProductBatch, ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from tests.canonical_actor_fixtures import seed_company_owner_fixture


async def build(root, size, admin):
    path = root / "fixture.json"
    assert not path.exists(), "Refuse a second scale fixture in this acceptance"
    old_size = r4.seed.PRODUCTS
    r4.seed.PRODUCTS = size
    try:
        await r4.seed.seed_fixture(path)
        fixture = json.loads(path.read_text())
        await r4.enrich_fixture(fixture)
    finally:
        r4.seed.PRODUCTS = old_size
    c, w = fixture["company_id"], fixture["warehouse_id"]
    families = 500 if size == 50000 else 8
    async with AsyncSession(admin, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"), {"c": str(c)})
        first, last = (await db.execute(select(ProductVariant.id, ProductVariant.sku)
            .where(ProductVariant.company_id == c).order_by(ProductVariant.id).limit(1))).one(), (
            await db.execute(select(ProductVariant.id, ProductVariant.sku)
            .where(ProductVariant.company_id == c).order_by(ProductVariant.id.desc()).limit(1))).one()
        # Master-data diversity, no changes to search names/SKUs or stocked-variant count.
        family_ids = []
        for index in range(families):
            fid = await db.scalar(text("""
                INSERT INTO products(company_id,code,name,version,created_at,updated_at)
                VALUES(:c,:code,:name,1,NOW(),NOW()) RETURNING id
            """), {"c": c, "code": f"R4-F-{index:04d}", "name": f"R4 Family {index:04d}"})
            family_ids.append(int(fid))
        await db.execute(text("""
            UPDATE product_variants SET product_id=:ids[
                1 + ((right(sku,6)::integer - 1) % :families)]
            WHERE company_id=:c
        """.replace(":ids[", "(CAST(:ids AS integer[]))[")),
            {"ids": family_ids, "families": families, "c": c})
        # Duplicate names prove the stable ID tie-breaker, without changing SKUs.
        tied = (await db.execute(select(ProductVariant.id, ProductVariant.name).where(
            ProductVariant.company_id == c).order_by(ProductVariant.id).limit(2))).all()
        await db.execute(text("UPDATE product_variants SET name=:n WHERE company_id=:c AND id=:v"),
                         {"n": tied[0].name, "c": c, "v": tied[1].id})
        await r4.refresh_live_stock_keys(db, company_id=c, keys=[(w, tied[1].id)])
        # The small smoke fixture has every variant in the R4 enrichment set;
        # leave its last variant plain before adding the fractional detail case.
        if size <= 400:
            await db.execute(text("DELETE FROM inventory_stock_policies WHERE company_id=:c AND location_id=:w AND product_variant_id=:v"),
                             {"c": c, "w": w, "v": last.id})
            await db.execute(text("DELETE FROM inventory_balances WHERE company_id=:c AND location_id=:w AND product_variant_id=:v AND stock_status='DAMAGED'"),
                             {"c": c, "w": w, "v": last.id})
            await db.execute(text("UPDATE inventory_balances SET reserved_quantity=0 WHERE company_id=:c AND location_id=:w AND product_variant_id=:v"),
                             {"c": c, "w": w, "v": last.id})
            fixture["filter_rows"] = size - 1
        # 250 actual detail rows for one fractional variant; total remains exactly1.
        await db.execute(text("UPDATE product_variants SET quantity_step=0.000001 WHERE company_id=:c AND id=:v"),
                         {"c": c, "v": last.id})
        original_batch = await db.scalar(select(ProductBatch.id).where(
            ProductBatch.company_id == c, ProductBatch.product_variant_id == last.id))
        await db.execute(text("""
            UPDATE inventory_balances SET on_hand_quantity=0.004
            WHERE company_id=:c AND product_variant_id=:v AND location_id=:w
        """), {"c": c, "v": last.id, "w": w})
        await db.execute(text("""
            WITH added AS (
                INSERT INTO product_batches(company_id,product_variant_id,batch_number,
                    disposition,disposition_revision,is_active,created_at,updated_at)
                SELECT :c,:v,'R4-DETAIL-'||g,'RELEASED',1,true,NOW(),NOW()
                FROM generate_series(1,249)g RETURNING id
            )
            INSERT INTO inventory_balances(company_id,location_id,product_variant_id,batch_id,
                stock_status,on_hand_quantity,reserved_quantity,last_updated)
            SELECT :c,:w,:v,id,'AVAILABLE',0.004,0,NOW() FROM added
        """), {"c": c, "v": last.id, "w": w})
        await r4.refresh_live_stock_keys(db, company_id=c, keys=[(w, last.id)])
        source_batch = int(await db.scalar(select(ProductBatch.id).where(
            ProductBatch.company_id == c, ProductBatch.product_variant_id == first.id)))
        # Synthetic 201-location source fanout, below the existing 500-source guard.
        await db.execute(text("""
            WITH locations AS (
                INSERT INTO inventory_locations(company_id,name,code,location_type,
                    is_system_managed,version,is_active,created_at,updated_at)
                SELECT :c,'R4 Source '||lpad(g::text,3,'0'),'R4-SOURCE-'||g,
                    'WAREHOUSE',false,1,true,NOW(),NOW() FROM generate_series(1,200)g
                RETURNING id
            )
            INSERT INTO inventory_balances(company_id,location_id,product_variant_id,batch_id,
                stock_status,on_hand_quantity,reserved_quantity,last_updated)
            SELECT :c,id,:v,:b,'AVAILABLE',1,0,NOW() FROM locations
        """), {"c": c, "v": first.id, "b": source_batch})
        fixture.update(families=families + 1, family_ids=family_ids,
                       family_id=family_ids[0], first_variant_id=int(first.id),
                       heavy_variant_id=int(last.id), heavy_batch_id=int(original_batch),
                       source_batch_id=source_batch, source_locations=201,
                       detail_batches=250, rare_search=str(last.sku), first_sku=str(first.sku),
                       deep_ordinal=min(40000, size // 2))
        identities = {}
        for actor, profile_id in (("owner", fixture["owner_backoffice_user_id"]),
                                  ("restricted", fixture["ordinary_backoffice_user_id"])):
            from domains.identity.models import BackofficeUser
            principal = await db.scalar(select(CompanyPrincipal).join(BackofficeUser,
                (BackofficeUser.company_id == CompanyPrincipal.company_id) &
                (BackofficeUser.principal_id == CompanyPrincipal.id)).where(
                BackofficeUser.company_id == c, BackofficeUser.id == profile_id))
            identities[actor] = {"username": principal.username,
                "password": "R2PerfOwner123" if actor == "owner" else "R2PerfReader123",
                "company_code": await db.scalar(select(Company.company_code).where(Company.id == c))}
        foreign_company = Company(name="R4 foreign identity", company_code="R4-FOREIGN",
                                  subscription_status="active", currency_code="JOD", timezone="Asia/Amman")
        db.add(foreign_company)
        await db.flush()
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                         {"c": str(foreign_company.id)})
        foreign_owner = await seed_company_owner_fixture(db, foreign_company.id, password="R4ForeignReader123")
        foreign_location = InventoryLocation(company_id=foreign_company.id, name="R4 foreign warehouse",
                                            code="R4-FOREIGN-W", location_type="WAREHOUSE")
        db.add(foreign_location)
        await db.flush()
        foreign_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == foreign_owner.context.principal_id))
        identities["foreign"] = {"company_code": foreign_company.company_code,
                                  "username": foreign_name, "password": "R4ForeignReader123"}
        fixture["foreign_company_id"], fixture["foreign_warehouse_id"] = int(foreign_company.id), int(foreign_location.id)
        await db.commit()
    async with admin.begin() as conn:
        for table in ("products", "product_variants", "product_batches", "inventory_balances",
                      "inventory_locations", "inventory_live_stock_projection"):
            await conn.execute(text(f"ANALYZE {table}"))
    # Never persist passwords/tokens. The artifact describes synthetic stock only.
    path.write_text(json.dumps(fixture, indent=2))
    return fixture, identities


async def fingerprint(engine, fixture):
    """Read-only authority fingerprint around every performance measurement.

    Location-type totals stay separate; there is deliberately no Route join and
    no Warehouse+Vehicle compatibility total. Cost/movement/idempotency evidence
    is independent from the Live Stock projection.
    """
    async with r4.session(engine, fixture["company_id"]) as db:
        company_id = fixture["company_id"]
        row = (await db.execute(text("""
            SELECT
              (SELECT count(*) FROM product_variants WHERE company_id=:c),
              (SELECT sum(id::bigint*product_id) FROM product_variants WHERE company_id=:c),
              (SELECT count(*) FROM inventory_balances WHERE company_id=:c),
              (SELECT sum(on_hand_quantity) FROM inventory_balances WHERE company_id=:c),
              (SELECT sum(reserved_quantity) FROM inventory_balances WHERE company_id=:c),
              (SELECT count(*) FROM inventory_movements WHERE company_id=:c),
              (SELECT count(*) FROM inventory_cost_events WHERE company_id=:c),
              (SELECT count(*) FROM inventory_cost_layers WHERE company_id=:c),
              (SELECT count(*) FROM operation_idempotency WHERE company_id=:c),
              (SELECT sum(warehouse_on_hand) FROM inventory_live_stock_projection WHERE company_id=:c),
              (SELECT sum(warehouse_reserved) FROM inventory_live_stock_projection WHERE company_id=:c),
              (SELECT count(*) FROM dispatch_routes WHERE company_id=:c)
        """), {"c": company_id})).one()
        physical = (await db.execute(text("""
            SELECT l.location_type,
                   count(*) AS balance_rows,
                   coalesce(sum(b.on_hand_quantity),0) AS on_hand,
                   coalesce(sum(b.reserved_quantity),0) AS reserved
            FROM inventory_balances b
            JOIN inventory_locations l
              ON l.company_id=b.company_id AND l.id=b.location_id
            WHERE b.company_id=:c
            GROUP BY l.location_type
            ORDER BY l.location_type
        """), {"c": company_id})).mappings().all()
        costing = (await db.execute(text("""
            SELECT count(*) AS states,
                   coalesce(sum(quantity),0) AS quantity,
                   coalesce(sum(inventory_value),0) AS inventory_value
            FROM inventory_cost_states
            WHERE company_id=:c
        """), {"c": company_id})).mappings().one()
        assert row[0] == fixture["products"]
        assert row[5] == row[6] == row[7] == row[8] == 0
        return {
            "authority": [str(x) for x in row],
            "physical_by_location_type": [
                {key: str(value) for key, value in item.items()}
                for item in physical
            ],
            "cost_state": {key: str(value) for key, value in costing.items()},
        }
