import argparse
import asyncio
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

BASELINE_FILE = Path(".concurrency_audit_baseline.json")

API_URL = os.getenv("API_URL", "http://localhost:8000")
COMPANY_CODE = os.getenv("COMPANY_CODE", "WNS-01")
USERNAME = os.getenv("TEST_USERNAME", "admin_1")
PASSWORD = os.getenv("TEST_PASSWORD", "password")


def get_async_db_url():
    db_url = os.getenv("DATABASE_URL_MIGRATION")

    if not db_url:
        raise RuntimeError("DATABASE_URL_MIGRATION غير موجود في .env")

    if db_url.startswith("postgres://"):
        return db_url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1
        )

    if db_url.startswith("postgresql://"):
        return db_url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1
        )

    if db_url.startswith("postgresql+psycopg2://"):
        return db_url.replace(
            "postgresql+psycopg2://",
            "postgresql+asyncpg://",
            1
        )

    return db_url


def get_test_locations():
    login = requests.post(
        f"{API_URL}/login",
        json={
            "company_code": COMPANY_CODE,
            "username": USERNAME,
            "password": PASSWORD,
        },
        timeout=20,
    )
    login.raise_for_status()

    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{API_URL}/warehouse/locations",
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()

    locations = response.json()

    main = [
        loc for loc in locations
        if "MAIN" in loc["code"].upper()
    ]

    sec = [
        loc for loc in locations
        if "SEC" in loc["code"].upper()
    ]

    if len(main) != 1:
        raise RuntimeError(
            f"يجب إيجاد MAIN واحد بالضبط، الموجود: "
            f"{[(x['id'], x['code']) for x in main]}"
        )

    if len(sec) != 1:
        raise RuntimeError(
            f"يجب إيجاد SEC واحد بالضبط، الموجود: "
            f"{[(x['id'], x['code']) for x in sec]}"
        )

    return main[0], sec[0]


async def get_db_state(conn, company_id, source_id, destination_id):
    result = await conn.execute(
        text("""
            SELECT
                product_variant_id,
                location_id,
                SUM(on_hand_quantity) AS qty
            FROM inventory_balances
            WHERE company_id = :company_id
              AND location_id IN (:source_id, :destination_id)
            GROUP BY product_variant_id, location_id
        """),
        {
            "company_id": company_id,
            "source_id": source_id,
            "destination_id": destination_id,
        }
    )

    state = {}

    for row in result.fetchall():
        product_id = str(row.product_variant_id)
        location_id = str(row.location_id)

        state[f"{product_id}:{location_id}"] = int(row.qty)

    return state


async def get_negative_balances(conn, company_id):
    result = await conn.execute(
        text("""
            SELECT COUNT(*)
            FROM inventory_balances
            WHERE company_id = :company_id
              AND on_hand_quantity < 0
        """),
        {"company_id": company_id}
    )

    return int(result.scalar() or 0)


async def get_deadlocks(conn):
    result = await conn.execute(
        text("""
            SELECT deadlocks
            FROM pg_stat_database
            WHERE datname = current_database()
        """)
    )

    return int(result.scalar() or 0)


