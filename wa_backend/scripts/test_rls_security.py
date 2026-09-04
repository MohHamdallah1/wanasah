import pytest
import httpx
import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv # +++ سحق خطأ الـ None URL +++

load_dotenv() # +++ قراءة الـ .env +++

BASE_URL = "http://localhost:8000"

@pytest.fixture(scope="module")
async def clients():
    """تجهيز الاتصالات واستخراج المعرفات الحقيقية، مع طباعة لقطة الداتابيز عند الفشل"""
    db_url_admin = os.getenv("DATABASE_URL_MIGRATION")
    if db_url_admin:
        if db_url_admin.startswith("postgres://"):
            db_url_admin = db_url_admin.replace("postgres://", "postgresql+asyncpg://", 1)
        elif db_url_admin.startswith("postgresql://") and "asyncpg" not in db_url_admin:
            db_url_admin = db_url_admin.replace("postgresql://", "postgresql+asyncpg://", 1)

    app_db_url = os.getenv("DATABASE_URL")
    if app_db_url:
        if app_db_url.startswith("postgres://"):
            app_db_url = app_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif app_db_url.startswith("postgresql://") and "asyncpg" not in app_db_url:
            app_db_url = app_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. دخول وناسة
        res_w = await client.post("/login", json={"company_code": "WNS-01", "username": "admin_1", "password": "password"})
        assert res_w.status_code == 200, f"فشل دخول وناسة: {res_w.text}"
        token_w = res_w.json()["token"]
        headers_w = {"Authorization": f"Bearer {token_w}"}
        wns_comp_id = res_w.json()["company_id"]

        # 2. دخول النسر
        res_e = await client.post("/login", json={"company_code": "EAGLE-02", "username": "admin_2", "password": "password"})
        token_e = res_e.json()["token"]
        headers_e = {"Authorization": f"Bearer {token_e}"}
        egl_comp_id = res_e.json()["company_id"]

        # 3. جلب المستودعات
        w_locs = await client.get("/warehouse/locations", headers=headers_w)
        w_loc_data = w_locs.json()
        wns_main_loc = next((loc["id"] for loc in w_loc_data if "MAIN" in loc["code"].upper()), w_loc_data[0]["id"])
        wns_sec_loc = next((loc["id"] for loc in w_loc_data if "SEC" in loc["code"].upper()), w_loc_data[-1]["id"])
        
        w_inv = await client.get(f"/warehouse/inventory?location_id={wns_main_loc}", headers=headers_w)
        wns_prod_id = w_inv.json()[0]["id"]

        e_locs = await client.get("/warehouse/locations", headers=headers_e)
        e_loc_data = e_locs.json()
        egl_loc_id = next((loc["id"] for loc in e_loc_data if "MAIN" in loc["code"].upper()), e_loc_data[0]["id"])
        egl_sec_loc = next((loc["id"] for loc in e_loc_data if "SEC" in loc["code"].upper()), e_loc_data[-1]["id"])

        # 4. جلب حالة الداتابيز مباشرة (للتشخيص لو فشل الـ Setup)
        engine = create_async_engine(db_url_admin)
        async with engine.begin() as conn:

            await conn.execute(text("DELETE FROM login_attempts"))
            res_bal = await conn.execute(text("SELECT * FROM inventory_balances WHERE product_variant_id = :vid"), {"vid": wns_prod_id})
            balances = [dict(r._mapping) for r in res_bal.fetchall()]
            
            res_bat = await conn.execute(text("SELECT * FROM product_batches WHERE product_variant_id = :vid"), {"vid": wns_prod_id})
            batches = [dict(r._mapping) for r in res_bat.fetchall()]
            
            res_reason = await conn.execute(text("SELECT id FROM override_reasons WHERE company_id = :cid LIMIT 1"), {"cid": egl_comp_id})
            egl_reason_id = res_reason.scalar() or 1
            
            res_ledger = await conn.execute(text("SELECT id FROM warehouse_ledger WHERE reference_id = :ref LIMIT 1"), {"ref": f"TEST-INV-{wns_comp_id}"})
            wns_ledger_id = res_ledger.scalar() or 1
        await engine.dispose()

        # 4.5 تنظيف بقايا التشغيلات السابقة (جلسات جرد مفتوحة + أقفال جراحية + حوالات معلقة)
        #     لضمان تكرارية التشغيل (Test Repeatability) دون تعارض مع حالة قديمة
        engine_cleanup = create_async_engine(db_url_admin)
        async with engine_cleanup.begin() as conn:
            await conn.execute(text("UPDATE stocktake_sessions SET status = 'CANCELLED' WHERE status IN ('COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED')"))
            await conn.execute(text("UPDATE inventory_locks SET released_at = NOW() WHERE released_at IS NULL"))
            await conn.execute(text("UPDATE inventory_transfer_headers SET status = 'CANCELLED' WHERE status = 'PENDING'"))
        await engine_cleanup.dispose()

        # 5. توليد الأهداف لشركة وناسة
        payload_trans = {"source_location_id": wns_main_loc, "destination_location_id": wns_sec_loc, "items": [{"product_variant_id": wns_prod_id, "quantity": 1}]}
        res_trans = await client.post("/warehouse/unified/transfer/dispatch", json=payload_trans, headers=headers_w)
        
        # +++ إذا فشل هنا، سيطبع حالة الأرصدة والدفعات الحقيقية من داخل الداتابيز! +++
        assert res_trans.status_code == 200, f"فشل تجهيز الحوالة. الرد: {res_trans.text} | الأرصدة بالداتابيز: {balances} | الدفعات: {batches}"
        wns_transfer_id = res_trans.json()["header_id"]

        payload_stk = {"location_id": wns_main_loc, "stocktake_type": "FULL_COUNT", "notes": "Test Setup"}
        res_stk = await client.post("/warehouse/unified/stocktake/start", json=payload_stk, headers=headers_w)
        assert res_stk.status_code == 201, f"فشل الجرد: {res_stk.text}"
        wns_session_id = res_stk.json()["session_id"]
        wns_batch_id = batches[0]["id"] if batches else 1

        yield {
            "wns_headers": headers_w, "wns_loc_id": wns_main_loc, "wns_sec_loc": wns_sec_loc, 
            "wns_prod_id": wns_prod_id, "wns_batch_id": wns_batch_id, "wns_company_id": str(wns_comp_id),
            "wns_transfer_id": wns_transfer_id, "wns_session_id": wns_session_id, "wns_ledger_id": wns_ledger_id,
            "egl_headers": headers_e, "egl_loc_id": egl_loc_id, "egl_sec_loc": egl_sec_loc, 
            "egl_reason_id": egl_reason_id, "egl_company_id": str(egl_comp_id),
            "client": client, "app_db_url": app_db_url
        }

