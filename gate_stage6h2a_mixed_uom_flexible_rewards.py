from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
EXPECTED_HEAD = "fa129278c7173fe39b4a991b7ee22950c05f07d5"
EXPECTED_CHANGED = {'wa_backend/domains/offers/handlers/bundle.py', 'wa_backend/domains/sales_calculation/service.py', 'wa_backend/domains/offers/handlers/quantity.py', 'wa_backend/domains/sales_evidence/service.py', 'wa_backend/domains/sales_evidence/core.py', 'wa_backend/domains/offers/models.py', 'wa_backend/alembic/versions/c3f8a1d6e2b4_stage6h2a_mixed_uom_flexible_rewards.py', 'wa_backend/domains/offers/handlers/cross_product.py', 'wa_backend/domains/offers/handlers/common.py', 'wa_backend/domains/uom_authority.py', 'wa_backend/api/offers.py', 'wa_backend/domains/offers/publishing.py', 'wa_backend/domains/offers/service.py', 'wa_backend/domains/offers/contracts.py', 'wa_backend/domains/offers/schemas.py', 'wa_backend/domains/offers/eligibility.py', 'wa_backend/domains/offers/engine.py', 'wa_backend/domains/offers/handlers/simple.py', 'wa_backend/domains/offers/validation.py'}
MIGRATION = (
    "wa_backend/alembic/versions/"
    "c3f8a1d6e2b4_stage6h2a_mixed_uom_flexible_rewards.py"
)

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)
        print(f"[FAIL] {label}")
    else:
        print(f"[PASS] {label}")