async def snapshot():
    print("\n📸 إنشاء Snapshot قبل اختبار الـ Concurrency...\n")

    source, destination = get_test_locations()

    engine = create_async_engine(get_async_db_url())

    async with engine.connect() as conn:
        company_result = await conn.execute(
            text("""
                SELECT id
                FROM companies
                WHERE company_code = :code
            """),
            {"code": COMPANY_CODE}
        )

        company_id = company_result.scalar()

        if company_id is None:
            raise RuntimeError(
                f"الشركة {COMPANY_CODE} غير موجودة"
            )

        state = await get_db_state(
            conn,
            company_id,
            source["id"],
            destination["id"],
        )

        deadlocks = await get_deadlocks(conn)
        negatives = await get_negative_balances(conn, company_id)

    await engine.dispose()

    baseline = {
        "company_id": company_id,
        "source": {
            "id": source["id"],
            "code": source["code"],
        },
        "destination": {
            "id": destination["id"],
            "code": destination["code"],
        },
        "state": state,
        "deadlocks": deadlocks,
    }

    BASELINE_FILE.write_text(
        json.dumps(
            baseline,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8",
    )

    total = sum(state.values())

    print(f"🏭 المصدر: {source['code']} ({source['id']})")
    print(f"🏪 الوجهة: {destination['code']} ({destination['id']})")
    print(f"📦 إجمالي المخزون قبل الاختبار: {total}")
    print(f"🔒 Deadlocks الحالية: {deadlocks}")

    if negatives:
        print(f"❌ يوجد {negatives} رصيد سالب قبل الاختبار!")
    else:
        print("✅ لا يوجد رصيد سالب قبل الاختبار.")

    print("\n✅ Snapshot محفوظ.")
    print("الآن شغّل Locust، وبعد انتهائه نفّذ:")
    print("python audit_concurrency.py check")


async def check():
    if not BASELINE_FILE.exists():
        raise RuntimeError(
            "لا يوجد Snapshot سابق. "
            "شغّل snapshot قبل اختبار Locust."
        )

    print("\n🔍 بدء التدقيق الجنائي بعد اختبار الـ Concurrency...\n")

    baseline = json.loads(
        BASELINE_FILE.read_text(encoding="utf-8")
    )

    company_id = baseline["company_id"]
    source_id = baseline["source"]["id"]
    destination_id = baseline["destination"]["id"]

    before = baseline["state"]

    engine = create_async_engine(get_async_db_url())

    async with engine.connect() as conn:
        after = await get_db_state(
            conn,
            company_id,
            source_id,
            destination_id,
        )

        negatives = await get_negative_balances(
            conn,
            company_id
        )

        deadlocks_after = await get_deadlocks(conn)

    await engine.dispose()

    deadlocks_before = baseline["deadlocks"]

    products = set()

    for key in before:
        products.add(key.split(":")[0])

    for key in after:
        products.add(key.split(":")[0])

    failed = False

    print(
        f"🏭 المصدر: {baseline['source']['code']}"
    )
    print(
        f"🏪 الوجهة: {baseline['destination']['code']}\n"
    )

    for product_id in sorted(products, key=int):
        source_key = f"{product_id}:{source_id}"
        destination_key = f"{product_id}:{destination_id}"

        src_before = before.get(source_key, 0)
        dst_before = before.get(destination_key, 0)

        src_after = after.get(source_key, 0)
        dst_after = after.get(destination_key, 0)

        total_before = src_before + dst_before
        total_after = src_after + dst_after

        # المنتجات التي لم تتغير نتجاوزها
        if (
            src_before == src_after
            and dst_before == dst_after
        ):
            continue

        print(f"📦 Product Variant ID: {product_id}")
        print(
            f"   Source: {src_before} -> {src_after}"
        )
        print(
            f"   Destination: {dst_before} -> {dst_after}"
        )
        print(
            f"   Total: {total_before} -> {total_after}"
        )

        if src_after < 0 or dst_after < 0:
            failed = True
            print("   ❌ رصيد سالب!")

        if total_before != total_after:
            failed = True
            print(
                "   ❌ فقدان أو استنساخ مخزون!"
            )
        else:
            print(
                "   ✅ Conservation صحيح."
            )

        source_delta = src_after - src_before
        destination_delta = dst_after - dst_before

        if source_delta != -destination_delta:
            failed = True
            print(
                "   ❌ حركة المصدر لا تطابق حركة الوجهة."
            )
        else:
            print(
                "   ✅ الخصم والإضافة متطابقان."
            )

        print()

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if negatives > 0:
        failed = True
        print(
            f"❌ يوجد {negatives} رصيد سالب في قاعدة البيانات."
        )
    else:
        print("✅ لا يوجد أي رصيد سالب.")

    deadlock_delta = deadlocks_after - deadlocks_before

    if deadlock_delta > 0:
        failed = True
        print(
            f"❌ حدث {deadlock_delta} Deadlock أثناء الاختبار."
        )
    else:
        print("✅ لم يتم تسجيل أي Deadlock جديد.")

    total_before_all = sum(before.values())
    total_after_all = sum(after.values())

    if total_before_all != total_after_all:
        failed = True
        print(
            f"❌ إجمالي المخزون تغير: "
            f"{total_before_all} -> {total_after_all}"
        )
    else:
        print(
            f"✅ إجمالي المخزون محفوظ: "
            f"{total_after_all}"
        )

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if failed:
        print(
            "\n🚨 RESULT: FAIL — فشل اختبار سلامة الـ Concurrency."
        )
        raise SystemExit(1)

    print(
        "\n🏆 RESULT: PASS — سلامة الأرصدة والـ Deadlocks اجتازت الاختبار."
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["snapshot", "check"]
    )

    args = parser.parse_args()

    if args.mode == "snapshot":
        await snapshot()
    else:
        await check()


if __name__ == "__main__":
    asyncio.run(main())