@pytest.mark.asyncio
async def test_vector_1_cross_tenant_auth(clients):
    res = await clients["client"].post("/login", json={"company_code": "WNS-01", "username": "admin_2", "password": "password"})
    assert res.status_code == 401

@pytest.mark.asyncio
async def test_vector_2_location_enumeration(clients):
    res = await clients["client"].get("/warehouse/locations", headers=clients["egl_headers"])
    loc_ids = [loc["id"] for loc in res.json()]
    assert clients["wns_loc_id"] not in loc_ids

@pytest.mark.asyncio
async def test_vector_3_inventory_probing(clients):
    res = await clients["client"].get(f"/warehouse/inventory?location_id={clients['wns_loc_id']}", headers=clients["egl_headers"])
    if res.status_code == 200:
        assert all(item["id"] != clients["wns_prod_id"] for item in res.json())
    else:
        assert res.status_code in [403, 404]

@pytest.mark.asyncio
async def test_vector_4_alert_leaks(clients):
    res = await clients["client"].get(f"/warehouse/alerts?location_id={clients['wns_loc_id']}", headers=clients["egl_headers"])
    if res.status_code == 200:
        assert all(item["product_variant_id"] != clients["wns_prod_id"] for item in res.json())
    else:
        assert res.status_code in [403, 404]

