from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "wa_backend"))

EXPECTED_HEAD = "fa129278c7173fe39b4a991b7ee22950c05f07d5"
H2A_HELPER = ROOT / "stage6h2a_mixed_uom_flexible_rewards_guarded_patch_v2.py"
H2B1_PATCH = ROOT / "stage6h2b1_immutable_mixed_uom_price_evidence_guarded_patch.py"

checks = 0
failures: list[str] = []


def run(*args: str) -> str:
    cp = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            cp.stderr.strip()
            or cp.stdout.strip()
            or f"command failed: {args}"
        )
    return cp.stdout.strip()


def check(ok: bool, label: str, detail: str | None = None) -> None:
    global checks
    checks += 1
    print(("  [PASS] " if ok else "  [FAIL] ") + label)
    if not ok:
        failures.append(label)
        if detail:
            print("   " + detail.replace("\n", "\n   "))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_surface() -> tuple[set[str], list[str]]:
    status = run("git", "status", "--porcelain", "--untracked-files=all")
    changed: set[str] = set()
    staged: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        code = line[:2]
        rel = line[3:].strip().replace("\\", "/")
        if not rel.startswith("wa_backend/"):
            continue
        changed.add(rel)
        if code[0] not in {" ", "?"}:
            staged.append(line)
    return changed, staged


