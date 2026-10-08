from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

COMPANY_CODE = "WNS-01"
COMPANY_NAME = "شركة وناسة للتطوير"
ADMIN_USERNAME = "admin_1"
ADMIN_PASSWORD = "password"
ADMIN_FULL_NAME = "مدير التطوير"


def _assert_local_development_target() -> None:
    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    if environment not in {"development", "dev", "local", "test"}:
        raise RuntimeError(
            "seed_dev.py is development-only. Set ENVIRONMENT=development explicitly."
        )

    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL is required.")
    url = make_url(raw_url.replace("postgres://", "postgresql://", 1))
    host = (url.host or "").lower()
    database = (url.database or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Development seed refuses non-local database hosts.")
    if not any(marker in database for marker in ("dev", "test", "local")):
        raise RuntimeError(
            "Development seed refuses databases whose name does not contain dev/test/local."
        )


async def _ensure_company_and_admin():
    from context import tenant_context
    from database import AsyncSessionLocal
    from domains.inventory_costing.service import provision_default_cost_policy
    from domains.pricing.publishing import create_assignment, create_price_book
    from models import Branch, Company, Driver, PriceBook, PriceBookAssignment

    async with AsyncSessionLocal() as db:
        company = await db.scalar(
            select(Company).where(Company.company_code == COMPANY_CODE)
        )
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
        else:
            company.name = COMPANY_NAME
            company.is_active = True
            company.subscription_status = "active"

        tenant_context.set(company.id)
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
            {"tenant_id": str(company.id)},
        )

        branch = await db.scalar(
            select(Branch).where(
                Branch.company_id == company.id,
                Branch.branch_code == "HQ",
            )
        )
        if branch is None:
            db.add(
                Branch(
                    company_id=company.id,
                    name="الفرع الرئيسي",
                    branch_code="HQ",
                    is_active=True,
                )
            )

        admin = await db.scalar(
            select(Driver).where(
                Driver.company_id == company.id,
                Driver.username == ADMIN_USERNAME,
            )
        )
        if admin is None:
            admin = Driver(
                company_id=company.id,
                username=ADMIN_USERNAME,
                password_hash="TEMP",
                full_name=ADMIN_FULL_NAME,
                is_active=True,
                is_admin=True,
                can_allow_debt=True,
            )
            admin.set_password(ADMIN_PASSWORD)
            db.add(admin)
            await db.flush()
        else:
            admin.full_name = ADMIN_FULL_NAME
            admin.is_active = True
            admin.is_admin = True
            admin.can_allow_debt = True
            admin.set_password(ADMIN_PASSWORD)
            await db.flush()

        default_book = await db.scalar(
            select(PriceBook).where(
                PriceBook.company_id == company.id,
                PriceBook.code == "DEFAULT",
            )
        )
        if default_book is None:
            default_book = await create_price_book(
                db,
                company_id=company.id,
                actor_id=admin.id,
                code="DEFAULT",
                name="Default selling prices",
                currency_code=company.currency_code,
            )

        default_assignment = await db.scalar(
            select(PriceBookAssignment).where(
                PriceBookAssignment.company_id == company.id,
                PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
                PriceBookAssignment.scope_id.is_(None),
            )
        )
        if default_assignment is None:
            await create_assignment(
                db,
                company_id=company.id,
                actor_id=admin.id,
                price_book_id=default_book.id,
                scope_type="COMPANY_DEFAULT",
                scope_id=None,
                allow_offers=True,
                priority=0,
                effective_from=datetime.now(timezone.utc),
                effective_to=None,
            )

        await provision_default_cost_policy(
            db,
            company_id=company.id,
            actor_id=admin.id,
        )
        await db.commit()
        return company.id, admin.id


async def main() -> None:
    _assert_local_development_target()
    company_id, admin_id = await _ensure_company_and_admin()
    print("DEV_SEED_READY=OK")
    print(f"company_id={company_id}")
    print(f"admin_id={admin_id}")
    print(f"company_code={COMPANY_CODE}")
    print(f"username={ADMIN_USERNAME}")
    print(f"password={ADMIN_PASSWORD}")
    from database import engine
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
