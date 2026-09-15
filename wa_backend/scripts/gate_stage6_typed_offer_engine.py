from __future__ import annotations

import asyncio
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError
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


def rejected(callable_) -> bool:
    try:
        callable_()
        return False
    except (ValidationError, ValueError):
        return True


def static_and_domain_checks() -> None:
    from domains.offers.contracts import (
        BasketLine,
        BasketPriceComponent,
        CatalogPrice,
        MONEY_MAX,
        OfferCandidate,
        OfferProductRef,
        Reward,
        money,
    )
    from domains.offers.core import OfferError
    from domains.offers.engine import calculate_offers
    from domains.offers.handlers.common import proposal
    from domains.offers.schemas import (
        BundlePayload,
        FixedDiscountPayload,
        OfferCaps,
    )
    from domains.uom_authority import (
        UomAuthorityError,
        _build_authority,
    )

    resolver = (BACKEND / "domains/pricing/resolver.py").read_text(encoding="utf-8")
    preview = (BACKEND / "domains/offers/service.py").read_text(encoding="utf-8")
    live = (BACKEND / "domains/sales_calculation/service.py").read_text(encoding="utf-8")
    schemas = (BACKEND / "domains/offers/schemas.py").read_text(encoding="utf-8")
    contracts = (BACKEND / "domains/offers/contracts.py").read_text(encoding="utf-8")

    check(
        "allow_unresolved_pairs: bool = False" in resolver
        and "if missing and not allow_unresolved_pairs:" in resolver,
        "Pricing resolver stays strict by default",
    )
    check(
        preview.count("allow_unresolved_pairs=True") == 1
        and live.count("allow_unresolved_pairs=True") == 1,
        "Only speculative reward bulk lookups opt into partial resolution",
    )
    check(
        "all_variant_ids = basket_ids |" not in preview
        and "all_variant_ids = set(product_ids) |" not in live,
        "Candidate reward UOMs are not prevalidated before basket eligibility",
    )
    check(
        "applied_reward_variant_ids" in preview
        and "applied_reward_variant_ids" in live,
        "Reward UOM authority is loaded only for applied rewards",
    )
    check(
        "def _money(value: Any, field_name: str)" in schemas
        and "normalize_discount_cap" in schemas
        and "normalize_amount" in schemas,
        "Offer immutable payload money uses exact NUMERIC(20,6) validation",
    )
    check(
        'MONEY_MAX = Decimal("99999999999999.999999")' in contracts,
        "Offer monetary primitive declares NUMERIC(20,6) capacity",
    )

    check(
        rejected(
            lambda: FixedDiscountPayload.model_validate(
                {"amount": "1.0000001"}
            )
        ),
        "Fixed discount rejects >6 meaningful decimals",
    )
    check(
        rejected(
            lambda: FixedDiscountPayload.model_validate(
                {"amount": "100000000000000"}
            )
        ),
        "Fixed discount rejects NUMERIC(20,6) overflow",
    )
    check(
        rejected(
            lambda: OfferCaps.model_validate(
                {"max_discount_amount": "1.0000001"}
            )
        )
        and rejected(
            lambda: OfferCaps.model_validate(
                {"max_reward_quantity": "1.0000001"}
            )
        ),
        "Offer caps reject money/quantity precision overflow",
    )
    check(
        rejected(
            lambda: BundlePayload.model_validate(
                {
                    "reward_type": "FIXED_PRICE",
                    "reward_value": "1.0000001",
                }
            )
        ),
        "Fixed-price bundle rejects >6-decimal money",
    )
    check(
        money(MONEY_MAX) == MONEY_MAX
        and rejected(
            lambda: money(
                MONEY_MAX + Decimal("1")
            )
        ),
        "money() enforces NUMERIC(20,6) capacity",
    )

    sold_component = BasketPriceComponent(
        uom_id=1,
        quantity=Decimal("1"),
        base_quantity=Decimal("1"),
        unit_price=Decimal("10"),
        price_entry_id=1,
        price_publication_revision=1,
        assignment_revision=1,
    )
    unrelated_line = BasketLine(
        line_id=1,
        product_variant_id=999,
        base_uom_id=1,
        quantity=Decimal("1"),
        price_components=(sold_component,),
    )
    eligible_line = BasketLine(
        line_id=1,
        product_variant_id=101,
        base_uom_id=1,
        quantity=Decimal("2"),
        price_components=(
            BasketPriceComponent(
                uom_id=1,
                quantity=Decimal("2"),
                base_quantity=Decimal("2"),
                unit_price=Decimal("10"),
                price_entry_id=2,
                price_publication_revision=1,
                assignment_revision=1,
            ),
        ),
    )
    reward_offer = OfferCandidate(
        version_id=7,
        definition_id=7,
        revision=7,
        offer_type="BUY_X_GET_Y",
        priority=10,
        stacking_mode="EXCLUSIVE",
        payload={"buy_quantity": "2"},
        product_targets=(),
        products=(
            OfferProductRef(
                role="QUALIFYING",
                product_variant_id=101,
                uom_id=1,
                quantity_per_application=None,
            ),
            OfferProductRef(
                role="REWARD",
                product_variant_id=202,
                uom_id=1,
                quantity_per_application=Decimal("1"),
            ),
        ),
    )
    unrelated_result = calculate_offers(
        lines=[unrelated_line],
        candidates=[reward_offer],
        catalog_prices={},
    )
    check(
        not unrelated_result.applied_offers,
        "Unrelated basket does not require an inapplicable reward price",
    )

    try:
        calculate_offers(
            lines=[eligible_line],
            candidates=[reward_offer],
            catalog_prices={},
        )
        eligible_missing_code = None
    except OfferError as exc:
        eligible_missing_code = exc.code
    check(
        eligible_missing_code == "OFFER_REWARD_PRICE_REQUIRED",
        "Eligible reward without price fails closed with stable domain code",
    )

    priced_reward = CatalogPrice(
        product_variant_id=202,
        uom_id=1,
        unit_price=Decimal("1"),
        price_entry_id=20,
        price_publication_revision=1,
        assignment_revision=1,
    )
    try:
        proposal(
            reward_offer,
            rewards=(
                Reward(
                    product_variant_id=202,
                    uom_id=1,
                    quantity=Decimal("100000000000000"),
                ),
            ),
            catalog_prices={(202, 1): priced_reward},
        )
        reward_overflow_code = None
    except OfferError as exc:
        reward_overflow_code = exc.code
    check(
        reward_overflow_code == "OFFER_REWARD_QUANTITY_INVALID",
        "Generated reward quantity overflow fails with stable OfferError",
    )

    variant = SimpleNamespace(
        id=101,
        base_uom_id=1,
        quantity_scale=6,
        quantity_step=Decimal("0.000001"),
    )
    authority = _build_authority(variant, [])
    try:
        authority.to_base(
            Decimal("100000000000000"),
            uom_id=1,
            field_name="reward_quantity",
        )
        uom_overflow_code = None
    except UomAuthorityError as exc:
        uom_overflow_code = exc.code
    check(
        uom_overflow_code == "UOM_QUANTITY_INVALID",
        "UOM authority never leaks raw QuantityError",
    )

    huge_line = BasketLine(
        line_id=1,
        product_variant_id=500,
        base_uom_id=1,
        quantity=Decimal("1"),
        price_components=(
            BasketPriceComponent(
                uom_id=1,
                quantity=Decimal("1"),
                base_quantity=Decimal("1"),
                unit_price=Decimal("100000000000000"),
                price_entry_id=50,
                price_publication_revision=1,
                assignment_revision=1,
            ),
        ),
    )
    try:
        calculate_offers(
            lines=[huge_line],
            candidates=[],
            catalog_prices={},
        )
        money_overflow_code = None
    except OfferError as exc:
        money_overflow_code = exc.code
    check(
        money_overflow_code == "OFFER_MONETARY_OVERFLOW",
        "Engine gross overflow fails as OfferError, not raw Decimal error",
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

    tables = (
        "offer_definitions",
        "offer_versions",
        "offer_version_scopes",
        "offer_version_products",
    )
    async with engine.connect() as conn:
        db_heads = set(
            (
                await conn.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalars().all()
        )
        check(
            bool(cli_heads) and db_heads == cli_heads,
            "Database is upgraded to the exact current Alembic head",
        )

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        rls = {
            str(row.relname): (
                bool(row.relrowsecurity),
                bool(row.relforcerowsecurity),
            )
            for row in rows
        }
        check(
            all(rls.get(table) == (True, True) for table in tables),
            "All offer tables keep ENABLE + FORCE RLS",
        )

        policies = (
            await conn.execute(
                text(
                    """
                    SELECT tablename, policyname, qual, with_check
                    FROM pg_policies
                    WHERE schemaname = current_schema()
                      AND tablename = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        policy_map = {
            str(row.tablename): (
                str(row.policyname),
                str(row.qual or ""),
                str(row.with_check or ""),
            )
            for row in policies
            if str(row.policyname).endswith("_company_isolation")
        }
        check(
            all(
                table in policy_map
                and "app.current_tenant" in policy_map[table][1]
                and "company_id" in policy_map[table][1]
                and "app.current_tenant" in policy_map[table][2]
                and "company_id" in policy_map[table][2]
                for table in tables
            ),
            "Offer RLS policies enforce tenant USING + WITH CHECK",
        )

        constraints = (
            await conn.execute(
                text(
                    """
                    SELECT cls.relname AS table_name,
                           c.conname,
                           c.contype::text AS constraint_type,
                           pg_get_constraintdef(c.oid, true) AS definition
                    FROM pg_constraint c
                    JOIN pg_class cls ON cls.oid = c.conrelid
                    WHERE cls.relname = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        defs = {
            (str(row.table_name), str(row.conname)): (
                str(row.constraint_type),
                str(row.definition),
            )
            for row in constraints
        }
        check(
            any(
                table == "offer_version_scopes"
                and constraint_type == "f"
                and "FOREIGN KEY (company_id, offer_version_id)" in definition
                for (table, _), (constraint_type, definition) in defs.items()
            )
            and any(
                table == "offer_version_products"
                and constraint_type == "f"
                and "FOREIGN KEY (company_id, offer_version_id)" in definition
                for (table, _), (constraint_type, definition) in defs.items()
            ),
            "Offer child rows are tenant-bound to parent versions by composite FK",
        )
        product_quantity_constraints = [
            (name, definition)
            for (table, name), (constraint_type, definition) in defs.items()
            if table == "offer_version_products"
            and constraint_type == "c"
            and "quantity_per_application" in definition
        ]
        typed_quantity_shape = any(
            "role" in definition
            and "QUALIFYING" in definition
            and "REWARD" in definition
            and "BUNDLE_COMPONENT" in definition
            and "quantity_per_application IS NULL" in definition
            and "quantity_per_application IS NOT NULL" in definition
            and "quantity_per_application >" in definition
            for _name, definition in product_quantity_constraints
        )
        check(
            typed_quantity_shape,
            "DB enforces typed qualifying/reward quantity shape",
        )
        if not typed_quantity_shape:
            print("OBSERVED_OFFER_PRODUCT_CHECK_CONSTRAINTS:")
            for name, definition in sorted(product_quantity_constraints):
                print(f"  {name}: {definition}")

        triggers = (
            await conn.execute(
                text(
                    """
                    SELECT event_object_table, trigger_name
                    FROM information_schema.triggers
                    WHERE event_object_table = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        trigger_set = {
            (str(row.event_object_table), str(row.trigger_name))
            for row in triggers
        }
        check(
            ("offer_versions", "trg_offer_version_immutable") in trigger_set
            and ("offer_version_scopes", "trg_offer_scope_immutable") in trigger_set
            and ("offer_version_products", "trg_offer_product_immutable") in trigger_set,
            "Published offer history and child configuration remain DB-immutable",
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
        print("STAGE6_TYPED_OFFER_ENGINE_GATE=FAIL")
        return 1

    print("STAGE6_TYPED_OFFER_ENGINE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