def static_checks() -> None:
    check(
        run("git", "rev-parse", "HEAD") == EXPECTED_HEAD,
        "HEAD remains exact Stage 6H.1 committed baseline",
    )
    check(
        run("git", "rev-parse", "origin/main") == EXPECTED_HEAD,
        "origin/main remains exact Stage 6H.1 committed baseline",
    )
    check(H2A_HELPER.is_file(), "Stage 6H.2A baseline helper exists")
    check(H2B1_PATCH.is_file(), "Stage 6H.2B.1 guarded patch exists")
    if not H2A_HELPER.is_file() or not H2B1_PATCH.is_file():
        return

    h2a = load_module(H2A_HELPER, "gate_h2a")
    h2b1 = load_module(H2B1_PATCH, "gate_h2b1")

    expected_surface = (
        set(h2a.FULL_REPLACEMENTS)
        | set(h2a.REPLACE_OPS)
        | set(h2a.BETWEEN_OPS)
        | set(h2a.NEW_FILES)
        | set(h2b1.FULL_REPLACEMENTS)
        | set(h2b1.REPLACE_OPS)
        | set(h2b1.NEW_FILES)
    )
    actual_surface, staged = production_surface()
    check(
        actual_surface == expected_surface,
        "Changed production surface is exactly Stage 6H.2A + 6H.2B.1",
        detail=(
            f"missing={sorted(expected_surface - actual_surface)}\n"
            f"unexpected={sorted(actual_surface - expected_surface)}"
        ) if actual_surface != expected_surface else None,
    )
    check(
        not staged,
        "No production changes are staged before technical acceptance",
        detail="\n".join(staged) if staged else None,
    )

    try:
        run("git", "diff", "--check")
        check(True, "git diff --check")
    except Exception as exc:
        check(False, "git diff --check", str(exc))

    deleted = []
    diff_names = run("git", "diff", "--name-status")
    for line in diff_names.splitlines():
        if line.startswith("D\t"):
            deleted.append(line[2:].strip())
    check(
        not deleted,
        "Stage 6H.2B.1 deletes no tracked file",
        detail=", ".join(deleted) if deleted else None,
    )

    all_expected = sorted(expected_surface)
    for rel in all_expected:
        path = ROOT / rel
        check(path.is_file(), f"Expected file exists: {rel}")
        if path.is_file() and rel.endswith(".py"):
            try:
                compile(path.read_text(encoding="utf-8"), rel, "exec")
                check(True, f"Python compile: {rel}")
            except Exception as exc:
                check(False, f"Python compile: {rel}", repr(exc))

    for rel, expected_text in h2b1.FULL_REPLACEMENTS.items():
        path = ROOT / rel
        check(
            path.is_file() and path.read_text(encoding="utf-8") == expected_text,
            f"Exact rendered content: {rel}",
        )
    for rel, expected_text in h2b1.NEW_FILES.items():
        path = ROOT / rel
        check(
            path.is_file() and path.read_text(encoding="utf-8") == expected_text,
            f"Exact new file content: {rel}",
        )

    models = (ROOT / "wa_backend/models.py").read_text(encoding="utf-8")
    core = (
        ROOT / "wa_backend/domains/sales_evidence/core.py"
    ).read_text(encoding="utf-8")
    evidence = (
        ROOT / "wa_backend/domains/sales_evidence/service.py"
    ).read_text(encoding="utf-8")
    evidence_models = (
        ROOT / "wa_backend/domains/sales_evidence/models.py"
    ).read_text(encoding="utf-8")
    calc_contracts = (
        ROOT / "wa_backend/domains/sales_calculation/contracts.py"
    ).read_text(encoding="utf-8")
    calc_service = (
        ROOT / "wa_backend/domains/sales_calculation/service.py"
    ).read_text(encoding="utf-8")
    calc_pipeline = (
        ROOT / "wa_backend/domains/sales_calculation/pipeline.py"
    ).read_text(encoding="utf-8")
    offer_contracts = (
        ROOT / "wa_backend/domains/offers/contracts.py"
    ).read_text(encoding="utf-8")
    migration = next(
        (ROOT / rel).read_text(encoding="utf-8")
        for rel in h2b1.NEW_FILES
    )

    check(
        "EVIDENCE_SCHEMA_VERSION = 3" in core,
        "Evidence schema version is exactly 3",
    )
    check(
        models.count("financial_evidence_version = 3") >= 2
        and "selected_price_entry_id IS NULL" in models,
        "Visit and VisitItem ORM shapes use v3 component-price authority",
    )
    check(
        "class SalesLinePriceComponent" in evidence_models
        and "uq_sales_line_price_component_uom" in evidence_models,
        "Typed immutable SalesLinePriceComponent model exists",
    )
    check(
        "uom_id = Column(Integer, nullable=False)" in evidence_models
        and "uq_sales_line_adjustment_sequence_uom" in evidence_models,
        "SalesLineAdjustment is typed per UOM component",
    )
    check(
        "SalesLinePriceComponent(" in evidence
        and "item.selected_price_entry_id = None" in evidence
        and "uom_id=int(adjustment.uom_id)" in evidence,
        "Freeze service persists price components and removes single-price authority",
    )
    check(
        "class CalculationInputComponent" in calc_contracts
        and "components: tuple[CalculationInputComponent, ...]" in calc_contracts
        and "price_components: tuple[CalculatedPriceComponent, ...]" in calc_contracts,
        "Sales calculation contracts are mixed-UOM native",
    )
    check(
        "load_variant_uom_authorities" in calc_service
        and "pairs=sorted(requested_pairs)" in calc_service
        and "BasketPriceComponent(" in calc_service,
        "Sales calculation resolves every sold Variant/UOM pair in bulk",
    )
    check(
        "CalculatedPriceComponent(" in calc_pipeline
        and "line.price_components" in calc_pipeline
        and "CALCULATION_PRICE_COMPONENT_RECONCILIATION_FAILED" in calc_pipeline,
        "Pipeline reconciles typed price components",
    )
    check(
        "price_publication_revision: int" in offer_contracts
        and "assignment_revision: int" in offer_contracts,
        "Offer basket price component carries locked revision evidence",
    )
    check(
        'down_revision: Union[str, Sequence[str], None] = "c3f8a1d6e2b4"'
        in migration,
        "Migration is chained exactly after Stage 6H.2A",
    )
    check(
        "sales_line_price_components" in migration
        and "price_base_total <> NEW.canonical_quantity" in migration
        and "price_gross_total <> NEW.gross_amount" in migration,
        "DB deferred reconciliation covers price quantity and gross",
    )
    check(
        "guard_sales_line_child_evidence()" in migration
        and "ensure_sales_line_parent_frozen()" in migration
        and "FORCE ROW LEVEL SECURITY" in migration,
        "New price evidence is insert-only, parent-frozen and RLS-hardened",
    )


