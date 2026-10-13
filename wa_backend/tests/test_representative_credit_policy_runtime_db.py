"""Real PostgreSQL matrix for canonical representative credit authority."""
from __future__ import annotations

import os
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import main as _main  # noqa: F401 - registers the complete runtime metadata
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import Base, Company, Driver, Shop
from services import check_debt_limits

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_REPRESENTATIVE_CREDIT_DB_GATE") != "1",
    reason="Explicit isolated representative credit PostgreSQL gate only",
)

REP_NOT_AUTHORIZED = "المندوب غير مخول بالبيع بالذمم."
REP_ZERO_LIMIT = "حد الذمم لكل عملية بيع لدى المندوب لا يسمح بإنشاء ذمم جديدة."
REP_LIMIT_EXCEEDED = "مبلغ الذمم الجديد يتجاوز حد الذمم المسموح للمندوب في عملية بيع واحدة."
SHOP_ZERO_LIMIT = "هذا المحل غير مسموح له بالبيع بالذمم لأن سقف ذمته يساوي صفراً."
SHOP_LIMIT_EXCEEDED = "إجمالي ذمة المحل بعد العملية سيتجاوز سقف الذمة المسموح له."


@pytest_asyncio.fixture(scope="module")
async def credit_engine():
    admin_url = os.environ["DATABASE_URL_MIGRATION"]
    assert make_url(admin_url).database == "representatives_credit_gate"
    schema = "representative_credit_" + uuid4().hex

    root_engine = create_async_engine(admin_url, poolclass=NullPool)
    async with root_engine.begin() as conn:
        for extension in ("btree_gist", "btree_gin", "pg_trgm"):
            await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        admin_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()
        async with root_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await root_engine.dispose()


@pytest_asyncio.fixture
async def policy_case(credit_engine):
    suffix = uuid4().hex[:10]
    async with AsyncSession(credit_engine, expire_on_commit=False) as db:
        company = Company(name=f"Credit Company {suffix}", company_code=f"CC-{suffix}")
        other_company = Company(
            name=f"Other Credit Company {suffix}",
            company_code=f"OC-{suffix}",
        )
        db.add_all([company, other_company])
        await db.flush()

        # Deliberately keep legacy Driver credit flags permissive. Tests then
        # prove canonical Representative state wins when it is disabled/lowered.
        driver = Driver(
            company_id=company.id,
            username=f"legacy-{suffix}",
            password_hash="legacy-password-hash",
            full_name="Legacy Operational Locator",
            is_active=True,
            can_allow_debt=True,
            max_debt_limit=Decimal("999999.000"),
        )
        principal = CompanyPrincipal(
            company_id=company.id,
            username=f"field-{suffix}",
            password_hash="canonical-password-hash",
            full_name="Canonical Field Representative",
            principal_type="FIELD_REPRESENTATIVE",
            is_active=True,
            auth_revision=1,
        )
        db.add_all([driver, principal])
        await db.flush()

        representative = FieldRepresentative(
            company_id=company.id,
            principal_id=principal.id,
            principal_type="FIELD_REPRESENTATIVE",
            can_allow_debt=True,
            max_debt_limit=Decimal("100.000"),
        )
        db.add(representative)
        await db.flush()
        db.add(
            IdentityLegacyDriverMap(
                company_id=company.id,
                legacy_driver_id=driver.id,
                classification="FIELD_ONLY",
                backoffice_principal_id=None,
                backoffice_user_id=None,
                field_principal_id=principal.id,
                field_representative_id=representative.id,
            )
        )

        shop = Shop(
            company_id=company.id,
            name=f"Credit Shop {suffix}",
            current_balance=Decimal("700.000"),
            max_debt_limit=Decimal("1000.000"),
            is_active=True,
            is_archived=False,
        )
        other_shop = Shop(
            company_id=other_company.id,
            name=f"Other Credit Shop {suffix}",
            current_balance=Decimal("0.000"),
            max_debt_limit=Decimal("1000.000"),
            is_active=True,
            is_archived=False,
        )
        db.add_all([shop, other_shop])
        await db.commit()

        return SimpleNamespace(
            company_id=company.id,
            other_company_id=other_company.id,
            driver_id=driver.id,
            principal_id=principal.id,
            representative_id=representative.id,
            shop_id=shop.id,
            other_shop_id=other_shop.id,
        )


async def run_policy(engine, case, debt: str, *, company_id=None, driver_id=None, shop_id=None):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        result = await check_debt_limits(
            db,
            company_id if company_id is not None else case.company_id,
            driver_id if driver_id is not None else case.driver_id,
            shop_id if shop_id is not None else case.shop_id,
            Decimal(debt),
        )
        await db.rollback()
        return result


async def set_rep_policy(engine, case, *, allowed=None, limit=None):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        representative = await db.get(FieldRepresentative, case.representative_id)
        assert representative is not None
        if allowed is not None:
            representative.can_allow_debt = allowed
        if limit is not None:
            representative.max_debt_limit = Decimal(limit)
        await db.commit()


async def set_shop_policy(engine, case, *, balance=None, limit=None):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        shop = await db.get(Shop, case.shop_id)
        assert shop is not None
        if balance is not None:
            shop.current_balance = Decimal(balance)
        if limit is not None:
            shop.max_debt_limit = Decimal(limit)
        await db.commit()


