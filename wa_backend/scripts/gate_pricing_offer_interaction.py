from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        failures.append(label)


def static_and_domain_checks() -> None:
    from domains.offers.handlers import HANDLERS
    from domains.sales_calculation.core import CalculationError
    from domains.sales_calculation.service import _offers_allowed_by_price_rows
    from models import PriceBookAssignment

    model = (BACKEND / "models.py").read_text(encoding="utf-8")
    publishing = (BACKEND / "domains/pricing/publishing.py").read_text(encoding="utf-8")
    resolver = (BACKEND / "domains/pricing/resolver.py").read_text(encoding="utf-8")
    live = (BACKEND / "domains/sales_calculation/service.py").read_text(encoding="utf-8")
    api = (BACKEND / "api/pricing.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "dashboard/src/pages/PricingDashboard.tsx").read_text(encoding="utf-8")

    check(
        hasattr(PriceBookAssignment, "allow_offers")
        and 'allow_offers = Column(Boolean' in model,
        "Price assignment owns the offer-interaction policy",
    )
    check(
        "allow_offers: bool" in publishing
        and "allow_offers=bool(allow_offers)" in publishing,
        "Assignment creation persists the policy explicitly",
    )
    check(
        "allow_offers: bool" in resolver
        and "allow_offers=bool(assignment.allow_offers)" in resolver,
        "Resolved base-price authority carries the policy",
    )
    check(
        "offers_allowed = _offers_allowed_by_price_rows(price_rows)" in live
        and "if offers_allowed:" in live
        and "offer_candidates = []" in live,
        "Live calculation blocks offer resolution when the selected price forbids offers",
    )
    check(
        'allow_offers: bool = True' in api
        and '"allow_offers": bool(row.allow_offers)' in api
        and "allow_offers=payload.allow_offers" in api,
        "Pricing API round-trips the policy with backward-compatible default TRUE",
    )
    check(
        "العروض فوق هذا السعر" in dashboard
        and "نعم، تسمح بالعروض" in dashboard
        and "لا، السعر نهائي" in dashboard
        and "allow_offers: assignmentForm.allow_offers" in dashboard,
        "Advanced-pricing UI explains and submits the policy",
    )
    check(
        set(HANDLERS) == {
            "PERCENTAGE_DISCOUNT",
            "FIXED_DISCOUNT",
            "BUY_X_GET_Y",
            "FREE_GOODS",
            "QUANTITY_TIERS",
            "BUNDLE",
        },
        "Offer engine remains discount/reward authority, not base-price replacement authority",
    )

    allow = {1: SimpleNamespace(assignment_id=1, assignment_revision=1, allow_offers=True)}
    block = {1: SimpleNamespace(assignment_id=2, assignment_revision=2, allow_offers=False)}
    mixed = {
        1: SimpleNamespace(assignment_id=1, assignment_revision=1, allow_offers=True),
        2: SimpleNamespace(assignment_id=2, assignment_revision=2, allow_offers=False),
    }
    check(
        _offers_allowed_by_price_rows(allow) is True
        and _offers_allowed_by_price_rows(block) is False,
        "Pure price-policy helper honors ALLOW and BLOCK deterministically",
    )
    try:
        _offers_allowed_by_price_rows(mixed)
        conflict_code = None
    except CalculationError as exc:
        conflict_code = exc.code
    check(
        conflict_code == "CALCULATION_PRICE_OFFER_POLICY_CONFLICT",
        "Mixed price authorities fail closed before offers are evaluated",
    )


async def database_checks() -> None:
    from database import engine

    heads_cp = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    cli_heads = {
        line.split()[0]
        for line in heads_cp.stdout.splitlines()
        if "(head)" in line and line.split()
    }
    check(
        heads_cp.returncode == 0 and len(cli_heads) == 1,
        "Alembic exposes exactly one current head",
    )
    history_cp = subprocess.run(
        [sys.executable, "-m", "alembic", "history", "--verbose"],
        cwd=BACKEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    check(
        history_cp.returncode == 0
        and "e3b7a9c1d4f6" in history_cp.stdout,
        "Pricing-offer policy migration remains in the current Alembic lineage",
    )

    async with engine.connect() as conn:
        db_heads = set(
            (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalars().all()
        )
        check(
            bool(cli_heads) and db_heads == cli_heads,
            "Database is upgraded to the exact current Alembic head",
        )

        column = (
            await conn.execute(
                text(
                    """
                    SELECT data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'price_book_assignments'
                      AND column_name = 'allow_offers'
                    """
                )
            )
        ).one_or_none()
        check(
            column is not None
            and str(column.data_type) == "boolean"
            and str(column.is_nullable) == "NO"
            and "true" in str(column.column_default).lower(),
            "DB policy column is BOOLEAN NOT NULL DEFAULT TRUE",
        )

        null_count = await conn.scalar(
            text(
                "SELECT count(*) FROM price_book_assignments "
                "WHERE allow_offers IS NULL"
            )
        )
        check(
            int(null_count or 0) == 0,
            "All existing pricing assignments received backward-compatible ALLOW behavior",
        )

        rls = (
            await conn.execute(
                text(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = 'price_book_assignments'
                    """
                )
            )
        ).one_or_none()
        check(
            rls is not None and bool(rls.relrowsecurity) and bool(rls.relforcerowsecurity),
            "Price assignment table keeps ENABLE + FORCE RLS",
        )

        policy = (
            await conn.execute(
                text(
                    """
                    SELECT qual, with_check
                    FROM pg_policies
                    WHERE schemaname = current_schema()
                      AND tablename = 'price_book_assignments'
                    """
                )
            )
        ).all()
        check(
            any(
                "app.current_tenant" in str(row.qual or "")
                and "company_id" in str(row.qual or "")
                and "app.current_tenant" in str(row.with_check or "")
                and "company_id" in str(row.with_check or "")
                for row in policy
            ),
            "Pricing assignment RLS still enforces tenant USING + WITH CHECK",
        )

    await engine.dispose()


def main() -> int:
    try:
        static_and_domain_checks()
        asyncio.run(database_checks())
    except Exception as exc:
        check(False, "Gate completed without unexpected exception")
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("PRICING_OFFER_INTERACTION_GATE=FAIL")
        return 1

    print("PRICING_OFFER_INTERACTION_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
