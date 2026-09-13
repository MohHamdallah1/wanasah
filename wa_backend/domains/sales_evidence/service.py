from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.sales_calculation.contracts import CommercialCalculation
from domains.sales_calculation.rounding import (
    reconcile_components,
    round_currency,
)
from domains.sales_evidence.core import (
    EVIDENCE_SCHEMA_VERSION,
    SalesEvidenceError,
    currency_code,
    json_value,
    utc_now,
)
from domains.sales_evidence.models import (
    SalesLineAdjustment,
    SalesLineTaxComponent,
)
from models import RouteCommercialContext, Visit, VisitItem


ZERO = Decimal("0")


async def _locked_visit(
    db: AsyncSession,
    *,
    company_id: int,
    visit_id: int,
) -> Visit:
    row = await db.scalar(
        select(Visit)
        .where(
            Visit.company_id == int(company_id),
            Visit.id == int(visit_id),
        )
        .with_for_update()
    )
    if row is None:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_VISIT_NOT_FOUND",
            "Visit was not found inside this company.",
            status_code=404,
        )
    return row


async def _locked_items(
    db: AsyncSession,
    *,
    company_id: int,
    visit_id: int,
    item_ids: set[int],
) -> dict[int, VisitItem]:
    rows = list(
        (
            await db.scalars(
                select(VisitItem)
                .where(
                    VisitItem.company_id == int(company_id),
                    VisitItem.visit_id == int(visit_id),
                    VisitItem.id.in_(sorted(item_ids)),
                )
                .order_by(VisitItem.id)
                .with_for_update()
            )
        ).all()
    )
    result = {int(row.id): row for row in rows}
    missing = sorted(item_ids - set(result))
    if missing:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_LINE_NOT_FOUND",
            "One or more visit items are missing from this tenant/visit.",
            status_code=404,
            context={"visit_item_ids": missing},
        )
    return result


async def _validate_commercial_context(
    db: AsyncSession,
    *,
    company_id: int,
    commercial_context_id: int | None,
    calculation: CommercialCalculation,
) -> RouteCommercialContext | None:
    if commercial_context_id is None:
        return None
    row = await db.scalar(
        select(RouteCommercialContext).where(
            RouteCommercialContext.company_id == int(company_id),
            RouteCommercialContext.id == int(commercial_context_id),
        )
    )
    if row is None:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_CONTEXT_NOT_FOUND",
            "Commercial context was not found inside this company.",
            status_code=404,
        )

    expected = {
        "price_publication_revision": calculation.price_publication_revision_ceiling,
        "assignment_revision": calculation.assignment_revision_ceiling,
        "offer_ruleset_version": calculation.offer_revision_ceiling,
        "tax_ruleset_version": calculation.tax_revision_ceiling,
        "transaction_currency_code": calculation.transaction_currency_code,
        "rounding_policy_version": calculation.rounding_policy.version,
    }
    actual = {
        "price_publication_revision": int(row.price_publication_revision),
        "assignment_revision": int(row.assignment_revision),
        "offer_ruleset_version": (
            int(row.offer_ruleset_version)
            if row.offer_ruleset_version is not None
            else None
        ),
        "tax_ruleset_version": (
            int(row.tax_ruleset_version)
            if row.tax_ruleset_version is not None
            else None
        ),
        "transaction_currency_code": str(row.transaction_currency_code).upper(),
        "rounding_policy_version": (
            int(row.rounding_policy_version)
            if row.rounding_policy_version is not None
            else None
        ),
    }
    if actual != expected:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_CONTEXT_MISMATCH",
            "Commercial calculation does not match the locked route context.",
            context={"expected": expected, "actual": actual},
        )
    return row


def _document_offer_snapshot(calculation: CommercialCalculation) -> dict:
    return json_value(
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "offer_revision_ceiling": calculation.offer_revision_ceiling,
            "applied_offers": [
                {
                    "sequence": row.sequence,
                    "offer_version_id": row.offer_version_id,
                    "offer_definition_id": row.offer_definition_id,
                    "offer_revision": row.offer_revision,
                    "offer_type": row.offer_type,
                    "priority": row.priority,
                    "stacking_mode": row.stacking_mode,
                    "application_count": row.application_count,
                    "discount_amount": row.discount_amount,
                    "reward_value": row.reward_value,
                    "benefit_amount": row.benefit_amount,
                    "metadata": dict(row.metadata),
                }
                for row in calculation.applied_offers
            ],
            "free_goods": [
                {
                    "sequence": row.sequence,
                    "offer_version_id": row.offer_version_id,
                    "offer_definition_id": row.offer_definition_id,
                    "offer_revision": row.offer_revision,
                    "offer_type": row.offer_type,
                    "product_variant_id": row.product_variant_id,
                    "uom_id": row.uom_id,
                    "quantity": row.quantity,
                }
                for row in calculation.rewards
            ],
        }
    )


