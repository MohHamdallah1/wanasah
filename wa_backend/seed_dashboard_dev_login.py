from __future__ import annotations

import asyncio

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import Company, DispatchRoute, Driver, InventoryLocation, Shop, Visit, Zone
from services import get_company_local_date

COMPANY_CODE = "DEV-01"
COMPANY_NAME = "شركة التطوير المحلية"
USERNAME = "devadmin"
PASSWORD = "DevAdmin#2026"
FULL_NAME = "مدير التطوير"

# بيانات فلاتر تطبيق المندوب (قائمة الزيارات: All / Completed / Pending + تبويب الطوارئ).
DRIVER_APP_USERNAME = "devdriver"
DRIVER_APP_PASSWORD = "DevDriver#2026"
DRIVER_APP_FULL_NAME = "مندوب التطوير"
DRIVER_APP_ZONE_NAME = "منطقة التطوير"
DRIVER_APP_SOURCE_LOCATION_CODE = "DEV-WH-01"
DRIVER_APP_SOURCE_LOCATION_NAME = "مستودع التطوير"


async def seed_driver_app_filter_data(db: AsyncSession, company: Company) -> None:
    """
    حقن بيانات فلاتر تطبيق المندوب بنفس نمط حقن لوحة التحكم أعلاه:
    حساب مندوب للدخول + منطقة + محلان + مستودع مصدر + خط سير يوم العمل
    + زيارات بحالات تغطي فلاتر قائمة الزيارات (Pending / طوارئ / Completed).
    يعمل داخل نفس معاملة الجلسة بعد تفعيل RLS، وقابل لإعادة التنفيذ (Idempotent).
    """

    rep = (
        await db.execute(
            select(Driver).where(
                Driver.company_id == company.id,
                Driver.username == DRIVER_APP_USERNAME,
            )
        )
    ).scalar_one_or_none()

    if rep is None:
        rep = Driver(
            company_id=company.id,
            username=DRIVER_APP_USERNAME,
            password_hash="TEMP",
            full_name=DRIVER_APP_FULL_NAME,
            is_active=True,
            is_admin=False,
            can_allow_debt=False,
        )
        rep.set_password(DRIVER_APP_PASSWORD)
        db.add(rep)
        await db.flush()
        print(f"DEV_DRIVER_CREATED={rep.id}")
    else:
        rep.full_name = DRIVER_APP_FULL_NAME
        rep.is_active = True
        rep.is_admin = False
        rep.set_password(DRIVER_APP_PASSWORD)
        print(f"DEV_DRIVER_REUSED={rep.id}")

    zone = (
        await db.execute(
            select(Zone).where(
                Zone.company_id == company.id,
                Zone.name == DRIVER_APP_ZONE_NAME,
            )
        )
    ).scalar_one_or_none()

    if zone is None:
        zone = Zone(
            company_id=company.id,
            name=DRIVER_APP_ZONE_NAME,
            is_active=True,
        )
        db.add(zone)
        await db.flush()
        print(f"DEV_ZONE_CREATED={zone.id}")
    else:
        zone.is_active = True
        print(f"DEV_ZONE_REUSED={zone.id}")

    shop_specs = [
        ("محل التطوير أ", 1),
        ("محل التطوير ب", 2),
    ]
    shops = []
    for shop_name, shop_sequence in shop_specs:
        shop = (
            await db.execute(
                select(Shop)
                .where(
                    Shop.company_id == company.id,
                    Shop.name == shop_name,
                )
                .order_by(Shop.id.asc())
            )
        ).scalars().first()
        if shop is None:
            shop = Shop(
                company_id=company.id,
                name=shop_name,
                zone_id=zone.id,
                sequence=shop_sequence,
                is_active=True,
            )
            db.add(shop)
            await db.flush()
            print(f"DEV_SHOP_CREATED={shop.id}")
        else:
            shop.is_active = True
            shop.is_archived = False
            print(f"DEV_SHOP_REUSED={shop.id}")
        shops.append(shop)

    # DispatchRoute.source_location_id إلزامي؛ مستودع تطوير مخصص للشركة.
    source_location = (
        await db.execute(
            select(InventoryLocation).where(
                InventoryLocation.company_id == company.id,
                InventoryLocation.code == DRIVER_APP_SOURCE_LOCATION_CODE,
            )
        )
    ).scalar_one_or_none()

    if source_location is None:
        source_location = InventoryLocation(
            company_id=company.id,
            name=DRIVER_APP_SOURCE_LOCATION_NAME,
            code=DRIVER_APP_SOURCE_LOCATION_CODE,
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add(source_location)
        await db.flush()
        print(f"DEV_SOURCE_LOCATION_CREATED={source_location.id}")
    else:
        print(f"DEV_SOURCE_LOCATION_REUSED={source_location.id}")

    # يوم العمل بتوقيت الشركة: نفس دالة النظام التي يستخدمها /driver/visits.
    operational_date = await get_company_local_date(db, company.id)

    # قيد uq_active_route_per_driver يسمح بخط سير مفتوح واحد فقط لكل مندوب.
    route = (
        await db.execute(
            select(DispatchRoute)
            .where(
                DispatchRoute.company_id == company.id,
                DispatchRoute.driver_id == rep.id,
                DispatchRoute.status.in_(["active", "waiting", "postponed"]),
            )
            .order_by(DispatchRoute.id.asc())
        )
    ).scalars().first()

    if route is None:
        route = DispatchRoute(
            company_id=company.id,
            zone_id=zone.id,
            driver_id=rep.id,
            source_location_id=source_location.id,
            dispatch_date=operational_date,
            status="waiting",
        )
        db.add(route)
        await db.flush()
        print(f"DEV_ROUTE_CREATED={route.id}")
    else:
        # خط سير تطوير لم يُستخدم بعد (بلا جلسة عمل أو سيارة) يُحدَّث تاريخه
        # ليوم العمل الحالي ليبقى مرئياً في /driver/visits؛ لا نلمس خطوطاً مربوطة بجلسة.
        if (
            route.status == "waiting"
            and route.work_session_id is None
            and route.vehicle_id is None
            and route.dispatch_date != operational_date
        ):
            route.dispatch_date = operational_date
            print(f"DEV_ROUTE_DATE_REFRESHED={route.id}")
        print(f"DEV_ROUTE_REUSED={route.id}")

    async def seed_visit(label: str, visit_shop: Shop, status: str, is_emergency: bool, sequence: int) -> None:
        visit = (
            await db.execute(
                select(Visit)
                .where(
                    Visit.company_id == company.id,
                    Visit.driver_id == rep.id,
                    Visit.shop_id == visit_shop.id,
                    Visit.operational_date == operational_date,
                    Visit.status == status,
                )
                .order_by(Visit.id.asc())
            )
        ).scalars().first()

        if visit is not None:
            print(f"DEV_VISIT_{label}_REUSED={visit.id}")
            return

        visit = Visit(
            company_id=company.id,
            driver_id=rep.id,
            shop_id=visit_shop.id,
            operational_date=operational_date,
            # نفس منطق update_visit: Completed يصاحبه NoSale (بلا آثار مالية أو مخزنية).
            outcome="NoSale" if status == "Completed" else "Pending",
            status=status,
            sequence=sequence,
            is_emergency=is_emergency,
        )
        db.add(visit)
        await db.flush()
        print(f"DEV_VISIT_{label}_CREATED={visit.id}")

    # زيارة معلقة عادية (فلتر Pending) + زيارة طوارئ معلقة (تبويب الطوارئ)
    # + زيارة مكتملة كمرجع لحالة Completed. الزيارة المكتملة لا تظهر في قائمة
    # التطبيق إلا مربوطة بجلسة عمل حقيقية، لذلك لا تُصنع جلسة مصطنعة هنا.
    await seed_visit("PENDING", shops[0], "Pending", False, 1)
    await seed_visit("EMERGENCY", shops[1], "Pending", True, 2)
    await seed_visit("COMPLETED", shops[0], "Completed", False, 3)

    print("DEV_DRIVER_APP_FILTERS_READY=OK")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        company = (
            await db.execute(
                select(Company).where(Company.company_code == COMPANY_CODE)
            )
        ).scalar_one_or_none()

        if company is None:
            company = Company(
                name=COMPANY_NAME,
                company_code=COMPANY_CODE,
                is_active=True,
                subscription_status="active",
                currency_code="JOD",
                timezone="Asia/Amman",
            )
            db.add(company)
            await db.flush()
            print(f"DEV_COMPANY_CREATED={company.id}")
        else:
            company.name = COMPANY_NAME
            company.is_active = True
            company.subscription_status = "active"
            print(f"DEV_COMPANY_REUSED={company.id}")

        # Mandatory for forced RLS before touching tenant-owned Driver rows.
        tenant_context.set(company.id)
        await db.execute(
            text("SELECT set_config('app.current_tenant', :v, false)"),
            {"v": str(company.id)},
        )

        admin = (
            await db.execute(
                select(Driver).where(
                    Driver.company_id == company.id,
                    Driver.username == USERNAME,
                )
            )
        ).scalar_one_or_none()

        if admin is None:
            admin = Driver(
                company_id=company.id,
                username=USERNAME,
                password_hash="TEMP",
                full_name=FULL_NAME,
                is_active=True,
                is_admin=True,
                can_allow_debt=True,
            )
            admin.set_password(PASSWORD)
            db.add(admin)
            await db.flush()
            print(f"DEV_ADMIN_CREATED={admin.id}")
        else:
            admin.full_name = FULL_NAME
            admin.is_active = True
            admin.is_admin = True
            admin.can_allow_debt = True
            admin.set_password(PASSWORD)
            print(f"DEV_ADMIN_REUSED={admin.id}")

        await seed_driver_app_filter_data(db, company)

        await db.commit()

        print("DEV_LOGIN_READY=OK")
        print(f"company_code={COMPANY_CODE}")
        print(f"username={USERNAME}")
        print(f"password={PASSWORD}")

        print("DEV_DRIVER_APP_LOGIN_READY=OK")
        print(f"company_code={COMPANY_CODE}")
        print(f"username={DRIVER_APP_USERNAME}")
        print(f"password={DRIVER_APP_PASSWORD}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())