def runtime_checks() -> None:
    from domains.offers.contracts import (
        BasketLine,
        BasketPriceComponent,
        OfferEngineResult,
        ZERO,
    )
    from domains.sales_calculation.contracts import RoundingPolicy
    from domains.sales_calculation.pipeline import calculate_document
    from domains.taxation.contracts import TaxComponentSnapshot, TaxResolution

    when = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
    line = BasketLine(
        line_id=1,
        product_variant_id=11,
        base_uom_id=101,
        quantity=Decimal("107.000000"),
        price_components=(
            BasketPriceComponent(
                uom_id=202,
                quantity=Decimal("2.000000"),
                base_quantity=Decimal("100.000000"),
                unit_price=Decimal("13.500000"),
                price_entry_id=301,
                price_publication_revision=7,
                assignment_revision=9,
            ),
            BasketPriceComponent(
                uom_id=101,
                quantity=Decimal("7.000000"),
                base_quantity=Decimal("7.000000"),
                unit_price=Decimal("0.350000"),
                price_entry_id=302,
                price_publication_revision=7,
                assignment_revision=9,
            ),
        ),
    )
    gross = line.gross_amount
    offer_result = OfferEngineResult(
        calculated_at=when,
        gross_amount=gross,
        discount_amount=ZERO,
        net_amount=gross,
        line_net_amounts={1: gross},
        adjustments=(),
        rewards=(),
        applied_offers=(),
    )
    tax = TaxResolution(
        product_variant_id=11,
        tax_rule_set_id=401,
        tax_rule_set_version_id=402,
        tax_revision=5,
        definition_version=1,
        priority=0,
        price_mode="EXCLUSIVE",
        scope_types=(),
        matched_jurisdiction_id=501,
        jurisdiction_distance=0,
        components=(
            TaxComponentSnapshot(
                component_id=601,
                component_code="ZERO",
                name="Zero Tax",
                sequence=1,
                rate=Decimal("0"),
                basis_mode="TAXABLE_BASE",
                reporting_code=None,
            ),
        ),
        resolved_at=when,
    )
    result = calculate_document(
        basket_lines=(line,),
        offer_result=offer_result,
        tax_resolutions={11: tax},
        transaction_currency_code="JOD",
        rounding_policy=RoundingPolicy(
            version=1,
            currency_code="JOD",
            precision=3,
            mode="HALF_UP",
        ),
        price_publication_revision_ceiling=7,
        assignment_revision_ceiling=9,
        offer_revision_ceiling=0,
        tax_revision_ceiling=5,
    )
    calculated = result.lines[0]
    check(
        gross == Decimal("29.450000"),
        "Mixed-UOM gross preserves independent carton + piece prices",
        detail=f"gross={gross}",
    )
    check(
        len(calculated.price_components) == 2
        and sum(
            (row.base_quantity for row in calculated.price_components),
            Decimal("0"),
        ) == Decimal("107.000000"),
        "Calculated price components reconcile exactly to canonical quantity",
    )
    check(
        sum(
            (row.gross_amount for row in calculated.price_components),
            Decimal("0"),
        ) == gross,
        "Calculated price components reconcile exactly to raw line gross",
    )
    check(
        result.totals.final_amount == Decimal("29.450")
        and result.totals.tax_amount == Decimal("0.000"),
        "Mixed-UOM line reaches deterministic rounded document total",
        detail=(
            f"final={result.totals.final_amount} "
            f"tax={result.totals.tax_amount}"
        ),
    )


def main() -> int:
    try:
        static_checks()
        runtime_checks()
    except Exception as exc:
        check(
            False,
            "Gate completed without unexpected exception",
            repr(exc),
        )

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(
        "STAGE6H2B1_IMMUTABLE_MIXED_UOM_PRICE_EVIDENCE_GATE="
        + ("PASS" if not failures else "FAIL")
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