@pytest.mark.asyncio
async def test_vector_5_inbound_injection(clients):
    payload = {"location_id": clients["wns_loc_id"], "items": [{"product_variant_id": clients["wns_prod_id"], "quantity_packs": 100}]}
    res = await clients["client"].post("/warehouse/inbound", json=payload, headers=clients["egl_headers"])
    assert res.status_code in [403, 404, 400]

@pytest.mark.asyncio
async def test_vector_6_cross_tenant_transfer(clients):
    payload = {"source_location_id": clients["wns_loc_id"], "destination_location_id": clients["egl_loc_id"], "items": [{"product_variant_id": clients["wns_prod_id"], "quantity": 1}]}
    res = await clients["client"].post("/warehouse/unified/transfer/dispatch", json=payload, headers=clients["egl_headers"])
    assert res.status_code in [400, 403, 404]

@pytest.mark.asyncio
async def test_vector_7_cross_stocktake(clients):
    payload = {"location_id": clients["wns_loc_id"], "stocktake_type": "FULL_COUNT"}
    res = await clients["client"].post("/warehouse/unified/stocktake/start", json=payload, headers=clients["egl_headers"])
    assert res.status_code in [400, 403, 404]

@pytest.mark.asyncio
async def test_vector_8_fefo_hijack(clients):
    payload = {
        "source_location_id": clients["egl_loc_id"],
        "destination_location_id": clients["egl_sec_loc"], 
        "items": [{
            "product_variant_id": clients["wns_prod_id"], 
            "quantity": 1, 
            "is_fefo_override": True,
            "override_batch_id": clients["wns_batch_id"], 
            "override_reason_id": clients["egl_reason_id"] 
        }]
    }
    res = await clients["client"].post("/warehouse/unified/transfer/dispatch", json=payload, headers=clients["egl_headers"])
    assert res.status_code in [400, 403, 404]

@pytest.mark.asyncio
async def test_vector_9_unauthorized_transfer_cancel(clients):
    res = await clients["client"].post(f"/warehouse/unified/transfer/{clients['wns_transfer_id']}/cancel", headers=clients["egl_headers"])
    assert res.status_code in [400, 403, 404]

@pytest.mark.asyncio
async def test_vector_10_unauthorized_stocktake_approve(clients):
    res = await clients["client"].post(f"/warehouse/unified/stocktake/{clients['wns_session_id']}/approve", headers=clients["egl_headers"])
    assert res.status_code in [400, 403, 404]

@pytest.mark.asyncio
async def test_vector_12_legacy_ledger_mutation_leak_fixed(clients):
    payload = {"password": "password", "new_total_packs": 50, "notes": "Hacked"}
    res = await clients["client"].post(f"/warehouse/ledger/{clients['wns_ledger_id']}/adjust", json=payload, headers=clients["egl_headers"])
    assert res.status_code in [404, 403] 

@pytest.mark.asyncio
async def test_vector_14_positive_control(clients):
    res = await clients["client"].get(f"/warehouse/inventory?location_id={clients['wns_loc_id']}", headers=clients["wns_headers"])
    assert res.status_code == 200
    assert len(res.json()) > 0

@pytest.mark.asyncio
async def test_db_level_rls_enforcement_direct(clients):
    engine = create_async_engine(clients["app_db_url"])
    async with engine.connect() as conn:
        await conn.execute(text(f"SELECT set_config('app.current_tenant', '{clients['wns_company_id']}', false)"))
        res_pos = await conn.execute(text("SELECT * FROM inventory_balances WHERE product_variant_id = :vid"), {"vid": clients["wns_prod_id"]})
        assert len(res_pos.fetchall()) > 0, "فشل التحكم الإيجابي: الـ RLS يحجب البيانات عن صاحبها الحقيقي!"
        
        await conn.execute(text(f"SELECT set_config('app.current_tenant', '{clients['egl_company_id']}', false)"))
        res_neg = await conn.execute(text("SELECT * FROM inventory_balances WHERE product_variant_id = :vid"), {"vid": clients["wns_prod_id"]})
        assert len(res_neg.fetchall()) == 0, "🚨 كارثة: الـ RLS مخترق على مستوى قاعدة البيانات!"
        
    await engine.dispose()