def _line_offer_snapshot(
    calculation: CommercialCalculation,
    *,
    line_id: int,
) -> dict:
    applied_by_sequence = {
        int(row.sequence): row for row in calculation.applied_offers
    }
    adjustments = [
        row for row in calculation.adjustments
        if int(row.line_id) == int(line_id)
    ]
    return json_value(
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "offer_revision_ceiling": calculation.offer_revision_ceiling,
            "adjustments": [
                {
                    "sequence": row.sequence,
                    "offer_version_id": row.offer_version_id,
                    "offer_definition_id": row.offer_definition_id,
                    "offer_revision": row.offer_revision,
                    "offer_type": row.offer_type,
                    "uom_id": row.uom_id,
                    "basis_amount": row.basis_amount,
                    "discount_amount": row.discount_amount,
                    "offer_metadata": (
                        dict(applied_by_sequence[row.sequence].metadata)
                        if row.sequence in applied_by_sequence
                        else {}
                    ),
                }
                for row in adjustments
            ],
        }
    )


def _line_tax_snapshot(calculation: CommercialCalculation, line) -> dict:
    resolution = calculation.tax_resolutions[line.product_variant_id]
    return json_value(
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "tax_revision_ceiling": calculation.tax_revision_ceiling,
            "tax_rule_set_id": line.tax_rule_set_id,
            "tax_rule_set_version_id": line.tax_rule_set_version_id,
            "tax_revision": line.tax_revision,
            "definition_version": resolution.definition_version,
            "price_mode": line.tax_price_mode,
            "scope_types": list(resolution.scope_types),
            "matched_jurisdiction_id": resolution.matched_jurisdiction_id,
            "jurisdiction_distance": resolution.jurisdiction_distance,
            "resolved_at": resolution.resolved_at,
            "components": [
                {
                    "tax_component_id": row.tax_component_id,
                    "component_code": row.component_code,
                    "name": row.name,
                    "sequence": row.sequence,
                    "rate": row.rate,
                    "basis_mode": row.basis_mode,
                    "reporting_code": row.reporting_code,
                    "unrounded_basis_amount": row.unrounded_basis_amount,
                    "unrounded_tax_amount": row.unrounded_tax_amount,
                    "tax_amount": row.tax_amount,
                }
                for row in line.tax_components
            ],
        }
    )