@pytest.mark.asyncio
async def test_representative_off_denies_even_when_shop_and_legacy_driver_allow(credit_engine, policy_case):
    await set_rep_policy(credit_engine, policy_case, allowed=False, limit="100.000")
    allowed, message = await run_policy(credit_engine, policy_case, "60.000")
    assert allowed is False
    assert message == REP_NOT_AUTHORIZED


@pytest.mark.asyncio
async def test_representative_per_sale_limit_exceeded_denies(credit_engine, policy_case):
    await set_rep_policy(credit_engine, policy_case, allowed=True, limit="50.000")
    allowed, message = await run_policy(credit_engine, policy_case, "60.000")
    assert allowed is False
    assert message == REP_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_shop_total_limit_exceeded_denies_independently(credit_engine, policy_case):
    await set_rep_policy(credit_engine, policy_case, allowed=True, limit="100.000")
    await set_shop_policy(credit_engine, policy_case, balance="960.000", limit="1000.000")
    allowed, message = await run_policy(credit_engine, policy_case, "60.000")
    assert allowed is False
    assert message == SHOP_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_both_representative_and_shop_limits_pass(credit_engine, policy_case):
    allowed, message = await run_policy(credit_engine, policy_case, "60.000")
    assert allowed is True
    assert message == ""


@pytest.mark.asyncio
async def test_shop_zero_limit_denies_new_credit(credit_engine, policy_case):
    await set_shop_policy(credit_engine, policy_case, limit="0.000")
    allowed, message = await run_policy(credit_engine, policy_case, "1.000")
    assert allowed is False
    assert message == SHOP_ZERO_LIMIT


@pytest.mark.asyncio
async def test_representative_zero_limit_denies_new_credit(credit_engine, policy_case):
    await set_rep_policy(credit_engine, policy_case, allowed=True, limit="0.000")
    allowed, message = await run_policy(credit_engine, policy_case, "1.000")
    assert allowed is False
    assert message == REP_ZERO_LIMIT


@pytest.mark.asyncio
async def test_cash_sale_is_not_blocked_by_credit_policy(credit_engine, policy_case):
    await set_rep_policy(credit_engine, policy_case, allowed=False, limit="0.000")
    await set_shop_policy(credit_engine, policy_case, limit="0.000")
    allowed, message = await run_policy(credit_engine, policy_case, "0.000")
    assert allowed is True
    assert message == ""


@pytest.mark.asyncio
async def test_cross_company_driver_mapping_and_shop_fail_closed(credit_engine, policy_case):
    allowed, message = await run_policy(
        credit_engine,
        policy_case,
        "1.000",
        company_id=policy_case.other_company_id,
        driver_id=policy_case.driver_id,
        shop_id=policy_case.other_shop_id,
    )
    assert allowed is False
    assert message == REP_NOT_AUTHORIZED


@pytest.mark.asyncio
async def test_immediate_disable_denies_very_next_credit_attempt(credit_engine, policy_case):
    first = await run_policy(credit_engine, policy_case, "60.000")
    assert first == (True, "")

    await set_rep_policy(credit_engine, policy_case, allowed=False)
    second = await run_policy(credit_engine, policy_case, "60.000")
    assert second == (False, REP_NOT_AUTHORIZED)


@pytest.mark.asyncio
async def test_immediate_limit_reduction_denies_next_above_limit_attempt(credit_engine, policy_case):
    first = await run_policy(credit_engine, policy_case, "60.000")
    assert first == (True, "")

    await set_rep_policy(credit_engine, policy_case, allowed=True, limit="50.000")
    second = await run_policy(credit_engine, policy_case, "60.000")
    assert second == (False, REP_LIMIT_EXCEEDED)


@pytest.mark.asyncio
async def test_locked_persisted_shop_balance_is_re_read_for_next_decision(credit_engine, policy_case):
    first = await run_policy(credit_engine, policy_case, "40.000")
    assert first == (True, "")

    await set_shop_policy(credit_engine, policy_case, balance="980.000")
    second = await run_policy(credit_engine, policy_case, "40.000")
    assert second == (False, SHOP_LIMIT_EXCEEDED)


@pytest.mark.asyncio
async def test_inactive_canonical_principal_denies_even_with_active_legacy_driver(credit_engine, policy_case):
    async with AsyncSession(credit_engine, expire_on_commit=False) as db:
        principal = await db.get(CompanyPrincipal, policy_case.principal_id)
        assert principal is not None
        principal.is_active = False
        await db.commit()

    allowed, message = await run_policy(credit_engine, policy_case, "1.000")
    assert allowed is False
    assert message == REP_NOT_AUTHORIZED


@pytest.mark.asyncio
async def test_legacy_driver_credit_flags_are_not_financial_authority(credit_engine, policy_case):
    async with AsyncSession(credit_engine, expire_on_commit=False) as db:
        driver = await db.get(Driver, policy_case.driver_id)
        assert driver is not None
        driver.can_allow_debt = False
        driver.max_debt_limit = Decimal("0.000")
        await db.commit()

    allowed, message = await run_policy(credit_engine, policy_case, "60.000")
    assert allowed is True
    assert message == ""
