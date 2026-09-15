from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        failures.append(label)


def run_gate(filename: str, marker: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / filename)],
        cwd=BACKEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    check(
        proc.returncode == 0 and marker in proc.stdout,
        f"{filename} returns its required PASS marker",
    )


def calculation_order_check() -> None:
    service_path = BACKEND / "domains/sales_calculation/service.py"
    pipeline_path = BACKEND / "domains/sales_calculation/pipeline.py"

    service = service_path.read_text(encoding="utf-8")
    pipeline = pipeline_path.read_text(encoding="utf-8")

    service_start = service.index("async def resolve_and_calculate_document(")
    service_body = service[service_start:]

    price_pos = service_body.index("price_rows = await resolve_prices_bulk(")
    offer_pos = service_body.index("offer_result = calculate_offers(")
    tax_pos = service_body.index(
        "tax_resolutions, used_tax_ceiling = await resolve_tax_rules_bulk("
    )
    document_pos = service_body.index("return calculate_document(")

    check(
        price_pos < offer_pos < tax_pos < document_pos,
        "Commercial authority order is price -> offer -> tax -> document calculation",
    )

    pipeline_start = pipeline.index("def calculate_document(")
    pipeline_body = pipeline[pipeline_start:]

    gross_pos = pipeline_body.index("gross_raw = line.gross_amount")
    post_offer_pos = pipeline_body.index(
        "post_offer_raw = offer_result.line_net_amounts[line.line_id]"
    )
    tax_calc_pos = pipeline_body.index(
        "tax_calc = calculate_tax(post_offer_raw, tax_resolution)"
    )
    rounding_pos = pipeline_body.index(
        "gross = round_currency(gross_raw, policy)"
    )
    component_reconcile_pos = pipeline_body.index(
        "component_amounts = reconcile_components("
    )
    line_reconcile_pos = pipeline_body.index(
        'if gross - discount != post_offer:'
    )

    check(
        gross_pos
        < post_offer_pos
        < tax_calc_pos
        < rounding_pos
        < component_reconcile_pos
        < line_reconcile_pos,
        "Line calculation order preserves offer -> taxable/tax -> rounding -> reconciliation",
    )

    required_markers = (
        "CALCULATION_OFFER_RESULT_MISMATCH",
        "CALCULATION_TAX_RESULT_MISMATCH",
        "CALCULATION_TAX_RECONCILIATION_FAILED",
        "CALCULATION_LINE_RECONCILIATION_FAILED",
    )
    check(
        all(marker in pipeline_body for marker in required_markers),
        "Calculation pipeline remains fail-closed on offer/tax/rounding reconciliation",
    )


def main() -> int:
    try:
        calculation_order_check()

        gates = (
            (
                "gate_stage6_typed_offer_engine.py",
                "STAGE6_TYPED_OFFER_ENGINE_GATE=PASS",
            ),
            (
                "gate_stage6_tax_rule_versions.py",
                "STAGE6_TAX_RULE_VERSIONS_GATE=PASS",
            ),
            (
                "gate_stage6_sales_line_evidence.py",
                "STAGE6_SALES_LINE_EVIDENCE_GATE=PASS",
            ),
            (
                "gate_stage6_financial_snapshots.py",
                "STAGE6_FINANCIAL_SNAPSHOTS_GATE=PASS",
            ),
            (
                "gate_stage6_return_reversal.py",
                "STAGE6_RETURN_REVERSAL_GATE=PASS",
            ),
        )
        for filename, marker in gates:
            run_gate(filename, marker)
    except Exception as exc:
        check(False, "Stage 6 aggregate gate completed without unexpected exception")
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("OFFER_TAX_SNAPSHOT_GATE=FAIL")
        return 1

    print("OFFER_TAX_SNAPSHOT_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