def run(
    *args: str,
    cwd: Path = ROOT,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if cp.returncode != 0 and not allow_failure:
        raise RuntimeError(
            cp.stderr.strip()
            or cp.stdout.strip()
            or f"command failed: {args}"
        )
    return cp


def git_output(*args: str) -> str:
    return run("git", *args).stdout.strip()


def changed_surface() -> set[str]:
    tracked = {
        line.strip()
        for line in git_output(
            "diff",
            "--name-only",
            "HEAD",
            "--",
        ).splitlines()
        if line.strip()
    }
    untracked = {
        line.strip()
        for line in git_output(
            "ls-files",
            "--others",
            "--exclude-standard",
        ).splitlines()
        if line.strip()
        and not line.startswith("stage6h2a_")
        and not line.startswith("gate_stage6h2a_")
    }
    return tracked | untracked


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def static_checks() -> None:
    head = git_output("rev-parse", "HEAD")
    origin = git_output("rev-parse", "origin/main")
    check(
        head == EXPECTED_HEAD,
        "HEAD remains exact Stage 6H.1 baseline",
    )
    check(
        origin == EXPECTED_HEAD,
        "origin/main remains exact Stage 6H.1 baseline",
    )

    surface = changed_surface()
    check(
        surface == EXPECTED_CHANGED,
        "Changed surface is exactly Stage 6H.2A",
    )
    if surface != EXPECTED_CHANGED:
        print(
            "  missing:",
            sorted(EXPECTED_CHANGED - surface),
        )
        print(
            "  unexpected:",
            sorted(surface - EXPECTED_CHANGED),
        )

    staged = git_output(
        "diff",
        "--cached",
        "--name-only",
    )
    check(
        not staged,
        "No Stage 6H.2A changes are staged before acceptance",
    )

    diff_check = run(
        "git",
        "diff",
        "--check",
        allow_failure=True,
    )
    check(
        diff_check.returncode == 0,
        "git diff --check",
    )
    if diff_check.returncode:
        print(diff_check.stdout)
        print(diff_check.stderr)

    name_status = git_output(
        "diff",
        "--name-status",
        "HEAD",
    )
    check(
        not any(
            line.startswith("D\t")
            for line in name_status.splitlines()
        ),
        "Stage 6H.2A deletes no tracked file",
    )

    for rel in sorted(EXPECTED_CHANGED):
        path = ROOT / rel
        check(
            path.is_file(),
            f"Expected file exists: {rel}",
        )
        if path.is_file() and rel.endswith(".py"):
            try:
                compile(
                    path.read_text(encoding="utf-8"),
                    rel,
                    "exec",
                )
                ok = True
            except Exception as exc:
                ok = False
                print(
                    f"  compile error {rel}: {exc!r}"
                )
            check(
                ok,
                f"Python compile: {rel}",
            )

    models = read(
        "wa_backend/domains/offers/models.py"
    )
    schemas = read(
        "wa_backend/domains/offers/schemas.py"
    )
    validation = read(
        "wa_backend/domains/offers/validation.py"
    )
    publishing = read(
        "wa_backend/domains/offers/publishing.py"
    )
    eligibility = read(
        "wa_backend/domains/offers/eligibility.py"
    )
    contracts = read(
        "wa_backend/domains/offers/contracts.py"
    )
    common = read(
        "wa_backend/domains/offers/handlers/common.py"
    )
    cross = read(
        "wa_backend/domains/offers/handlers/cross_product.py"
    )
    quantity = read(
        "wa_backend/domains/offers/handlers/quantity.py"
    )
    bundle = read(
        "wa_backend/domains/offers/handlers/bundle.py"
    )
    engine = read(
        "wa_backend/domains/offers/engine.py"
    )
    preview = read(
        "wa_backend/domains/offers/service.py"
    )
    sale_calc = read(
        "wa_backend/domains/sales_calculation/service.py"
    )
    evidence_core = read(
        "wa_backend/domains/sales_evidence/core.py"
    )
    evidence = read(
        "wa_backend/domains/sales_evidence/service.py"
    )
    uom = read(
        "wa_backend/domains/uom_authority.py"
    )
    migration = read(MIGRATION)

    check(
        "uom_id = Column(Integer, nullable=True)"
        in models
        and "fk_offer_scope_uom" in models
        and "uq_offer_scope_product_all_uom"
        in models
        and "uq_offer_scope_product_specific_uom"
        in models,
        "Product scopes support explicit UOM or all-UOM targeting",
    )
    check(
        "uom_id = Column(Integer, nullable=False)"
        in models
        and "quantity_per_application = Column(Numeric(20, 6), nullable=True)"
        in models
        and "offer_product_quantity_shape"
        in models,
        "Offer products carry typed UOM and quantity semantics",
    )
    check(
        "uom_id: int = Field(gt=0)" in schemas
        and "quantity_per_application: Optional[Decimal]"
        in schemas
        and "class PreviewComponent" in schemas
        and "components: list[PreviewComponent]"
        in schemas,
        "API contracts expose typed UOM/product components",
    )
    check(
        "get_quantity" not in schemas
        and "free_quantity" not in schemas
        and "bundle_quantity" not in schemas,
        "Legacy single-reward payload quantities are removed",
    )
    check(
        "OFFER_REWARD_QUANTITY_REQUIRED"
        in validation
        and "OFFER_QUALIFYING_UOM_CONFLICT"
        in validation
        and "OFFER_BUNDLE_COMPONENTS_REQUIRED"
        in validation,
        "Offer validation enforces flexible reward and bundle invariants",
    )
    check(
        "len(rewards) != 1" not in validation
        and "rewards[0]" not in cross,
        "No single-reward assumption remains",
    )
    check(
        "load_variant_uom_authorities"
        in publishing
        and "_validate_offer_quantity_semantics"
        in publishing
        and "validate_step=True" in publishing,
        "Publishing validates exact UOM reachability and quantity step",
    )
    check(
        "ComponentKey = tuple[int, int]"
        in contracts
        and "class BasketPriceComponent"
        in contracts
        and "price_components:"
        in contracts
        and "uom_id: int"
        in contracts,
        "Offer engine contract is component-level by line/UOM",
    )
    check(
        "current: dict[ComponentKey, Decimal]"
        in engine
        and "adjustment.uom_id"
        in engine
        and "current_key" in engine,
        "Discount stacking/clamping works per UOM component",
    )
    check(
        "target_components" in common
        and "component.uom_id"
        in common,
        "Simple discounts target exact UOM components",
    )
    check(
        "qualifying_uom" in cross
        and "quantity_for_uom" in cross
        and "for row in sorted(" in cross,
        "BOGO/free-goods supports multi-product multi-reward rows",
    )
    check(
        "target_uom = int(target.uom_id)"
        in quantity
        and "line.component(" in quantity,
        "Quantity tiers operate on an explicit UOM",
    )
    check(
        "term.quantity_per_application"
        in bundle
        and "line.component(" in bundle
        and "applications_by_component"
        in bundle,
        "Bundle terms carry independent product/UOM/quantity",
    )
    check(
        "Fraction" in uom
        and "UOM_CONVERSION_GRAPH_AMBIGUOUS"
        in uom
        and "UOM_CONVERSION_PRECISION_LOSS"
        in uom
        and "float(" not in uom,
        "UOM authority is exact-rational and fail-closed",
    )
    check(
        "component_base_quantities"
        in preview
        and "requested_pairs"
        in preview
        and "price_components"
        in preview,
        "Offer preview resolves each sold Variant/UOM price independently",
    )
    check(
        "reward_pairs" in sale_calc
        and "missing_pairs = reward_pairs - set(price_rows)"
        in sale_calc
        and "CatalogPrice(" in sale_calc
        and "uom_id=int(pair[1])"
        in sale_calc,
        "Live Stage 6H.1 path resolves reward prices by exact Variant/UOM",
    )
    check(
        "EVIDENCE_SCHEMA_VERSION = 2"
        in evidence_core
        and '"uom_id": row.uom_id'
        in evidence
        and '"target_uom_id": int(adjustment.uom_id)'
        in evidence,
        "Offer evidence records explicit UOM semantics",
    )

    runtime = "\n".join(
        (
            schemas,
            validation,
            publishing,
            eligibility,
            contracts,
            engine,
            preview,
        )
    )
    forbidden = (
        "configuration_schema_version",
        "LegacyBuyXGetYPayload",
        "LegacyFreeGoodsPayload",
        "LegacyBundlePayload",
    )
    check(
        not any(
            token in runtime
            for token in forbidden
        ),
        "No V1/V2 compatibility runtime or parallel offer schema exists",
    )

    check(
        'down_revision: Union[str, Sequence[str], None] = "91e6b4c8d2f0"'
        in migration
        and 'revision: str = "c3f8a1d6e2b4"'
        in migration,
        "Alembic Stage 6H.2A chains from exact Stage 6H.1 head",
    )
    check(
        "_disable_rls_for_admin_migration()"
        in migration
        and "_assert_offer_tables_empty()"
        in migration
        and "_restore_rls()" in migration
        and "DISABLE ROW LEVEL SECURITY"
        in migration
        and "FORCE ROW LEVEL SECURITY"
        in migration,
        "Migration cannot mistake RLS-hidden rows for an empty offer database",
    )
    check(
        "server_default" not in migration
        and 'sa.Column("uom_id", sa.Integer(), nullable=False)'
        in migration,
        "Migration adds no silent/default UOM fallback",
    )
    check(
        "uq_offer_version_product_role_variant_uom"
        in migration
        and "uq_offer_scope_product_specific_uom"
        in migration
        and "ck_offer_version_products_offer_product_quantity_shape"
        in migration,
        "Migration DB constraints match ORM UOM/reward invariants",
    )

    alembic = run(
        sys.executable,
        "-m",
        "alembic",
        "heads",
        cwd=ROOT / "wa_backend",
        allow_failure=True,
    )
    check(
        alembic.returncode == 0
        and "c3f8a1d6e2b4 (head)"
        in alembic.stdout,
        "Alembic has one Stage 6H.2A head",
    )
    if alembic.returncode != 0:
        print(alembic.stdout)
        print(alembic.stderr)


def domain_tests() -> None:
    backend = str(ROOT / "wa_backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)

    from domains.offers.contracts import (
        BasketLine,
        BasketPriceComponent,
        CatalogPrice,
        OfferCandidate,
        OfferProductRef,
        ProductTargetRef,
    )
    from domains.offers.core import OfferError
    from domains.offers.engine import calculate_offers
    from domains.offers.schemas import (
        OfferProductInput,
        OfferScopeInput,
    )
    from domains.offers.validation import (
        validate_offer_configuration,
    )
    from domains.offers.publishing import (
        _validate_offer_quantity_semantics,
    )
    from domains.uom_authority import (
        UomAuthorityError,
        _build_authority,
    )

    # Exact UOM authority: 1 carton = 10 base pieces.
    variant = SimpleNamespace(
        id=101,
        base_uom_id=1,
        quantity_scale=6,
        quantity_step=Decimal("1"),
    )
    carton_to_piece = SimpleNamespace(
        from_uom_id=2,
        to_uom_id=1,
        numerator=Decimal("10"),
        denominator=Decimal("1"),
    )
    authority = _build_authority(
        variant,
        [carton_to_piece],
    )
    check(
        authority.to_base(
            Decimal("2"),
            uom_id=2,
            validate_step=True,
        )
        == Decimal("20.000000"),
        "Exact UOM authority converts carton quantity to canonical base",
    )

    # Conflicting graph must fail instead of selecting an arbitrary path.
    pack_to_carton = SimpleNamespace(
        from_uom_id=3,
        to_uom_id=2,
        numerator=Decimal("2"),
        denominator=Decimal("1"),
    )
    pack_to_piece_conflict = SimpleNamespace(
        from_uom_id=3,
        to_uom_id=1,
        numerator=Decimal("19"),
        denominator=Decimal("1"),
    )
    try:
        _build_authority(
            variant,
            [
                carton_to_piece,
                pack_to_carton,
                pack_to_piece_conflict,
            ],
        )
        ambiguous_failed = False
    except UomAuthorityError as exc:
        ambiguous_failed = (
            exc.code
            == "UOM_CONVERSION_GRAPH_AMBIGUOUS"
        )
    check(
        ambiguous_failed,
        "Conflicting UOM conversion paths fail closed",
    )

    precision_variant = SimpleNamespace(
        id=202,
        base_uom_id=1,
        quantity_scale=2,
        quantity_step=Decimal("0.01"),
    )
    third = SimpleNamespace(
        from_uom_id=4,
        to_uom_id=1,
        numerator=Decimal("1"),
        denominator=Decimal("3"),
    )
    precision_authority = _build_authority(
        precision_variant,
        [third],
    )
    try:
        precision_authority.to_base(
            Decimal("1"),
            uom_id=4,
        )
        precision_failed = False
    except UomAuthorityError as exc:
        precision_failed = (
            exc.code
            == "UOM_CONVERSION_PRECISION_LOSS"
        )
    check(
        precision_failed,
        "Unrepresentable UOM conversion never rounds silently",
    )

    try:
        _validate_offer_quantity_semantics(
            authorities={101: authority},
            offer_type="BUY_X_GET_Y",
            payload={"buy_quantity": "0.15"},
            scopes=[],
            products=[
                OfferProductInput(
                    role="QUALIFYING",
                    product_variant_id=101,
                    uom_id=2,
                )
            ],
        )
        threshold_step_failed = False
    except UomAuthorityError as exc:
        threshold_step_failed = (
            exc.code
            == "UOM_CONVERTED_QUANTITY_INVALID"
        )
    check(
        threshold_step_failed,
        "Offer threshold quantity must match canonical product step after UOM conversion",
    )

    qualifying = [
        OfferProductInput(
            role="QUALIFYING",
            product_variant_id=101,
            uom_id=2,
        )
    ]
    rewards = [
        OfferProductInput(
            role="REWARD",
            product_variant_id=102,
            uom_id=5,
            quantity_per_application=Decimal("1"),
        ),
        OfferProductInput(
            role="REWARD",
            product_variant_id=103,
            uom_id=6,
            quantity_per_application=Decimal("2"),
        ),
    ]
    canonical = validate_offer_configuration(
        offer_type="BUY_X_GET_Y",
        payload={"buy_quantity": "2"},
        currency_code=None,
        scopes=[],
        products=qualifying + rewards,
    )
    check(
        Decimal(str(canonical["buy_quantity"])) == Decimal("2"),
        "BUY_X_GET_Y accepts typed multi-reward configuration",
    )

    try:
        validate_offer_configuration(
            offer_type="BUY_X_GET_Y",
            payload={"buy_quantity": "2"},
            currency_code=None,
            scopes=[],
            products=qualifying
            + [
                OfferProductInput(
                    role="REWARD",
                    product_variant_id=102,
                    uom_id=5,
                )
            ],
        )
        missing_reward_qty_failed = False
    except OfferError as exc:
        missing_reward_qty_failed = (
            exc.code
            == "OFFER_REWARD_QUANTITY_REQUIRED"
        )
    check(
        missing_reward_qty_failed,
        "Reward product without quantity is rejected",
    )

    try:
        validate_offer_configuration(
            offer_type="QUANTITY_TIERS",
            payload={
                "tiers": [
                    {
                        "minimum_quantity": "2",
                        "reward_type": "PERCENTAGE_DISCOUNT",
                        "reward_value": "10",
                    }
                ]
            },
            currency_code=None,
            scopes=[
                OfferScopeInput(
                    scope_type="PRODUCT_VARIANT",
                    product_variant_id=101,
                )
            ],
            products=[],
        )
        tier_uom_failed = False
    except OfferError as exc:
        tier_uom_failed = (
            exc.code
            == "OFFER_QUANTITY_TIER_SCOPE_REQUIRED"
        )
    check(
        tier_uom_failed,
        "Quantity-tier without explicit UOM is rejected",
    )

    line = BasketLine(
        line_id=1,
        product_variant_id=101,
        base_uom_id=1,
        quantity=Decimal("27.000000"),
        price_components=(
            BasketPriceComponent(
                uom_id=2,
                quantity=Decimal("2"),
                base_quantity=Decimal("20"),
                unit_price=Decimal("13.5"),
                price_entry_id=201,
            ),
            BasketPriceComponent(
                uom_id=1,
                quantity=Decimal("7"),
                base_quantity=Decimal("7"),
                unit_price=Decimal("0.35"),
                price_entry_id=202,
            ),
        ),
    )
    prices = {
        (101, 2): CatalogPrice(
            product_variant_id=101,
            uom_id=2,
            unit_price=Decimal("13.5"),
            price_entry_id=201,
        ),
        (101, 1): CatalogPrice(
            product_variant_id=101,
            uom_id=1,
            unit_price=Decimal("0.35"),
            price_entry_id=202,
        ),
    }
    pct = OfferCandidate(
        version_id=1,
        definition_id=1,
        revision=1,
        offer_type="PERCENTAGE_DISCOUNT",
        priority=10,
        stacking_mode="EXCLUSIVE",
        payload={"percentage": "10"},
        product_targets=(
            ProductTargetRef(
                product_variant_id=101,
                uom_id=2,
            ),
        ),
        products=(),
    )
    result = calculate_offers(
        lines=[line],
        candidates=[pct],
        catalog_prices=prices,
    )
    check(
        result.gross_amount
        == Decimal("29.450000")
        and result.discount_amount
        == Decimal("2.700000")
        and result.net_amount
        == Decimal("26.750000")
        and len(result.adjustments) == 1
        and result.adjustments[0].uom_id == 2,
        "Percentage discount targets carton component without discounting pieces",
    )

    buy_line = BasketLine(
        line_id=1,
        product_variant_id=101,
        base_uom_id=1,
        quantity=Decimal("40.000000"),
        price_components=(
            BasketPriceComponent(
                uom_id=2,
                quantity=Decimal("4"),
                base_quantity=Decimal("40"),
                unit_price=Decimal("13.5"),
                price_entry_id=201,
            ),
        ),
    )
    bogo = OfferCandidate(
        version_id=2,
        definition_id=2,
        revision=2,
        offer_type="BUY_X_GET_Y",
        priority=20,
        stacking_mode="EXCLUSIVE",
        payload={"buy_quantity": "2"},
        product_targets=(),
        products=(
            OfferProductRef(
                role="QUALIFYING",
                product_variant_id=101,
                uom_id=2,
                quantity_per_application=None,
            ),
            OfferProductRef(
                role="REWARD",
                product_variant_id=102,
                uom_id=5,
                quantity_per_application=Decimal("1"),
            ),
            OfferProductRef(
                role="REWARD",
                product_variant_id=103,
                uom_id=6,
                quantity_per_application=Decimal("2"),
            ),
        ),
    )
    bogo_prices = {
        (101, 2): CatalogPrice(
            product_variant_id=101,
            uom_id=2,
            unit_price=Decimal("13.5"),
            price_entry_id=201,
        ),
        (102, 5): CatalogPrice(
            product_variant_id=102,
            uom_id=5,
            unit_price=Decimal("3"),
            price_entry_id=301,
        ),
        (103, 6): CatalogPrice(
            product_variant_id=103,
            uom_id=6,
            unit_price=Decimal("1.5"),
            price_entry_id=401,
        ),
    }
    bogo_result = calculate_offers(
        lines=[buy_line],
        candidates=[bogo],
        catalog_prices=bogo_prices,
    )
    reward_shape = {
        (
            row.product_variant_id,
            row.uom_id,
            row.quantity,
        )
        for row in bogo_result.rewards
    }
    check(
        reward_shape
        == {
            (102, 5, Decimal("2")),
            (103, 6, Decimal("4")),
        }
        and bogo_result.applied_offers[0].application_count
        == 2,
        "A -> B + C multi-reward calculation is deterministic",
    )

    clamp_line = BasketLine(
        line_id=7,
        product_variant_id=700,
        base_uom_id=1,
        quantity=Decimal("1"),
        price_components=(
            BasketPriceComponent(
                uom_id=1,
                quantity=Decimal("1"),
                base_quantity=Decimal("1"),
                unit_price=Decimal("30"),
                price_entry_id=7001,
            ),
        ),
    )
    stackable = [
        OfferCandidate(
            version_id=10 + index,
            definition_id=10 + index,
            revision=10 + index,
            offer_type="FIXED_DISCOUNT",
            priority=5,
            stacking_mode="STACKABLE",
            payload={"amount": "20"},
            product_targets=(),
            products=(),
        )
        for index in range(2)
    ]
    clamp_result = calculate_offers(
        lines=[clamp_line],
        candidates=stackable,
        catalog_prices={},
    )
    check(
        clamp_result.discount_amount
        == Decimal("30.000000")
        and clamp_result.net_amount
        == Decimal("0.000000")
        and sum(
            (
                row.discount_amount
                for row in clamp_result.adjustments
            ),
            Decimal("0"),
        )
        == Decimal("30.000000"),
        "Stackable discounts clamp exactly at component net zero",
    )

    exclusive = [
        OfferCandidate(
            version_id=30 + index,
            definition_id=30 + index,
            revision=30 + index,
            offer_type="FIXED_DISCOUNT",
            priority=100,
            stacking_mode="EXCLUSIVE",
            payload={"amount": "10"},
            product_targets=(),
            products=(),
        )
        for index in range(2)
    ]
    try:
        calculate_offers(
            lines=[clamp_line],
            candidates=exclusive,
            catalog_prices={},
        )
        conflict_failed = False
    except OfferError as exc:
        conflict_failed = (
            exc.code
            == "OFFER_PRECEDENCE_CONFLICT"
        )
    check(
        conflict_failed,
        "Equal-benefit exclusive offer conflict fails closed",
    )

    bundle_lines = [
        BasketLine(
            line_id=1,
            product_variant_id=501,
            base_uom_id=1,
            quantity=Decimal("20"),
            price_components=(
                BasketPriceComponent(
                    uom_id=2,
                    quantity=Decimal("2"),
                    base_quantity=Decimal("20"),
                    unit_price=Decimal("10"),
                    price_entry_id=5012,
                ),
            ),
        ),
        BasketLine(
            line_id=2,
            product_variant_id=502,
            base_uom_id=3,
            quantity=Decimal("4"),
            price_components=(
                BasketPriceComponent(
                    uom_id=3,
                    quantity=Decimal("4"),
                    base_quantity=Decimal("4"),
                    unit_price=Decimal("5"),
                    price_entry_id=5023,
                ),
            ),
        ),
    ]
    bundle_offer = OfferCandidate(
        version_id=50,
        definition_id=50,
        revision=50,
        offer_type="BUNDLE",
        priority=50,
        stacking_mode="EXCLUSIVE",
        payload={
            "reward_type": "FIXED_PRICE",
            "reward_value": "15",
        },
        product_targets=(),
        products=(
            OfferProductRef(
                role="BUNDLE_COMPONENT",
                product_variant_id=501,
                uom_id=2,
                quantity_per_application=Decimal("1"),
            ),
            OfferProductRef(
                role="BUNDLE_COMPONENT",
                product_variant_id=502,
                uom_id=3,
                quantity_per_application=Decimal("2"),
            ),
        ),
    )
    bundle_result = calculate_offers(
        lines=bundle_lines,
        candidates=[bundle_offer],
        catalog_prices={},
    )
    check(
        bundle_result.applied_offers[0].application_count
        == 2
        and bundle_result.discount_amount
        == Decimal("10.000000"),
        "Bundle computes independent product/UOM quantities and fixed bundle price",
    )


def main() -> int:
    try:
        static_checks()
        domain_tests()
    except Exception as exc:
        check(
            False,
            "Gate completed without unexpected exception",
        )
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for item in failures:
        print(f"FAIL: {item}")

    if failures:
        print(
            "STAGE6H2A_MIXED_UOM_FLEXIBLE_REWARDS_GATE=FAIL"
        )
        return 1

    print(
        "STAGE6H2A_MIXED_UOM_FLEXIBLE_REWARDS_GATE=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
