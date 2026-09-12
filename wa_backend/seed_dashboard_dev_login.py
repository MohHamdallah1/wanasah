from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import Company, Driver

COMPANY_CODE = "DEV-01"
COMPANY_NAME = "شركة التطوير المحلية"
USERNAME = "devadmin"
PASSWORD = "DevAdmin#2026"
FULL_NAME = "مدير التطوير"


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

        await db.commit()

        print("DEV_LOGIN_READY=OK")
        print(f"company_code={COMPANY_CODE}")
        print(f"username={USERNAME}")
        print(f"password={PASSWORD}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())