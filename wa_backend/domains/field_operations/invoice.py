"""Serialize canonical commercial calculation and immutable posted evidence."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from domains.pricing.context import require_route_commercial_context
from domains.sales_calculation.driver_sale import DriverSaleInput, resolve_driver_sale
from domains.sales_evidence.models import SalesRewardEvidence, SalesVisitRevision
from models import VisitItem
from .contracts import FieldContractError
from .context import assigned_visit, owned_visit, shop_commercial_state

_TOTALS = ("gross_amount", "discount_amount", "post_offer_amount", "taxable_amount",
           "tax_amount", "line_total_amount", "rounding_adjustment", "final_amount")


def _exact(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise FieldContractError("FIELD_INVOICE_EVIDENCE_INVALID", "Invoice evidence is invalid.")
    return format(amount, "f")


def invoice_payload(*, totals, currency, rounding, lines, rewards, status, calculated_at):
    return {
        "status": status, "currency_code": currency,
        "calculated_at": calculated_at.isoformat(),
        "rounding": {"precision": rounding.precision, "mode": rounding.mode},
        "totals": {key: _exact(getattr(totals, key)) for key in _TOTALS},
        "lines": [{
            "product_variant_id": line.product_variant_id,
            "gross_amount": _exact(line.gross_amount),
            "discount_amount": _exact(line.discount_amount),
            "tax_amount": _exact(line.tax_amount),
            "final_amount": _exact(line.final_amount),
        } for line in lines],
        "rewards": [{
            "product_variant_id": reward.product_variant_id,
            "base_quantity": _exact(reward.base_quantity),
        } for reward in rewards],
    }


def invoice_from_calculation(calculation, *, status="COMMITTED"):
    return invoice_payload(
        totals=calculation.totals, currency=calculation.transaction_currency_code,
        rounding=calculation.rounding_policy, lines=calculation.lines,
        rewards=calculation.rewards, status=status, calculated_at=calculation.calculated_at,
    )


async def preview_invoice(db, *, context, driver_id, visit_id, request):
    visit, shop, work = await assigned_visit(
        db, context=context, driver_id=driver_id, visit_id=visit_id,
    )
    state = await shop_commercial_state(db, company_id=context.company_id, shop=shop)
    if not state["sale_ready"]:
        raise FieldContractError(
            state["code"], "Complete the shop tax setup before a sale.",
            context={"required_action": state["required_action"]},
        )
    ids = [item.product_variant_id for item in request.cart_items]
    if len(ids) != len(set(ids)):
        raise FieldContractError("FIELD_INVOICE_DUPLICATE_PRODUCT", "Combine repeated product lines.", status_code=422)
    inputs = tuple(DriverSaleInput(
        product_variant_id=item.product_variant_id,
        carton_quantity=item.quantity, pack_quantity=item.packs_quantity,
    ) for item in request.cart_items if item.quantity or item.packs_quantity)
    if not inputs:
        raise FieldContractError("FIELD_INVOICE_SALE_REQUIRED", "Preview requires sold quantity.", status_code=422)
    locked = await require_route_commercial_context(
        db, company_id=context.company_id, dispatch_route_id=work.route.id,
    )
    if work.session.commercial_context_id != locked.id:
        raise FieldContractError("COMMERCIAL_CONTEXT_LOCKED", "Session commercial context differs from the route.")
    resolved = await resolve_driver_sale(
        db, company_id=context.company_id, dispatch_route_id=work.route.id,
        expected_commercial_context_id=locked.id,
        customer_id=shop.id, jurisdiction_id=shop.tax_jurisdiction_id, inputs=inputs,
    )
    final = resolved.calculation.totals.final_amount
    if final != final.quantize(Decimal("0.001")):
        raise FieldContractError(
            "DRIVER_LEDGER_PRECISION_UNSUPPORTED", "Invoice exceeds the field ledger precision.",
        )
    # A quote is not a stock reservation or credit approval. Commit re-runs the
    # existing visit engine and remains the acceptance authority.
    return {"invoice": invoice_from_calculation(resolved.calculation, status="PREVIEW"),
            "commit_required": True}


async def read_invoice(db, *, context, driver_id, visit_id):
    visit, _shop = await owned_visit(db, context=context, driver_id=driver_id, visit_id=visit_id)
    if visit.outcome != "Sale" or visit.status != "Completed":
        return {"invoice": None}
    if visit.current_sales_revision_id is None:
        raise FieldContractError("FIELD_INVOICE_EVIDENCE_UNAVAILABLE", "No frozen invoice evidence is available.")
    revision = (await db.execute(select(SalesVisitRevision).where(
        SalesVisitRevision.company_id == context.company_id,
        SalesVisitRevision.visit_id == visit.id,
        SalesVisitRevision.id == visit.current_sales_revision_id,
        SalesVisitRevision.frozen_at.is_not(None),
    ))).scalar_one_or_none()
    if revision is None:
        raise FieldContractError("FIELD_INVOICE_EVIDENCE_UNAVAILABLE", "No frozen invoice evidence is available.")
    items = (await db.execute(select(VisitItem).where(
        VisitItem.company_id == context.company_id, VisitItem.visit_id == visit.id,
        VisitItem.sales_revision_id == revision.id,
    ).order_by(VisitItem.id).limit(501))).scalars().all()
    rewards = (await db.execute(select(SalesRewardEvidence).where(
        SalesRewardEvidence.company_id == context.company_id,
        SalesRewardEvidence.visit_id == visit.id,
        SalesRewardEvidence.sales_revision_id == revision.id,
    ).order_by(SalesRewardEvidence.sequence).limit(501))).scalars().all()
    if len(items) > 500 or len(rewards) > 500:
        raise FieldContractError("FIELD_INVOICE_TOO_LARGE", "Invoice evidence exceeds the bounded field read.")
    lines = [SimpleNamespace(
        product_variant_id=item.product_variant_id, gross_amount=item.gross_amount,
        discount_amount=item.discount_amount, tax_amount=item.tax_amount, final_amount=item.net_amount,
    ) for item in items]
    invoice = invoice_payload(
        totals=revision, currency=revision.transaction_currency_code,
        rounding=SimpleNamespace(precision=revision.rounding_precision, mode=revision.rounding_mode),
        lines=lines, rewards=rewards, status="COMMITTED",
        calculated_at=revision.commercial_calculated_at,
    )
    invoice["revision_number"] = revision.revision_number
    return {"invoice": invoice}