async def freeze_sales_evidence(
    db: AsyncSession,
    *,
    company_id: int,
    visit_id: int,
    line_item_ids: Mapping[int, int],
    calculation: CommercialCalculation,
    commercial_context_id: int | None,
    functional_currency_code: str,
) -> Visit:
    if int(company_id) <= 0 or int(visit_id) <= 0:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_INPUT_INVALID",
            "company_id and visit_id must be positive.",
            status_code=422,
        )

    transaction_currency = currency_code(
        calculation.transaction_currency_code,
        "transaction_currency_code",
    )
    functional_currency = currency_code(
        functional_currency_code,
        "functional_currency_code",
    )
    if calculation.rounding_policy.currency_code != transaction_currency:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_ROUNDING_CURRENCY_MISMATCH",
            "Calculation rounding currency does not match transaction currency.",
        )

    visit = await _locked_visit(
        db,
        company_id=company_id,
        visit_id=visit_id,
    )
    if visit.financial_evidence_version is not None:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_ALREADY_FROZEN",
            "Financial evidence for this visit is already frozen.",
        )

    calc_lines = {int(line.line_id): line for line in calculation.lines}
    mapping = {int(key): int(value) for key, value in line_item_ids.items()}
    if (
        set(mapping) != set(calc_lines)
        or len(set(mapping.values())) != len(mapping)
        or any(key <= 0 or value <= 0 for key, value in mapping.items())
    ):
        raise SalesEvidenceError(
            "SALES_EVIDENCE_LINE_MAPPING_INVALID",
            "Calculation lines must map one-to-one to visit items.",
            status_code=422,
            context={
                "calculation_line_ids": sorted(calc_lines),
                "mapping_line_ids": sorted(mapping),
            },
        )

    items = await _locked_items(
        db,
        company_id=company_id,
        visit_id=visit_id,
        item_ids=set(mapping.values()),
    )
    for line_id, item_id in mapping.items():
        item = items[item_id]
        line = calc_lines[line_id]
        if int(item.product_variant_id) != int(line.product_variant_id):
            raise SalesEvidenceError(
                "SALES_EVIDENCE_PRODUCT_MISMATCH",
                "Visit item product does not match calculated line product.",
                context={
                    "line_id": line_id,
                    "visit_item_id": item_id,
                    "visit_item_product_variant_id": int(item.product_variant_id),
                    "calculated_product_variant_id": int(line.product_variant_id),
                },
            )
        if item.financial_evidence_version is not None:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_ALREADY_FROZEN",
                "One or more visit items already carry frozen evidence.",
                context={"visit_item_id": item_id},
            )

    context = await _validate_commercial_context(
        db,
        company_id=company_id,
        commercial_context_id=commercial_context_id,
        calculation=calculation,
    )
    if context is not None:
        if str(context.functional_currency_code).upper() != functional_currency:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_FUNCTIONAL_CURRENCY_MISMATCH",
                "Functional currency does not match the locked route context.",
            )

    applied_by_sequence = {
        int(row.sequence): row for row in calculation.applied_offers
    }

    # Insert typed child evidence while the line is still open. PostgreSQL blocks
    # all later inserts once the VisitItem becomes frozen; deferred constraints
    # require the parent to be frozen before COMMIT.
    adjustments_by_line: dict[int, list] = {}
    for adjustment in calculation.adjustments:
        line_id = int(adjustment.line_id)
        if line_id not in mapping:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_ADJUSTMENT_LINE_UNKNOWN",
                "Offer adjustment refers to an unmapped calculation line.",
                context={"line_id": line_id},
            )
        if adjustment.discount_amount < ZERO:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_ADJUSTMENT_INVALID",
                "Persisted sales adjustments cannot be negative.",
                context={"line_id": line_id},
            )
        adjustments_by_line.setdefault(line_id, []).append(adjustment)

    for line_id, line in calc_lines.items():
        line_adjustments = sorted(
            adjustments_by_line.get(line_id, []),
            key=lambda row: (int(row.sequence), int(row.offer_version_id)),
        )
        if not line_adjustments:
            if line.discount_amount != ZERO:
                raise SalesEvidenceError(
                    "SALES_EVIDENCE_ADJUSTMENT_RECONCILIATION_FAILED",
                    "A discounted line has no typed adjustment evidence.",
                    context={"line_id": line_id},
                )
            continue

        rounded_amounts = reconcile_components(
            raw_amounts=tuple(row.discount_amount for row in line_adjustments),
            target_total=line.discount_amount,
            policy=calculation.rounding_policy,
        )
        for index, adjustment in enumerate(line_adjustments):
            item_id = mapping[line_id]
            applied = applied_by_sequence.get(int(adjustment.sequence))
            metadata = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "priority": applied.priority if applied else None,
                "stacking_mode": applied.stacking_mode if applied else None,
                "application_count": applied.application_count if applied else None,
                "target_uom_id": int(adjustment.uom_id),
                "reward_value": applied.reward_value if applied else ZERO,
                "benefit_amount": applied.benefit_amount if applied else adjustment.discount_amount,
                "unrounded_basis_amount": adjustment.basis_amount,
                "unrounded_adjustment_amount": adjustment.discount_amount,
                "metadata": dict(applied.metadata) if applied else {},
            }
            db.add(
                SalesLineAdjustment(
                    company_id=int(company_id),
                    visit_item_id=item_id,
                    sequence=int(adjustment.sequence),
                    offer_version_id=int(adjustment.offer_version_id),
                    rule_type=str(adjustment.offer_type),
                    rule_id=int(adjustment.offer_definition_id),
                    rule_version=int(adjustment.offer_revision),
                    basis_amount=round_currency(
                        adjustment.basis_amount,
                        calculation.rounding_policy,
                    ),
                    adjustment_amount=rounded_amounts[index],
                    metadata_snapshot=json_value(metadata),
                )
            )

    for line in calculation.lines:
        item_id = mapping[int(line.line_id)]
        resolution = calculation.tax_resolutions[int(line.product_variant_id)]
        if not line.tax_components:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_TAX_COMPONENT_REQUIRED",
                "Every frozen sales line requires typed tax evidence, including zero-rate tax.",
                context={"line_id": int(line.line_id)},
            )
        for component in line.tax_components:
            db.add(
                SalesLineTaxComponent(
                    company_id=int(company_id),
                    visit_item_id=item_id,
                    sequence=int(component.sequence),
                    tax_rule_set_id=int(line.tax_rule_set_id),
                    tax_rule_set_version_id=int(line.tax_rule_set_version_id),
                    tax_revision=int(line.tax_revision),
                    tax_component_id=int(component.tax_component_id),
                    component_code=str(component.component_code),
                    tax_name=str(component.name),
                    rate=component.rate,
                    basis_mode=str(component.basis_mode),
                    taxable_amount=round_currency(
                        component.unrounded_basis_amount,
                        calculation.rounding_policy,
                    ),
                    tax_amount=component.tax_amount,
                    reporting_code=component.reporting_code,
                    matched_jurisdiction_id=resolution.matched_jurisdiction_id,
                    jurisdiction_distance=resolution.jurisdiction_distance,
                    metadata_snapshot=json_value(
                        {
                            "schema_version": EVIDENCE_SCHEMA_VERSION,
                            "scope_types": list(resolution.scope_types),
                            "definition_version": resolution.definition_version,
                            "unrounded_basis_amount": component.unrounded_basis_amount,
                            "unrounded_tax_amount": component.unrounded_tax_amount,
                            "resolved_at": resolution.resolved_at,
                        }
                    ),
                )
            )

    await db.flush()

    frozen_at = utc_now()
    for line_id, item_id in mapping.items():
        item = items[item_id]
        line = calc_lines[line_id]
        item.financial_evidence_version = EVIDENCE_SCHEMA_VERSION
        item.financial_evidence_frozen_at = frozen_at
        item.commercial_context_id = commercial_context_id
        item.base_uom_id = int(line.base_uom_id)
        item.canonical_quantity = line.quantity
        item.selected_price_entry_id = int(line.price_entry_id)
        item.price_publication_revision = int(line.price_publication_revision)
        item.assignment_revision = int(line.assignment_revision)
        item.price_per_unit_at_sale = line.unit_price
        item.total_price = line.final_amount
        item.gross_amount = line.gross_amount
        item.discount_amount = line.discount_amount
        item.post_offer_amount = line.post_offer_amount
        item.taxable_amount = line.taxable_amount
        item.tax_amount = line.tax_amount
        item.net_amount = line.final_amount
        item.transaction_currency_code = transaction_currency
        item.functional_currency_code = functional_currency
        item.offer_snapshot = _line_offer_snapshot(
            calculation,
            line_id=line_id,
        )
        item.tax_snapshot = _line_tax_snapshot(calculation, line)

    totals = calculation.totals
    visit.financial_evidence_version = EVIDENCE_SCHEMA_VERSION
    visit.financial_evidence_frozen_at = frozen_at
    visit.commercial_calculated_at = calculation.calculated_at
    visit.commercial_context_id = commercial_context_id
    visit.transaction_currency_code = transaction_currency
    visit.functional_currency_code = functional_currency
    visit.rounding_policy_version = int(calculation.rounding_policy.version)
    visit.rounding_precision = int(calculation.rounding_policy.precision)
    visit.rounding_mode = str(calculation.rounding_policy.mode)
    visit.price_publication_revision_ceiling = int(
        calculation.price_publication_revision_ceiling
    )
    visit.assignment_revision_ceiling = int(
        calculation.assignment_revision_ceiling
    )
    visit.offer_revision_ceiling = int(calculation.offer_revision_ceiling)
    visit.tax_revision_ceiling = int(calculation.tax_revision_ceiling)
    visit.amount_before_tax_and_discount = totals.gross_amount
    visit.discount_applied = totals.discount_amount
    visit.post_offer_amount = totals.post_offer_amount
    visit.taxable_amount = totals.taxable_amount
    visit.tax_amount = totals.tax_amount
    visit.line_total_amount = totals.line_total_amount
    visit.rounding_adjustment = totals.rounding_adjustment
    visit.final_amount_due = totals.final_amount
    visit.offer_snapshot = _document_offer_snapshot(calculation)

    await db.flush()
    return visit
