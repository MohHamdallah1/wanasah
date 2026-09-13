from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domains.taxation.calculator import calculate_tax
from domains.taxation.core import require_aware_datetime, utc_now
from domains.taxation.resolver import resolve_tax_rules_bulk
from domains.taxation.schemas import TaxPreviewRequest


def _decimal(value: Decimal) -> str:
    return format(value, "f")


async def preview_tax_document(
    db: AsyncSession,
    *,
    company_id: int,
    payload: TaxPreviewRequest,
) -> dict[str, Any]:
    when = require_aware_datetime(payload.as_of or utc_now(), "as_of")
    resolutions, ceiling = await resolve_tax_rules_bulk(
        db,
        company_id=company_id,
        product_variant_ids=[line.product_variant_id for line in payload.lines],
        jurisdiction_id=payload.jurisdiction_id,
        customer_id=payload.customer_id,
        document_type_code=payload.document_type_code,
        as_of=when,
        revision_ceiling=payload.tax_revision_ceiling,
    )

    line_results: list[dict[str, Any]] = []
    taxable_total = Decimal("0")
    tax_total = Decimal("0")
    document_total = Decimal("0")

    for line in payload.lines:
        resolution = resolutions[int(line.product_variant_id)]
        calculation = calculate_tax(line.amount, resolution)
        taxable_total += calculation.taxable_base
        tax_total += calculation.tax_amount
        document_total += calculation.total_amount

        line_results.append(
            {
                "line_id": int(line.line_id),
                "product_variant_id": int(line.product_variant_id),
                "input_amount": _decimal(calculation.input_amount),
                "taxable_base": _decimal(calculation.taxable_base),
                "tax_amount": _decimal(calculation.tax_amount),
                "total_amount": _decimal(calculation.total_amount),
                "resolution": {
                    "tax_rule_set_id": resolution.tax_rule_set_id,
                    "tax_rule_set_version_id": resolution.tax_rule_set_version_id,
                    "tax_revision": resolution.tax_revision,
                    "definition_version": resolution.definition_version,
                    "priority": resolution.priority,
                    "price_mode": resolution.price_mode,
                    "scope_types": list(resolution.scope_types),
                    "matched_jurisdiction_id": resolution.matched_jurisdiction_id,
                    "jurisdiction_distance": resolution.jurisdiction_distance,
                    "resolved_at": resolution.resolved_at.isoformat(),
                },
                "components": [
                    {
                        "tax_component_id": item.component_id,
                        "component_code": item.component_code,
                        "name": item.name,
                        "sequence": item.sequence,
                        "rate": _decimal(item.rate),
                        "basis_mode": item.basis_mode,
                        "reporting_code": item.reporting_code,
                        "basis_amount": _decimal(item.basis_amount),
                        "tax_amount": _decimal(item.tax_amount),
                    }
                    for item in calculation.components
                ],
            }
        )

    return {
        "calculated_at": when.isoformat(),
        "jurisdiction_id": int(payload.jurisdiction_id),
        "customer_id": payload.customer_id,
        "document_type_code": payload.document_type_code,
        "tax_revision_ceiling": int(ceiling),
        "lines": line_results,
        "totals": {
            "taxable_base": _decimal(taxable_total),
            "tax_amount": _decimal(tax_total),
            "total_amount": _decimal(document_total),
        },
    }
