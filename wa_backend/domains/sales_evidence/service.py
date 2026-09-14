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
    SalesLinePriceComponent,
    SalesLineTaxComponent,
    SalesRewardEvidence,
    SalesVisitRevision,
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
                    "base_quantity": row.base_quantity,
                    "price_entry_id": row.price_entry_id,
                    "price_publication_revision": (
                        row.price_publication_revision
                    ),
                    "assignment_revision": row.assignment_revision,
                    "unit_price": row.unit_price,
                    "reward_value": row.reward_value,
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

    if commercial_context_id is None:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_CONTEXT_REQUIRED",
            "A locked RouteCommercialContext is required for immutable sales evidence.",
            status_code=422,
        )

    visit = await _locked_visit(
        db,
        company_id=company_id,
        visit_id=visit_id,
    )
    if (
        visit.current_sales_revision_id is not None
        or visit.financial_evidence_version is not None
    ):
        raise SalesEvidenceError(
            "SALES_EVIDENCE_CURRENT_REVISION_EXISTS",
            "The visit already points to a current immutable sales revision. "
            "Reverse the completed visit before creating a correction revision.",
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

    previous_revision = (
        await db.execute(
            select(
                SalesVisitRevision.id,
                SalesVisitRevision.revision_number,
            )
            .where(
                SalesVisitRevision.company_id == int(company_id),
                SalesVisitRevision.visit_id == int(visit_id),
            )
            .order_by(SalesVisitRevision.revision_number.desc())
            .limit(1)
        )
    ).first()
    next_revision_number = (
        int(previous_revision.revision_number) + 1
        if previous_revision is not None
        else 1
    )
    previous_revision_id = (
        int(previous_revision.id)
        if previous_revision is not None
        else None
    )

    totals = calculation.totals
    document_offer_snapshot = _document_offer_snapshot(calculation)
    revision = SalesVisitRevision(
        company_id=int(company_id),
        visit_id=int(visit_id),
        revision_number=next_revision_number,
        supersedes_revision_id=previous_revision_id,
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        frozen_at=None,
        commercial_calculated_at=calculation.calculated_at,
        commercial_context_id=int(commercial_context_id),
        transaction_currency_code=transaction_currency,
        functional_currency_code=functional_currency,
        rounding_policy_version=int(calculation.rounding_policy.version),
        rounding_precision=int(calculation.rounding_policy.precision),
        rounding_mode=str(calculation.rounding_policy.mode),
        price_publication_revision_ceiling=int(
            calculation.price_publication_revision_ceiling
        ),
        assignment_revision_ceiling=int(
            calculation.assignment_revision_ceiling
        ),
        offer_revision_ceiling=int(calculation.offer_revision_ceiling),
        tax_revision_ceiling=int(calculation.tax_revision_ceiling),
        gross_amount=totals.gross_amount,
        discount_amount=totals.discount_amount,
        post_offer_amount=totals.post_offer_amount,
        taxable_amount=totals.taxable_amount,
        tax_amount=totals.tax_amount,
        line_total_amount=totals.line_total_amount,
        rounding_adjustment=totals.rounding_adjustment,
        final_amount=totals.final_amount,
        offer_snapshot=document_offer_snapshot,
    )
    db.add(revision)
    await db.flush()

    seen_reward_keys: set[tuple[int, int, int]] = set()
    for reward in calculation.rewards:
        reward_key = (
            int(reward.sequence),
            int(reward.product_variant_id),
            int(reward.uom_id),
        )
        if reward_key in seen_reward_keys:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_REWARD_DUPLICATE",
                "Reward evidence repeats the same offer/product/UOM.",
                context={
                    "offer_sequence": reward_key[0],
                    "product_variant_id": reward_key[1],
                    "uom_id": reward_key[2],
                },
            )
        seen_reward_keys.add(reward_key)
        if (
            reward.quantity <= ZERO
            or reward.base_quantity <= ZERO
            or reward.unit_price < ZERO
            or reward.reward_value < ZERO
        ):
            raise SalesEvidenceError(
                "SALES_EVIDENCE_REWARD_INVALID",
                "Reward evidence contains invalid quantities or monetary values.",
                context={
                    "offer_sequence": int(reward.sequence),
                    "product_variant_id": int(reward.product_variant_id),
                    "uom_id": int(reward.uom_id),
                },
            )
        db.add(
            SalesRewardEvidence(
                company_id=int(company_id),
                visit_id=int(visit_id),
                sales_revision_id=int(revision.id),
                sequence=int(reward.sequence),
                offer_version_id=int(reward.offer_version_id),
                offer_definition_id=int(reward.offer_definition_id),
                offer_revision=int(reward.offer_revision),
                offer_type=str(reward.offer_type),
                product_variant_id=int(reward.product_variant_id),
                uom_id=int(reward.uom_id),
                quantity=reward.quantity,
                base_quantity=reward.base_quantity,
                price_entry_id=int(reward.price_entry_id),
                price_publication_revision=int(
                    reward.price_publication_revision
                ),
                assignment_revision=int(reward.assignment_revision),
                unit_price=reward.unit_price,
                reward_value=reward.reward_value,
            )
        )

    # Persist exact sold-UOM pricing evidence before freezing the parent.
    # The parent VisitItem intentionally carries no single price authority in
    # schema v4; sales_line_price_components is the only immutable price SSOT.
    for line in calculation.lines:
        item_id = mapping[int(line.line_id)]
        if not line.price_components:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_PRICE_COMPONENT_REQUIRED",
                "Every frozen sales line requires at least one typed price component.",
                context={"line_id": int(line.line_id)},
            )
        expected_sequence = 1
        seen_uoms: set[int] = set()
        for component in line.price_components:
            if int(component.sequence) != expected_sequence:
                raise SalesEvidenceError(
                    "SALES_EVIDENCE_PRICE_SEQUENCE_INVALID",
                    "Price component sequence must be contiguous from 1.",
                    context={"line_id": int(line.line_id)},
                )
            expected_sequence += 1
            uom_id = int(component.uom_id)
            if uom_id in seen_uoms:
                raise SalesEvidenceError(
                    "SALES_EVIDENCE_PRICE_UOM_DUPLICATE",
                    "A frozen sales line cannot repeat the same price UOM.",
                    context={"line_id": int(line.line_id), "uom_id": uom_id},
                )
            seen_uoms.add(uom_id)
            db.add(
                SalesLinePriceComponent(
                    company_id=int(company_id),
                    visit_item_id=item_id,
                    sequence=int(component.sequence),
                    uom_id=uom_id,
                    quantity=component.quantity,
                    base_quantity=component.base_quantity,
                    price_entry_id=int(component.price_entry_id),
                    price_publication_revision=int(
                        component.price_publication_revision
                    ),
                    assignment_revision=int(component.assignment_revision),
                    unit_price=component.unit_price,
                    gross_amount=component.gross_amount,
                )
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
            key=lambda row: (
                int(row.sequence),
                int(row.offer_version_id),
                int(row.uom_id),
            ),
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
                    uom_id=int(adjustment.uom_id),
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
        item.sales_revision_id = int(revision.id)
        item.base_uom_id = int(line.base_uom_id)
        item.canonical_quantity = line.quantity
        # Schema v3 removes the misleading single-price parent authority.
        # Keep the legacy display field only as a projection for single-UOM lines.
        item.selected_price_entry_id = None
        item.price_publication_revision = None
        item.assignment_revision = None
        item.price_per_unit_at_sale = (
            line.price_components[0].unit_price
            if len(line.price_components) == 1
            else ZERO
        )
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

    # Flush frozen line parents before sealing the document revision.
    await db.flush()

    revision.frozen_at = frozen_at
    await db.flush()

    visit.current_sales_revision_id = int(revision.id)
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
    visit.offer_snapshot = document_offer_snapshot

    await db.flush()
    return visit
