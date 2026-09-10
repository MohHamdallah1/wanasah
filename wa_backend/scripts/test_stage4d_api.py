"""HTTP + real PostgreSQL/RLS gate. Retains isolated cluster artifacts.

No application database connection or startup jobs. Authentication and permission
dependencies are real; only get_db is bound to a newly created test database.
"""
import os
os.environ['SECRET_KEY'] = 'Stage4DIsolatedTestKeyOnly2026ABCDEFGHIJKLMNOPQRSTUVWXYZ'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://unused@127.0.0.1:1/unused'

from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from test_stage4d_postgres import cluster  # noqa: F401
from models import Base, Company, Driver, InventoryLocation, Vehicle, Zone, DispatchRoute
from database import get_db, on_checkout, tenant_context
from api import auth, warehouse, dispatch


@pytest_asyncio.fixture
async def api(cluster):
    name = 'api_' + uuid.uuid4().hex
    role = 'app_' + uuid.uuid4().hex
    admin = await asyncpg.connect(host=cluster, user='postgres', database='postgres')
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.execute(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS')
    setup = create_async_engine('postgresql+asyncpg://postgres@/'+name, connect_args={'host':cluster})
    async with setup.begin() as conn:
        # SQLAlchemy 2.0 does not compile PostgreSQL's column-list form
        # ``SET NULL (column)``. The test never deletes those parents; normalize
        # only this process-local metadata so the production model stays intact.
        for table in Base.metadata.tables.values():
            for constraint in table.foreign_key_constraints:
                if constraint.ondelete and constraint.ondelete.startswith('SET NULL ('):
                    constraint.ondelete = 'SET NULL'
        await conn.run_sync(Base.metadata.create_all)
        for table in Base.metadata.tables.values():
            if 'company_id' in table.c:
                await conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
                await conn.execute(text(f'ALTER TABLE "{table.name}" FORCE ROW LEVEL SECURITY'))
                predicate = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
                await conn.execute(text(f'CREATE POLICY tenant_isolation_policy ON "{table.name}" USING ({predicate}) WITH CHECK ({predicate})'))
        await conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        await conn.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
        await conn.execute(text(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
    async with AsyncSession(setup) as db:
        db.add_all([Company(id=i, name='Same name',company_code=f'TEST{i}') for i in [1,2]])
        await db.commit()
        for i,c,admin_flag in [(1,1,True),(2,1,False),(3,2,True),(4,1,False)]:
            user=Driver(id=i,company_id=c,username=f'user{i}',full_name='Same name',is_admin=admin_flag)
            user.set_password('Stage4D-password')
            db.add(user)
        db.add_all([Vehicle(id=i,company_id=c,plate_number='Same-plate',vehicle_type='Van') for i,c in [(10,1),(20,2)]])
        db.add_all([Zone(id=i,company_id=c,name='Same zone') for i,c in [(10,1),(20,2)]])
        await db.commit()
        db.add_all([InventoryLocation(id=i,company_id=c,name='Same warehouse',code=str(i),location_type='WAREHOUSE')
                    for i,c in [(100,1),(101,1),(200,2)]])
        db.add_all([InventoryLocation(id=i,company_id=c,name='Same vehicle',code=str(i),location_type='VEHICLE',vehicle_id=v)
                    for i,c,v in [(110,1,10),(210,2,20)]])
        await db.commit()
        db.add_all([DispatchRoute(id=i,company_id=c,zone_id=z,vehicle_id=v,source_location_id=loc,status='waiting')
                    for i,c,z,v,loc in [(10,1,10,10,100),(20,2,20,20,200)]])
        await db.commit()
    engine=create_async_engine(f'postgresql+asyncpg://{role}@/{name}',connect_args={'host':cluster},pool_size=1,max_overflow=0)
    event.listen(engine.sync_engine,'checkout',on_checkout)
    async def isolated_db():
        marker=tenant_context.set(None)
        try:
            async with AsyncSession(engine,expire_on_commit=False) as session:
                yield session
        finally:
            tenant_context.reset(marker)
    app=FastAPI()
    app.include_router(auth.router)
    app.include_router(warehouse.router)
    app.include_router(dispatch.router)
    app.dependency_overrides[get_db]=isolated_db
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://isolated') as client:
        def headers(user=1,company=1,refresh=False):
            token=(auth.create_refresh_token({'sub':str(user)},company) if refresh else
                   auth.create_access_token({'sub':str(user)},company))
            return {'Authorization':'Bearer '+token}
        yield client, headers, setup
    await engine.dispose()
    await setup.dispose()
    await admin.close()


async def create_role(client, headers, codes):
    response=await client.post('/inventory/access/roles',headers=headers(),json={'name':'Role '+uuid.uuid4().hex,'permissions':codes})
    assert response.status_code==201,response.text
    return response.json()['id']


async def grant(client, headers, role, location, user=2):
    response=await client.post(f'/inventory/access/users/{user}/grants',headers=headers(),json={'role_id':role,'location_id':location})
    assert response.status_code==201,response.text


@pytest.mark.asyncio
async def test_http_permissions_lists_mutations_replay_and_revocation(api):
    client,headers,setup=api
    role=await create_role(client,headers,['location.read','location.update','inventory.read'])
    await grant(client,headers,role,100)
    limited=headers(2)
    response=await client.get('/warehouse/locations/manage?include_inactive=true&limit=1',headers=limited)
    assert response.status_code==200,response.text
    assert response.json()['total']==1
    assert [row['id'] for row in response.json()['items']]==[100]
    assert response.json()['has_more'] is False
    batch=await client.post('/inventory/access/locations/capabilities',headers=limited,json={'location_ids':[100,101,200]})
    assert batch.status_code==200,batch.text
    assert set(batch.json()['locations'])=={'100'}
    payload={'request_id':str(uuid.uuid4()),'name':'Updated by authorized operator','code':'WH100'}
    for loc,code in [(101,403),(200,404)]:
        denied=await client.patch(f'/warehouse/locations/{loc}',headers=limited,json=payload)
        assert denied.status_code==code,denied.text
    updated=await client.patch('/warehouse/locations/100',headers=limited,json=payload)
    assert updated.status_code==200,updated.text
    replay=await client.patch('/warehouse/locations/100',headers=limited,json=payload)
    assert replay.status_code==200 and replay.json()==updated.json()
    grants=await client.get('/inventory/access/users/2/grants',headers=headers())
    grant_id=grants.json()['items'][0]['id']
    revoked=await client.delete(f'/inventory/access/users/2/grants/{grant_id}?scope=location',headers=headers())
    assert revoked.status_code==200,revoked.text
    assert (await client.patch('/warehouse/locations/100',headers=limited,json=payload)).status_code==403
    assert (await client.get('/inventory/access/me',headers=limited)).status_code==403
    # Inspect with setup role: denied requests did not alter either other warehouse.
    async with setup.connect() as db:
        names=(await db.execute(text('SELECT name FROM inventory_locations WHERE id IN (101,200)'))).scalars().all()
        assert names==['Same warehouse','Same warehouse']


@pytest.mark.asyncio
async def test_http_tenant_escalation_tokens_and_pool_reuse(api):
    client,headers,_=api
    role=await create_role(client,headers,['location.read'])
    await grant(client,headers,role,100)
    for path in ['/inventory/access/roles','/inventory/access/users','/inventory/access/catalog']:
        assert (await client.get(path,headers=headers(2))).status_code==403
    assert (await client.post('/inventory/access/roles',headers=headers(2),json={'name':'Admin','permissions':['location.create']})).status_code==403
    for user,loc in [(3,100),(2,200)]:
        response=await client.post(f'/inventory/access/users/{user}/grants',headers=headers(),json={'role_id':role,'location_id':loc})
        assert response.status_code==404,response.text
    foreign_role=await client.post('/inventory/access/roles',headers=headers(3,2),json={'name':'Foreign','permissions':['location.read']})
    assert foreign_role.status_code==201,foreign_role.text
    response=await client.post('/inventory/access/users/2/grants',headers=headers(),json={'role_id':foreign_role.json()['id'],'location_id':100})
    assert response.status_code==404,response.text
    assert (await client.get('/inventory/access/me',headers=headers(2,1,True))).status_code==401
    assert (await client.get('/inventory/access/me',headers=headers(2,2))).status_code==401
    # The one-connection pool must reset its tenant across repeated companies.
    for user,company,expected in [(1,1,{100,101}),(3,2,{200}),(2,1,{100}),(3,2,{200})]:
        response=await client.get('/warehouse/locations/manage',headers=headers(user,company))
        assert response.status_code==200,response.text
        assert {r['id'] for r in response.json()['items']}==expected


@pytest.mark.asyncio
async def test_http_dispatch_requires_both_source_and_actual_vehicle(api):
    client,headers,_=api
    read=await create_role(client,headers,['dispatch.read'])
    execute=await create_role(client,headers,['dispatch.execute'])
    await grant(client,headers,read,100)
    await grant(client,headers,execute,100)
    response=await client.get('/dispatch/active_routes',headers=headers(2))
    assert response.status_code==200 and response.json()==[],response.text
    await grant(client,headers,read,110)
    response=await client.get('/dispatch/active_routes',headers=headers(2))
    assert response.status_code==200,response.text
    assert [r['id'] for r in response.json()]==['10']
    assert response.json()[0]['can_execute'] is False
    assert response.json()[0]['sessionBound'] is False
    init=await client.get('/dispatch/init',headers=headers(2))
    assert init.status_code==200,init.text
    assert init.json()['warehouses']==[{'id':'100','label':'Same warehouse (100)','can_execute':True}]
    assert init.json()['vehicles']==[{'id':'10','label':'Van - Same-plate','can_execute':False}]
    status=await client.get('/warehouse/status?location_id=100',headers=headers(2))
    assert status.status_code==200 and status.json()['status']=='ACTIVE',status.text
    denied=await client.put('/dispatch/route/10/status',headers=headers(2),json={'status':'postponed'})
    assert denied.status_code==403,denied.text
    await grant(client,headers,execute,110)
    response=await client.get('/dispatch/active_routes',headers=headers(2))
    assert response.json()[0]['can_execute'] is True
    assert (await client.put('/dispatch/route/20/status',headers=headers(2),json={'status':'postponed'})).status_code==404


@pytest.mark.asyncio
async def test_http_dashboard_login_grants_and_revocation(api):
    client,headers,_=api
    role=await create_role(client,headers,['location.read'])
    await grant(client,headers,role,100)
    for user,expected in [(1,200),(2,200),(4,401)]:
        response=await client.post('/login',json={'company_code':'TEST1','username':f'user{user}','password':'Stage4D-password'})
        assert response.status_code==expected,response.text
        if expected==200:
            assert response.json()['dashboard_access'] is True
            assert response.json()['is_admin'] is (user==1)
            capabilities=await client.get('/inventory/access/me',headers={'Authorization':'Bearer '+response.json()['token']})
            assert capabilities.status_code==200,capabilities.text


@pytest.mark.asyncio
async def test_http_inbound_is_atomic_tenant_scoped_and_revocation_precedes_replay(api):
    client,headers,setup=api
    async with setup.begin() as db:
        await db.execute(text("INSERT INTO uom(id,name,code) VALUES (1,'Pack','PACK'),(2,'Carton','CARTON')"))
        await db.execute(text("""
            INSERT INTO products(id,company_id,base_name,created_at)
            VALUES (1000,1,'Item',CURRENT_TIMESTAMP),(2000,2,'Item',CURRENT_TIMESTAMP)
        """))
        await db.execute(text("""
            INSERT INTO product_variants
                (id,company_id,product_id,base_uom_id,variant_name,sku,packs_per_carton,
                 price_per_carton,price_per_pack,is_active,default_max_samples_per_day)
            VALUES (1000,1,1000,1,'Tenant 1 item','SKU-1',12,10,1,true,0),
                   (2000,2,2000,1,'Tenant 2 item','SKU-2',12,10,1,true,0)
        """))
    role=await create_role(client,headers,[
        'location.read','catalog.read','catalog.manage','inbound.create','inventory.read','ledger.read','ledger.adjust'
    ])
    await grant(client,headers,role,100)
    limited=headers(2)
    catalog=await client.get('/product_variants/simple/cursor',headers=limited)
    assert catalog.status_code==200,catalog.text
    assert [item['id'] for item in catalog.json()['items']]==[1000]
    request_id=str(uuid.uuid4())
    payload={'request_id':request_id,'location_id':100,'reference_id':'INV-4D-INBOUND-1','notes':'atomic',
             'items':[{'product_variant_id':1000,'quantity_packs':27,'batch_number':'B-1',
                       'production_date':'2026-01-01','expiry_date':'2099-01-01'}]}
    created=await client.post('/warehouse/inbound',headers=limited,json=payload)
    assert created.status_code==201,created.text
    replay=await client.post('/warehouse/inbound',headers=limited,json=payload)
    assert replay.status_code==201 and replay.json()==created.json(),replay.text
    live=await client.get('/warehouse/inventory/cursor?location_id=100&limit=50',headers=limited)
    assert live.status_code==200,live.text
    live_payload=live.json()
    assert live_payload['total']==1
    assert live_payload['alert_count']==0
    assert live_payload['alert_samples']==[]
    assert live_payload['has_more'] is False and live_payload['next_cursor'] is None
    assert live_payload['items']==[{
        'id':1000,'name':'Tenant 1 item','sku':'SKU-1','packs_per_carton':12,
        'available_packs':27,'reserved_packs':0,'blocked_packs':0,
        'total_packs':27,'damaged_packs':0,'available_cartons':2,
        'available_loose_packs':3,'min_threshold':0,
    }]
    ledger=await client.get('/warehouse/ledger/cursor?location_id=100&limit=20',headers=limited)
    assert ledger.status_code==200,ledger.text
    ledger_payload=ledger.json()
    assert ledger_payload['total']==1
    assert ledger_payload['available_types']==['INBOUND_SUPPLIER']
    assert ledger_payload['has_more'] is False and ledger_payload['next_cursor'] is None
    inbound_entry=ledger_payload['items'][0]
    assert inbound_entry['product_variant_id']==1000
    assert inbound_entry['type']=='INBOUND_SUPPLIER'
    assert inbound_entry['quantity_packs']==27
    assert inbound_entry['balance_before']==0 and inbound_entry['balance_after']==27
    assert inbound_entry['reference']=='INV-4D-INBOUND-1'
    assert inbound_entry['date'].endswith(('Z','+00:00'))
    adjusted=await client.post(
        f"/warehouse/ledger/{inbound_entry['id']}/adjust",headers=limited,
        json={'password':'Stage4D-password','new_total_packs':20},
    )
    assert adjusted.status_code==200,adjusted.text
    adjusted_ledger=await client.get('/warehouse/ledger/cursor?location_id=100&limit=20',headers=limited)
    assert adjusted_ledger.status_code==200,adjusted_ledger.text
    adjusted_payload=adjusted_ledger.json()
    assert adjusted_payload['total']==2
    assert adjusted_payload['available_types']==['INBOUND_CORRECTION','INBOUND_SUPPLIER']
    correction,original=adjusted_payload['items']
    assert (correction['type'],correction['quantity_packs'])==('INBOUND_CORRECTION',-7)
    assert (correction['balance_before'],correction['balance_after'])==(27,20)
    assert (original['type'],original['quantity_packs'])==('INBOUND_SUPPLIER',27)
    catalog_payload={
        'variant_name':'Shared catalog item','sku':'CAT-SAME','price_per_carton':'12.500',
        'packs_per_carton':10,'price_per_pack':'1.250','min_threshold_packs':5,'max_samples':2,
    }
    # A location grant must never confer this company-only authority.
    denied_catalog=await client.post('/warehouse/product_variants',headers=limited,json=catalog_payload)
    assert denied_catalog.status_code==403,denied_catalog.text
    company_product=await client.post('/warehouse/product_variants',headers=headers(),json=catalog_payload)
    assert company_product.status_code==201,company_product.text
    company_product_id=company_product.json()['product_id']
    foreign_product=await client.post('/warehouse/product_variants',headers=headers(3,2),json=catalog_payload)
    assert foreign_product.status_code==201,foreign_product.text
    foreign_product_id=foreign_product.json()['product_id']
    assert foreign_product_id != company_product_id
    refreshed_catalog=await client.get('/product_variants/simple/cursor',headers=limited)
    assert refreshed_catalog.status_code==200,refreshed_catalog.text
    refreshed_ids={item['id'] for item in refreshed_catalog.json()['items']}
    assert refreshed_ids=={1000,company_product_id}
    assert foreign_product_id not in refreshed_ids
    foreign={**payload,'location_id':200,'request_id':str(uuid.uuid4()),'reference_id':'FOREIGN'}
    assert (await client.post('/warehouse/inbound',headers=limited,json=foreign)).status_code==404
    assert (await client.get('/warehouse/inventory/cursor?location_id=200',headers=limited)).status_code==404
    assert (await client.get('/warehouse/ledger/cursor?location_id=200',headers=limited)).status_code==404
    grants=await client.get('/inventory/access/users/2/grants',headers=headers())
    grant_id=grants.json()['items'][0]['id']
    assert (await client.delete(f'/inventory/access/users/2/grants/{grant_id}?scope=location',headers=headers())).status_code==200
    assert (await client.post('/warehouse/inbound',headers=limited,json=payload)).status_code==403
    assert (await client.get('/warehouse/inventory/cursor?location_id=100',headers=limited)).status_code==403
    assert (await client.get('/warehouse/ledger/cursor?location_id=100',headers=limited)).status_code==403
    async with setup.connect() as db:
        quantity=await db.scalar(text("""
            SELECT on_hand_quantity FROM inventory_balances
            WHERE company_id=1 AND location_id=100 AND product_variant_id=1000
        """))
        movements=await db.scalar(text("""
            SELECT count(*) FROM inventory_movements
            WHERE company_id=1 AND reference_type='INBOUND_SUPPLIER' AND reference_id='INV-4D-INBOUND-1'
        """))
        corrections=await db.scalar(text("""
            SELECT count(*) FROM inventory_movements
            WHERE company_id=1 AND reference_type='INBOUND_CORRECTION' AND reference_id='INV-4D-INBOUND-1'
        """))
        policy_locations=(await db.execute(text("""
            SELECT location_id FROM inventory_stock_policies
            WHERE company_id=1 AND product_variant_id=:product_id
            ORDER BY location_id
        """), {'product_id':company_product_id})).scalars().all()
        foreign_policy_locations=(await db.execute(text("""
            SELECT location_id FROM inventory_stock_policies
            WHERE company_id=2 AND product_variant_id=:product_id
            ORDER BY location_id
        """), {'product_id':foreign_product_id})).scalars().all()
        assert quantity==20
        assert movements==1
        assert corrections==1
        assert policy_locations==[100,101]
        assert foreign_policy_locations==[200]
