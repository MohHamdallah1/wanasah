"""Rollback-only PostgreSQL correctness/equivalence gate for Phase 1.1.
Run against the local benchmark DB; fixture setup uses migration credentials,
endpoint reads use the runtime role, real RBAC and RLS. No fixtures are committed.
"""
from __future__ import annotations
import ast
import asyncio
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event, select, text, true
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi import HTTPException
import api.warehouse.live_stock as w
from context import tenant_context
from database import engine as runtime_engine
from models import (Company, Driver, Product, ProductVariant, ProductBatch, InventoryBalance,
                    InventoryLocation, InventoryStockPolicy, Vehicle, DispatchRoute, Zone,
                    UOM, Role, Permission, UserLocationAccess, role_permissions)
from scripts.seed_live_stock_scale import migration_url

BASELINE = "84ded66"
source = subprocess.check_output(
    ["git", "show", f"{BASELINE}:wa_backend/api/warehouse.py"], encoding="utf-8",
)
tree = ast.parse(source)
fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_warehouse_inventory")
fn.decorator_list = []
fn.name = "baseline_get"
namespace = dict(vars(w), true=true)
exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "baseline", "exec"), namespace)
baseline_get = namespace["baseline_get"]

async def main():
    engine = create_async_engine(migration_url())
    Session = async_sessionmaker(engine, expire_on_commit=False)
    checks = 0
    counts = {}
    captured = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with Session() as db:
            async def add(cls, **kw):
                obj = cls(**kw); db.add(obj); await db.flush(); return obj
            tag = "P11-" + uuid4().hex[:12]
            company = await add(Company, name=tag, company_code=tag)
            foreign = await add(Company, name=tag+"F", company_code=tag+"F")
            cid = company.id
            token = tenant_context.set(cid)
            await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c":str(cid)})
            admin = await add(Driver, company_id=cid, username=tag, full_name=tag, password_hash="not-a-login", is_admin=True)
            actor = await add(Driver, company_id=cid, username=tag+"R", full_name=tag, password_hash="not-a-login", is_admin=False)
            wh = await add(InventoryLocation, company_id=cid, code="WH", name="WH", location_type="WAREHOUSE")
            other = await add(InventoryLocation, company_id=cid, code="OTHER", name="OTHER", location_type="WAREHOUSE")
            foreign_wh = await add(InventoryLocation, company_id=foreign.id, code="WH", name="WH", location_type="WAREHOUSE")
            zone = await add(Zone, company_id=cid, name=tag)
            vehicle_locations=[]
            for i in range(2):
                vehicle=await add(Vehicle,company_id=cid,plate_number=tag+str(i))
                loc=await add(InventoryLocation,company_id=cid,code="V"+str(i),name="V",location_type="VEHICLE",vehicle_id=vehicle.id)
                vehicle_locations.append(loc)
                await add(DispatchRoute,company_id=cid,zone_id=zone.id,vehicle_id=vehicle.id,source_location_id=other.id,status="closed")
                await add(DispatchRoute,company_id=cid,zone_id=zone.id,vehicle_id=vehicle.id,source_location_id=wh.id,status="closed")
            role=await add(Role,company_id=cid,name=tag)
            permission=await db.scalar(select(Permission.id).where(Permission.code=="inventory.read"))
            if permission is None:
                permission=(await add(Permission,code="inventory.read")).id
            await db.execute(role_permissions.insert().values(company_id=cid,role_id=role.id,permission_id=permission))
            for loc in [wh,other,vehicle_locations[0]]:
                await add(UserLocationAccess,company_id=cid,driver_id=actor.id,location_id=loc.id,role_id=role.id)
            product=await add(Product,company_id=cid,code=tag,name=tag)
            foreign_product=await add(Product,company_id=foreign.id,code=tag,name=tag)
            uom=await db.scalar(select(UOM.id).where(UOM.code=="EACH"))
            async def variant(name,company_id=cid,active=True,location=None):
                v=await add(ProductVariant,company_id=company_id,product_id=product.id if company_id==cid else foreign_product.id,
                    name=name,sku=name,base_uom_id=uom,quantity_scale=0,quantity_step=1,
                    lifecycle_status="ACTIVE" if active else "RETIRING",published_at=datetime(2025,1,1),
                    retired_at=None if active else datetime(2025,2,1),expiry_control_mode="NONE",lot_control_mode="NONE")
                batch=await add(ProductBatch,company_id=company_id,product_variant_id=v.id,batch_number=name)
                if location is not None:
                    await add(InventoryBalance,company_id=company_id,location_id=location.id,product_variant_id=v.id,batch_id=batch.id,
                              on_hand_quantity=10,reserved_quantity=2,stock_status="AVAILABLE")
                return v,batch
            variants=[];policies=[]
            for i in range(240):
                v,b=await variant(f"Fixture {i:04}",location=wh);variants.append(v)
                policies.append(await add(InventoryStockPolicy,company_id=cid,location_id=wh.id,product_variant_id=v.id,minimum_quantity=1))
                if i==0:
                    for status,qty in [("BLOCKED",2),("DAMAGED",3)]:
                        await add(InventoryBalance,company_id=cid,location_id=wh.id,product_variant_id=v.id,batch_id=b.id,on_hand_quantity=qty,reserved_quantity=0,stock_status=status)
            active,_=await variant("Visible ACTIVE")
            stored,_=await variant("Visible retired warehouse",active=False,location=wh)
            carried,_=await variant("Visible retired vehicle",active=False,location=vehicle_locations[0])
            denied,_=await variant("Hidden retired vehicle",active=False,location=vehicle_locations[1])
            elsewhere,_=await variant("Hidden retired other warehouse",active=False,location=other)
            alien,_=await variant("Fixture foreign",company_id=foreign.id,location=foreign_wh)
            role_name=engine.dialect.identifier_preparer.quote(runtime_engine.url.username)
            async def read_role():
                await db.execute(text("SET LOCAL ROLE "+role_name))
                await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"),{"c":str(cid)})
            async def page(*,who=actor,location=wh,limit=50,cursor=None,alerts=False,search=None):
                kw=dict(location_id=location.id,limit=limit,cursor=cursor,only_alerts=alerts,search=search,db=db,current_admin=who)
                old=await baseline_get(**kw)
                captured.clear()
                new=await w.get_warehouse_inventory(**kw)
                count=len(captured)
                assert new==old, "Payload/cursor/quantity/cost equivalence"
                assert new["total"] is None
                assert not any("LATERAL" in sql.upper() or "COUNT(" in sql.upper() or "OVER (" in sql.upper() for sql in captured)
                return new,count
            await read_role()
            all_ids=[];cursor=None
            while True:
                data,count=await page(cursor=cursor)
                all_ids.extend(x["id"] for x in data["items"])
                if not data["has_more"]:break
                cursor=data["next_cursor"]
            expected={v.id for v in variants}|{active.id,stored.id,carried.id}
            assert len(all_ids)==len(set(all_ids)) and set(all_ids)==expected
            checks+=6
            actor_summary=await w.get_warehouse_inventory_summary(wh.id,db,actor)
            admin_summary=await w.get_warehouse_inventory_summary(wh.id,db,admin)
            assert actor_summary["stock_total"]==len(expected)
            assert admin_summary["stock_total"]==len(expected)+1
            assert actor_summary["alert_count"]==0
            assert admin_summary["alert_count"]==0
            checks+=4
            other_page,_=await page(location=other,search="retired")
            assert {x["id"] for x in other_page["items"]}=={elsewhere.id};checks+=1
            for endpoint in [w.get_warehouse_inventory_summary,w.get_warehouse_inventory_alert_summary]:
                try:await endpoint(foreign_wh.id,db,actor)
                except HTTPException as e:assert e.status_code==404
                else:raise AssertionError("foreign warehouse leaked")
                checks+=1
            for size in [50,200]:
                _,counts[str(size)]=await page(limit=size)
            assert counts["50"]==counts["200"];checks+=1
            distributions={"first":set(range(60)),"last":set(range(180,240)),"sparse":{239},"zero":set(),"all":set(range(240))}
            for name,selected in distributions.items():
                await db.execute(text("RESET ROLE"))
                for i,p in enumerate(policies):p.minimum_quantity=8 if i in selected else 1
                await db.flush();await read_role()
                ids=[];cursor=None
                while True:
                    data,_=await page(alerts=True,search="Fixture",cursor=cursor)
                    ids.extend(x["id"] for x in data["items"])
                    if not data["has_more"]:break
                    cursor=data["next_cursor"]
                assert ids==[variants[i].id for i in sorted(selected)],name
                summary=await w.get_warehouse_inventory_summary(wh.id,db,actor)
                legacy_summary=await w.get_warehouse_inventory_alert_summary(wh.id,db,actor)
                assert summary["alert_count"]==len(selected),name
                assert legacy_summary["alert_count"]==summary["alert_count"],name
                # Verify SKU search semantics as well as names and cursor paging.
                data,_=await page(alerts=True,search="Fixture 0239")
                assert len(data["items"])==int(239 in selected)
                checks+=4
            await db.rollback()
            tenant_context.reset(token)
        print(f"CORRECTNESS_EQUIVALENCE=PASS CHECKS={checks} SQL_COUNTS={counts} FIXTURES=ROLLED_BACK")
    finally:
        await engine.dispose()
        await runtime_engine.dispose()

if __name__=="__main__":
    asyncio.run(main())
