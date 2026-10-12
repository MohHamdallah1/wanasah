from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
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


async def _ensure_dev_password_hash(existing_hash: str | None = None) -> str:
    if existing_hash:
        try:
            matches = await asyncio.to_thread(
                bcrypt.checkpw,
                ADMIN_PASSWORD.encode("utf-8"),
                existing_hash.encode("utf-8"),
            )
        except ValueError:
            matches = False
        if matches:
            return existing_hash

    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(
            ADMIN_PASSWORD.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
    )


async def _ensure_company_and_admin():
    from context import tenant_context
    from database import AsyncSessionLocal
    from domains.identity.migration.models import IdentityLegacyDriverMap
    from domains.identity.models import BackofficeUser, CompanyOwner, CompanyPrincipal
    from domains.identity.types import PrincipalType
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

        owner_principal = await db.scalar(
            select(CompanyPrincipal).where(
                CompanyPrincipal.company_id == company.id,
                CompanyPrincipal.username == ADMIN_USERNAME,
            )
        )
        if owner_principal is None:
            owner_principal = CompanyPrincipal(
                company_id=company.id,
                username=ADMIN_USERNAME,
                password_hash=await _ensure_dev_password_hash(),
                full_name=ADMIN_FULL_NAME,
                principal_type=PrincipalType.BACKOFFICE.value,
                is_active=True,
                auth_revision=1,
            )
            db.add(owner_principal)
            await db.flush()
        else:
            owner_principal.username = ADMIN_USERNAME
            owner_principal.password_hash = await _ensure_dev_password_hash(
                owner_principal.password_hash
            )
            owner_principal.full_name = ADMIN_FULL_NAME
            owner_principal.principal_type = PrincipalType.BACKOFFICE.value
            owner_principal.is_active = True
            await db.flush()

        owner_backoffice_user = await db.scalar(
            select(BackofficeUser).where(
                BackofficeUser.company_id == company.id,
                BackofficeUser.principal_id == owner_principal.id,
            )
        )
        if owner_backoffice_user is None:
            owner_backoffice_user = BackofficeUser(
                company_id=company.id,
                principal_id=owner_principal.id,
                principal_type=PrincipalType.BACKOFFICE.value,
            )
            db.add(owner_backoffice_user)
            await db.flush()
        else:
            owner_backoffice_user.principal_type = PrincipalType.BACKOFFICE.value

        company_owner = await db.scalar(
            select(CompanyOwner).where(CompanyOwner.company_id == company.id)
        )
        if company_owner is None:
            company_owner = CompanyOwner(
                company_id=company.id,
                backoffice_user_id=owner_backoffice_user.id,
            )
            db.add(company_owner)
        else:
            company_owner.backoffice_user_id = owner_backoffice_user.id
        await db.flush()

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
                password_hash=owner_principal.password_hash,
                full_name=ADMIN_FULL_NAME,
                is_active=True,
                can_allow_debt=True,
            )
            db.add(admin)
            await db.flush()
        else:
            admin.full_name = ADMIN_FULL_NAME
            admin.is_active = True
            admin.can_allow_debt = True
            admin.password_hash = owner_principal.password_hash
            await db.flush()

        map_by_principal = await db.scalar(
            select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == company.id,
                IdentityLegacyDriverMap.backoffice_principal_id == owner_principal.id,
            )
        )
        map_by_user = await db.scalar(
            select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == company.id,
                IdentityLegacyDriverMap.backoffice_user_id == owner_backoffice_user.id,
            )
        )
        map_by_driver = await db.scalar(
            select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == company.id,
                IdentityLegacyDriverMap.legacy_driver_id == admin.id,
            )
        )
        existing_maps = [
            mapping
            for mapping in (map_by_principal, map_by_user, map_by_driver)
            if mapping is not None
        ]
        identity_map = existing_maps[0] if existing_maps else None
        if identity_map is not None and any(
            mapping is not identity_map for mapping in existing_maps[1:]
        ):
            raise RuntimeError("Conflicting development identity compatibility mappings.")

        if identity_map is None:
            identity_map = IdentityLegacyDriverMap(
                classification="BACKOFFICE_ONLY",
                company_id=company.id,
                legacy_driver_id=admin.id,
                backoffice_principal_id=owner_principal.id,
                backoffice_user_id=owner_backoffice_user.id,
                field_principal_id=None,
                field_representative_id=None,
            )
            db.add(identity_map)
        else:
            identity_map.classification = "BACKOFFICE_ONLY"
            identity_map.legacy_driver_id = admin.id
            identity_map.backoffice_principal_id = owner_principal.id
            identity_map.backoffice_user_id = owner_backoffice_user.id
            identity_map.field_principal_id = None
            identity_map.field_representative_id = None
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
