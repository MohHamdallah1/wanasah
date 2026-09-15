from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ProductVariant,
    Shop,
    SystemAuditLog,
    UOM,
    Visit,
    VisitItem,
)
from domains.sales_evidence.models import (
    SalesLineAdjustment,
    SalesLinePriceComponent,
    SalesLineTaxComponent,
    SalesVisitRevision,
)
from domains.sales_returns.core import SalesReturnError
from domains.sales_returns.models import (
    SalesReturnAdjustment,
    SalesReturnDocument,
    SalesReturnLine,
    SalesReturnQuantityComponent,
    SalesReturnTaxComponent,
)
from domains.sales_returns.schemas import SalesReturnCreate
from domains.uom_authority import UomAuthorityError, load_variant_uom_authorities


MONEY_QUANT = Decimal("0.000001")
MONEY_MAX = Decimal("99999999999999.999999")


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value) -> Decimal:
    try:
        result = _d(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SalesReturnError(
            "SALES_RETURN_MONEY_INVALID",
            "Return amount cannot be represented as NUMERIC(20,6).",
            status_code=422,
        ) from exc
    if not result.is_finite() or abs(result) > MONEY_MAX:
        raise SalesReturnError(
            "SALES_RETURN_MONEY_INVALID",
            "Return amount exceeds NUMERIC(20,6) capacity.",
            status_code=422,
        )
    return result


def _target_amount(original, cumulative_numerator, denominator) -> Decimal:
    original = _d(original)
    cumulative_numerator = _d(cumulative_numerator)
    denominator = _d(denominator)
    if denominator <= 0:
        return Decimal("0.000000")
    if cumulative_numerator < 0 or cumulative_numerator > denominator:
        raise SalesReturnError(
            "SALES_RETURN_ALLOCATION_INVALID",
            "Cumulative return allocation is outside the original evidence.",
        )
    if cumulative_numerator == denominator:
        return money(original)
    return money(original * cumulative_numerator / denominator)


def _currency_round(value, precision: int, mode: str) -> Decimal:
    if precision < 0 or precision > 6:
        raise SalesReturnError(
            "SALES_RETURN_ROUNDING_INVALID",
            "Original sale rounding precision is invalid.",
        )
    quant = Decimal("1").scaleb(-precision)
    rounding = {
        "HALF_UP": ROUND_HALF_UP,
        "HALF_EVEN": ROUND_HALF_EVEN,
    }.get(str(mode))
    if rounding is None:
        raise SalesReturnError(
            "SALES_RETURN_ROUNDING_INVALID",
            "Original sale rounding mode is invalid.",
        )
    try:
        return _d(value).quantize(quant, rounding=rounding)
    except InvalidOperation as exc:
        raise SalesReturnError(
            "SALES_RETURN_ROUNDING_INVALID",
            "Return credit cannot be rounded using the original sale policy.",
        ) from exc


def cumulative_delta(
    *,
    original_amount: Decimal,
    source_quantity: Decimal,
    prior_returned_quantity: Decimal,
    requested_quantity: Decimal,
    prior_reversed_amount: Decimal,
) -> Decimal:
    new_quantity = _d(prior_returned_quantity) + _d(requested_quantity)
    target = _target_amount(original_amount, new_quantity, source_quantity)
    delta = money(target - _d(prior_reversed_amount))
    if delta < 0:
        raise SalesReturnError(
            "SALES_RETURN_HISTORY_INVALID",
            "Existing return evidence exceeds the cumulative target.",
        )
    return delta


def _request_hash(payload: SalesReturnCreate) -> str:
    canonical = {
        "original_sales_revision_id": int(payload.original_sales_revision_id),
        "reason": payload.reason,
        "components": sorted(
            [
                {
                    "original_price_component_id": int(row.original_price_component_id),
                    "quantity": format(row.quantity, "f"),
                }
                for row in payload.components
            ],
            key=lambda row: row["original_price_component_id"],
        ),
    }
    return hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


async def _source_visit_revision(
    db: AsyncSession,
    *,
    company_id: int,
    revision_id: int,
    lock: bool,
):
    visit_stmt = (
        select(Visit)
        .join(
            SalesVisitRevision,
            (SalesVisitRevision.company_id == Visit.company_id)
            & (SalesVisitRevision.visit_id == Visit.id)
            & (SalesVisitRevision.id == int(revision_id)),
        )
        .where(
            Visit.company_id == int(company_id),
            Visit.current_sales_revision_id == int(revision_id),
            Visit.status == "Completed",
            Visit.outcome == "Sale",
        )
    )
    if lock:
        visit_stmt = visit_stmt.with_for_update(of=Visit)

    visit = (await db.execute(visit_stmt)).scalar_one_or_none()
    if visit is None:
        raise SalesReturnError(
            "SALES_RETURN_SOURCE_NOT_CURRENT",
            "The selected sale revision is not the current completed sale.",
            status_code=409,
        )

    revision_stmt = select(SalesVisitRevision).where(
        SalesVisitRevision.company_id == int(company_id),
        SalesVisitRevision.id == int(revision_id),
        SalesVisitRevision.visit_id == int(visit.id),
    )
    if lock:
        revision_stmt = revision_stmt.with_for_update()
    revision = (await db.execute(revision_stmt)).scalar_one_or_none()
    if revision is None or revision.frozen_at is None:
        raise SalesReturnError(
            "SALES_RETURN_SOURCE_NOT_FROZEN",
            "The original sale revision is missing or not frozen.",
            status_code=409,
        )
    return visit, revision


async def source_summary(
    db: AsyncSession,
    *,
    company_id: int,
    visit_id: int,
) -> dict:
    visit = (
        await db.execute(
            select(Visit).where(
                Visit.company_id == int(company_id),
                Visit.id == int(visit_id),
                Visit.status == "Completed",
                Visit.outcome == "Sale",
                Visit.current_sales_revision_id.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if visit is None:
        raise SalesReturnError(
            "SALES_RETURN_SOURCE_NOT_FOUND",
            "No current completed sale exists for this visit.",
            status_code=404,
        )

    _visit, revision = await _source_visit_revision(
        db,
        company_id=company_id,
        revision_id=int(visit.current_sales_revision_id),
        lock=False,
    )

    rows = (
        await db.execute(
            select(
                VisitItem.id.label("visit_item_id"),
                VisitItem.product_variant_id,
                ProductVariant.variant_name.label("product_name"),
                VisitItem.net_amount,
                SalesLinePriceComponent.id.label("price_component_id"),
                SalesLinePriceComponent.uom_id,
                UOM.code.label("uom_code"),
                UOM.name.label("uom_name"),
                SalesLinePriceComponent.quantity,
                SalesLinePriceComponent.base_quantity,
                SalesLinePriceComponent.unit_price,
            )
            .join(
                SalesLinePriceComponent,
                (SalesLinePriceComponent.company_id == VisitItem.company_id)
                & (SalesLinePriceComponent.visit_item_id == VisitItem.id),
            )
            .join(
                ProductVariant,
                (ProductVariant.company_id == VisitItem.company_id)
                & (ProductVariant.id == VisitItem.product_variant_id),
            )
            .join(UOM, UOM.id == SalesLinePriceComponent.uom_id)
            .where(
                VisitItem.company_id == int(company_id),
                VisitItem.visit_id == int(visit.id),
                VisitItem.sales_revision_id == int(revision.id),
                VisitItem.is_cancelled.is_(False),
            )
            .order_by(VisitItem.id, SalesLinePriceComponent.sequence)
        )
    ).all()

    component_ids = [int(row.price_component_id) for row in rows]
    returned_map: dict[int, Decimal] = {}
    if component_ids:
        prior = (
            await db.execute(
                select(
                    SalesReturnQuantityComponent.original_price_component_id,
                    func.coalesce(func.sum(SalesReturnQuantityComponent.quantity), 0),
                )
                .join(
                    SalesReturnLine,
                    (SalesReturnLine.company_id == SalesReturnQuantityComponent.company_id)
                    & (SalesReturnLine.id == SalesReturnQuantityComponent.sales_return_line_id),
                )
                .join(
                    SalesReturnDocument,
                    (SalesReturnDocument.company_id == SalesReturnLine.company_id)
                    & (SalesReturnDocument.id == SalesReturnLine.sales_return_id),
                )
                .where(
                    SalesReturnDocument.company_id == int(company_id),
                    SalesReturnDocument.original_sales_revision_id == int(revision.id),
                    SalesReturnQuantityComponent.original_price_component_id.in_(component_ids),
                )
                .group_by(SalesReturnQuantityComponent.original_price_component_id)
            )
        ).all()
        returned_map = {
            int(component_id): _d(quantity)
            for component_id, quantity in prior
        }

    shop_name = (
        await db.execute(
            select(Shop.name).where(
                Shop.company_id == int(company_id),
                Shop.id == int(visit.shop_id),
            )
        )
    ).scalar_one()

    grouped: dict[int, dict] = {}
    for row in rows:
        item_id = int(row.visit_item_id)
        entry = grouped.setdefault(
            item_id,
            {
                "visit_item_id": item_id,
                "product_variant_id": int(row.product_variant_id),
                "product_name": str(row.product_name),
                "net_amount": format(_d(row.net_amount or 0), "f"),
                "components": [],
            },
        )
        returned = returned_map.get(int(row.price_component_id), Decimal("0"))
        available = _d(row.quantity) - returned
        if available < 0:
            raise SalesReturnError(
                "SALES_RETURN_HISTORY_INVALID",
                "Existing return quantities exceed the original sale evidence.",
            )
        entry["components"].append(
            {
                "price_component_id": int(row.price_component_id),
                "uom_id": int(row.uom_id),
                "uom_code": str(row.uom_code),
                "uom_name": str(row.uom_name),
                "sold_quantity": format(_d(row.quantity), "f"),
                "returned_quantity": format(returned, "f"),
                "available_quantity": format(available, "f"),
                "unit_price": format(_d(row.unit_price), "f"),
            }
        )

    return {
        "visit_id": int(visit.id),
        "sales_revision_id": int(revision.id),
        "shop": {"id": int(visit.shop_id), "name": str(shop_name)},
        "transaction_currency_code": str(revision.transaction_currency_code),
        "final_amount": format(_d(revision.final_amount), "f"),
        "lines": list(grouped.values()),
    }


async def create_sales_return(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    payload: SalesReturnCreate,
) -> dict:
    # Tenant + request scoped advisory lock is the first mutation lock.  It
    # makes idempotency deterministic even when the same request_id is raced
    # against different source invoices.
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                int(company_id),
                func.hashtext(str(payload.request_id)),
            )
        )
    )

    request_hash = _request_hash(payload)
    existing = (
        await db.execute(
            select(SalesReturnDocument).where(
                SalesReturnDocument.company_id == int(company_id),
                SalesReturnDocument.request_id == payload.request_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SalesReturnError(
                "SALES_RETURN_REQUEST_REUSED",
                "request_id was already used with different return data.",
                status_code=409,
            )
        return await get_sales_return(
            db,
            company_id=company_id,
            return_id=int(existing.id),
        )

    visit, revision = await _source_visit_revision(
        db,
        company_id=company_id,
        revision_id=payload.original_sales_revision_id,
        lock=True,
    )

    # Re-check idempotency after serializing on the original sale.  This closes
    # the race where two identical requests arrive before either one commits.
    existing = (
        await db.execute(
            select(SalesReturnDocument).where(
                SalesReturnDocument.company_id == int(company_id),
                SalesReturnDocument.request_id == payload.request_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SalesReturnError(
                "SALES_RETURN_REQUEST_REUSED",
                "request_id was already used with different return data.",
                status_code=409,
            )
        return await get_sales_return(
            db,
            company_id=company_id,
            return_id=int(existing.id),
        )

    requested = {
        int(row.original_price_component_id): _d(row.quantity)
        for row in payload.components
    }
    component_rows = (
        await db.execute(
            select(SalesLinePriceComponent)
            .where(
                SalesLinePriceComponent.company_id == int(company_id),
                SalesLinePriceComponent.id.in_(sorted(requested)),
            )
            .order_by(SalesLinePriceComponent.id)
        )
    ).scalars().all()
    components = {int(row.id): row for row in component_rows}
    if set(components) != set(requested):
        raise SalesReturnError(
            "SALES_RETURN_SOURCE_COMPONENT_INVALID",
            "One or more original price components do not exist in this company.",
            status_code=404,
        )

    item_ids = sorted({int(row.visit_item_id) for row in component_rows})
    item_rows = (
        await db.execute(
            select(VisitItem)
            .where(
                VisitItem.company_id == int(company_id),
                VisitItem.id.in_(item_ids),
                VisitItem.visit_id == int(visit.id),
                VisitItem.sales_revision_id == int(revision.id),
                VisitItem.financial_evidence_version == 4,
                VisitItem.is_cancelled.is_(False),
            )
            .order_by(VisitItem.id)
        )
    ).scalars().all()
    items = {int(row.id): row for row in item_rows}
    if set(items) != set(item_ids):
        raise SalesReturnError(
            "SALES_RETURN_SOURCE_LINE_INVALID",
            "A selected component does not belong to the current frozen sale revision.",
        )

    try:
        uom_authorities = await load_variant_uom_authorities(
            db,
            company_id=int(company_id),
            variant_ids={
                int(item.product_variant_id)
                for item in item_rows
            },
        )
        for component in component_rows:
            item = items[int(component.visit_item_id)]
            converted = uom_authorities[
                int(item.product_variant_id)
            ].to_base(
                requested[int(component.id)],
                uom_id=int(component.uom_id),
                field_name=f"return_quantity[{int(component.id)}]",
                validate_step=True,
            )
            if converted <= 0:
                raise SalesReturnError(
                    "SALES_RETURN_QUANTITY_INVALID",
                    "Returned quantity must be positive.",
                    status_code=422,
                )
    except UomAuthorityError as exc:
        raise SalesReturnError(
            exc.code,
            exc.message,
            status_code=422,
            context=exc.context,
        ) from exc

    prior_quantity_rows = (
        await db.execute(
            select(
                SalesReturnQuantityComponent.original_price_component_id,
                func.coalesce(func.sum(SalesReturnQuantityComponent.quantity), 0),
                func.coalesce(func.sum(SalesReturnQuantityComponent.base_quantity), 0),
                func.coalesce(func.sum(SalesReturnQuantityComponent.gross_reversal), 0),
            )
            .join(
                SalesReturnLine,
                (SalesReturnLine.company_id == SalesReturnQuantityComponent.company_id)
                & (SalesReturnLine.id == SalesReturnQuantityComponent.sales_return_line_id),
            )
            .join(
                SalesReturnDocument,
                (SalesReturnDocument.company_id == SalesReturnLine.company_id)
                & (SalesReturnDocument.id == SalesReturnLine.sales_return_id),
            )
            .where(
                SalesReturnDocument.company_id == int(company_id),
                SalesReturnDocument.original_sales_revision_id == int(revision.id),
                SalesReturnQuantityComponent.original_price_component_id.in_(sorted(requested)),
            )
            .group_by(SalesReturnQuantityComponent.original_price_component_id)
        )
    ).all()
    prior_quantity = {
        int(cid): (_d(qty), _d(base_qty), _d(gross))
        for cid, qty, base_qty, gross in prior_quantity_rows
    }

    by_item: dict[int, list[SalesLinePriceComponent]] = {}
    quantity_results: dict[int, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
    for component in component_rows:
        cid = int(component.id)
        source_qty = _d(component.quantity)
        requested_qty = requested[cid]
        prior_qty, prior_base, prior_gross = prior_quantity.get(
            cid,
            (Decimal("0"), Decimal("0"), Decimal("0")),
        )
        new_qty = prior_qty + requested_qty
        if new_qty > source_qty:
            raise SalesReturnError(
                "SALES_RETURN_QUANTITY_EXCEEDED",
                "Returned quantity exceeds the remaining quantity on the original sale component.",
                context={
                    "original_price_component_id": cid,
                    "sold_quantity": format(source_qty, "f"),
                    "already_returned": format(prior_qty, "f"),
                    "requested": format(requested_qty, "f"),
                },
            )
        target_base = _target_amount(component.base_quantity, new_qty, source_qty)
        base_delta = money(target_base - prior_base)
        gross_delta = cumulative_delta(
            original_amount=_d(component.gross_amount),
            source_quantity=source_qty,
            prior_returned_quantity=prior_qty,
            requested_quantity=requested_qty,
            prior_reversed_amount=prior_gross,
        )
        quantity_results[cid] = (
            requested_qty,
            base_delta,
            gross_delta,
            new_qty,
        )
        by_item.setdefault(int(component.visit_item_id), []).append(component)

    all_adjustments = (
        await db.execute(
            select(SalesLineAdjustment)
            .where(
                SalesLineAdjustment.company_id == int(company_id),
                SalesLineAdjustment.visit_item_id.in_(item_ids),
            )
            .order_by(SalesLineAdjustment.visit_item_id, SalesLineAdjustment.sequence)
        )
    ).scalars().all()
    all_taxes = (
        await db.execute(
            select(SalesLineTaxComponent)
            .where(
                SalesLineTaxComponent.company_id == int(company_id),
                SalesLineTaxComponent.visit_item_id.in_(item_ids),
            )
            .order_by(SalesLineTaxComponent.visit_item_id, SalesLineTaxComponent.sequence)
        )
    ).scalars().all()

    adjustment_ids = [int(row.id) for row in all_adjustments]
    prior_adjustments: dict[int, Decimal] = {}
    if adjustment_ids:
        prior_adjustments = {
            int(aid): _d(amount)
            for aid, amount in (
                await db.execute(
                    select(
                        SalesReturnAdjustment.original_adjustment_id,
                        func.coalesce(func.sum(SalesReturnAdjustment.adjustment_reversal), 0),
                    )
                    .join(
                        SalesReturnLine,
                        (SalesReturnLine.company_id == SalesReturnAdjustment.company_id)
                        & (SalesReturnLine.id == SalesReturnAdjustment.sales_return_line_id),
                    )
                    .join(
                        SalesReturnDocument,
                        (SalesReturnDocument.company_id == SalesReturnLine.company_id)
                        & (SalesReturnDocument.id == SalesReturnLine.sales_return_id),
                    )
                    .where(
                        SalesReturnDocument.company_id == int(company_id),
                        SalesReturnDocument.original_sales_revision_id == int(revision.id),
                        SalesReturnAdjustment.original_adjustment_id.in_(adjustment_ids),
                    )
                    .group_by(SalesReturnAdjustment.original_adjustment_id)
                )
            ).all()
        }

    tax_ids = [int(row.id) for row in all_taxes]
    prior_taxes: dict[int, tuple[Decimal, Decimal]] = {}
    if tax_ids:
        prior_taxes = {
            int(tid): (_d(taxable), _d(tax))
            for tid, taxable, tax in (
                await db.execute(
                    select(
                        SalesReturnTaxComponent.original_tax_component_id,
                        func.coalesce(func.sum(SalesReturnTaxComponent.taxable_reversal), 0),
                        func.coalesce(func.sum(SalesReturnTaxComponent.tax_reversal), 0),
                    )
                    .join(
                        SalesReturnLine,
                        (SalesReturnLine.company_id == SalesReturnTaxComponent.company_id)
                        & (SalesReturnLine.id == SalesReturnTaxComponent.sales_return_line_id),
                    )
                    .join(
                        SalesReturnDocument,
                        (SalesReturnDocument.company_id == SalesReturnLine.company_id)
                        & (SalesReturnDocument.id == SalesReturnLine.sales_return_id),
                    )
                    .where(
                        SalesReturnDocument.company_id == int(company_id),
                        SalesReturnDocument.original_sales_revision_id == int(revision.id),
                        SalesReturnTaxComponent.original_tax_component_id.in_(tax_ids),
                    )
                    .group_by(SalesReturnTaxComponent.original_tax_component_id)
                )
            ).all()
        }

    prior_line_rows = (
        await db.execute(
            select(
                SalesReturnLine.original_visit_item_id,
                func.coalesce(func.sum(SalesReturnLine.post_offer_reversal), 0),
                func.coalesce(func.sum(SalesReturnLine.taxable_reversal), 0),
                func.coalesce(func.sum(SalesReturnLine.credit_amount), 0),
            )
            .join(
                SalesReturnDocument,
                (SalesReturnDocument.company_id == SalesReturnLine.company_id)
                & (SalesReturnDocument.id == SalesReturnLine.sales_return_id),
            )
            .where(
                SalesReturnDocument.company_id == int(company_id),
                SalesReturnDocument.original_sales_revision_id == int(revision.id),
                SalesReturnLine.original_visit_item_id.in_(item_ids),
            )
            .group_by(SalesReturnLine.original_visit_item_id)
        )
    ).all()
    prior_lines = {
        int(item_id): (_d(post_offer), _d(taxable), _d(credit))
        for item_id, post_offer, taxable, credit in prior_line_rows
    }

    adjustments_by_item: dict[int, list[SalesLineAdjustment]] = {}
    for row in all_adjustments:
        adjustments_by_item.setdefault(int(row.visit_item_id), []).append(row)
    taxes_by_item: dict[int, list[SalesLineTaxComponent]] = {}
    for row in all_taxes:
        taxes_by_item.setdefault(int(row.visit_item_id), []).append(row)

    prepared_lines: list[dict] = []
    current_line_credit_total = Decimal("0")
    for item_id in sorted(by_item):
        item = items[item_id]
        source_components = by_item[item_id]
        source_by_uom = {int(row.uom_id): row for row in source_components}

        gross_current = sum(
            (quantity_results[int(row.id)][2] for row in source_components),
            Decimal("0"),
        )
        base_current = sum(
            (quantity_results[int(row.id)][1] for row in source_components),
            Decimal("0"),
        )

        adjustment_results: list[tuple[SalesLineAdjustment, Decimal]] = []
        discount_current = Decimal("0")
        for adjustment in adjustments_by_item.get(item_id, []):
            source_component = source_by_uom.get(int(adjustment.uom_id))
            if source_component is None:
                continue
            cid = int(source_component.id)
            req_qty, _base, _gross, new_qty = quantity_results[cid]
            prior_qty = new_qty - req_qty
            prior_amount = prior_adjustments.get(int(adjustment.id), Decimal("0"))
            delta = cumulative_delta(
                original_amount=_d(adjustment.adjustment_amount),
                source_quantity=_d(source_component.quantity),
                prior_returned_quantity=prior_qty,
                requested_quantity=req_qty,
                prior_reversed_amount=prior_amount,
            )
            if delta > 0:
                adjustment_results.append((adjustment, delta))
                discount_current += delta

        gross_current = money(gross_current)
        discount_current = money(discount_current)
        post_offer_current = money(gross_current - discount_current)
        if post_offer_current < 0:
            raise SalesReturnError(
                "SALES_RETURN_RECONCILIATION_INVALID",
                "Return discount exceeds returned gross amount.",
            )

        prior_post_offer, prior_taxable, prior_credit = prior_lines.get(
            item_id,
            (Decimal("0"), Decimal("0"), Decimal("0")),
        )
        original_post_offer = _d(item.post_offer_amount or 0)
        cumulative_post_offer = prior_post_offer + post_offer_current
        if cumulative_post_offer > original_post_offer:
            raise SalesReturnError(
                "SALES_RETURN_RECONCILIATION_INVALID",
                "Return post-offer amount exceeds original line evidence.",
            )

        if original_post_offer > 0:
            taxable_target = _target_amount(
                _d(item.taxable_amount or 0),
                cumulative_post_offer,
                original_post_offer,
            )
            taxable_current = money(taxable_target - prior_taxable)
        else:
            taxable_current = Decimal("0.000000")

        tax_results: list[tuple[SalesLineTaxComponent, Decimal, Decimal]] = []
        tax_current = Decimal("0")
        for tax_component in taxes_by_item.get(item_id, []):
            prior_taxable_component, prior_tax_component = prior_taxes.get(
                int(tax_component.id),
                (Decimal("0"), Decimal("0")),
            )
            if original_post_offer > 0:
                target_taxable_component = _target_amount(
                    _d(tax_component.taxable_amount),
                    cumulative_post_offer,
                    original_post_offer,
                )
                target_tax_component = _target_amount(
                    _d(tax_component.tax_amount),
                    cumulative_post_offer,
                    original_post_offer,
                )
                taxable_delta = money(
                    target_taxable_component - prior_taxable_component
                )
                tax_delta = money(target_tax_component - prior_tax_component)
            else:
                taxable_delta = Decimal("0.000000")
                tax_delta = Decimal("0.000000")
            if taxable_delta < 0 or tax_delta < 0:
                raise SalesReturnError(
                    "SALES_RETURN_HISTORY_INVALID",
                    "Prior tax reversal evidence exceeds its cumulative target.",
                )
            tax_results.append((tax_component, taxable_delta, tax_delta))
            tax_current += tax_delta

        tax_current = money(tax_current)
        line_total_current = money(taxable_current + tax_current)

        if original_post_offer > 0:
            credit_target = _currency_round(
                _d(item.net_amount or 0) * cumulative_post_offer / original_post_offer,
                int(revision.rounding_precision),
                str(revision.rounding_mode),
            )
            credit_current = money(credit_target - prior_credit)
        else:
            credit_current = Decimal("0.000000")
        if credit_current < 0:
            raise SalesReturnError(
                "SALES_RETURN_HISTORY_INVALID",
                "Prior credit evidence exceeds the cumulative target.",
            )

        prepared_lines.append(
            {
                "item_id": item_id,
                "item": item,
                "source_components": source_components,
                "base_current": money(base_current),
                "gross_current": gross_current,
                "discount_current": discount_current,
                "post_offer_current": post_offer_current,
                "taxable_current": taxable_current,
                "tax_current": tax_current,
                "line_total_current": line_total_current,
                "credit_current": credit_current,
                "original_post_offer": original_post_offer,
                "adjustment_results": adjustment_results,
                "tax_results": tax_results,
            }
        )
        current_line_credit_total += credit_current

    prior_line_credit_total = _d(
        (
            await db.execute(
                select(func.coalesce(func.sum(SalesReturnLine.credit_amount), 0))
                .join(
                    SalesReturnDocument,
                    (SalesReturnDocument.company_id == SalesReturnLine.company_id)
                    & (SalesReturnDocument.id == SalesReturnLine.sales_return_id),
                )
                .where(
                    SalesReturnDocument.company_id == int(company_id),
                    SalesReturnDocument.original_sales_revision_id == int(revision.id),
                )
            )
        ).scalar_one()
    )
    prior_rounding = _d(
        (
            await db.execute(
                select(func.coalesce(func.sum(SalesReturnDocument.rounding_reversal), 0))
                .where(
                    SalesReturnDocument.company_id == int(company_id),
                    SalesReturnDocument.original_sales_revision_id == int(revision.id),
                )
            )
        ).scalar_one()
    )

    cumulative_line_credit = prior_line_credit_total + current_line_credit_total
    original_line_total = _d(revision.line_total_amount)
    if original_line_total > 0:
        rounding_target = _target_amount(
            _d(revision.rounding_adjustment),
            cumulative_line_credit,
            original_line_total,
        )
        rounding_current = money(rounding_target - prior_rounding)
    else:
        rounding_current = Decimal("0.000000")

    document_credit = money(current_line_credit_total + rounding_current)
    if document_credit < 0:
        raise SalesReturnError(
            "SALES_RETURN_CREDIT_INVALID",
            "Calculated return credit cannot be negative.",
        )

    # The posted Credit Note is immutable from its first INSERT.  Settlement is
    # intentionally external to this evidence document and will be represented
    # by a future settlement ledger, not by mutating the return.
    document = SalesReturnDocument(
        company_id=int(company_id),
        request_id=payload.request_id,
        request_hash=request_hash,
        original_visit_id=int(visit.id),
        original_sales_revision_id=int(revision.id),
        shop_id=int(visit.shop_id),
        created_by=int(actor_id),
        reason=payload.reason,
        status="POSTED",
        transaction_currency_code=str(revision.transaction_currency_code).upper(),
        functional_currency_code=str(revision.functional_currency_code).upper(),
        rounding_reversal=rounding_current,
        credit_amount=document_credit,
        evidence_schema_version=1,
    )
    db.add(document)
    await db.flush()

    for prepared in prepared_lines:
        item_id = int(prepared["item_id"])
        item = prepared["item"]
        source_components = prepared["source_components"]

        line = SalesReturnLine(
            company_id=int(company_id),
            sales_return_id=int(document.id),
            original_visit_item_id=item_id,
            product_variant_id=int(item.product_variant_id),
            returned_base_quantity=prepared["base_current"],
            gross_reversal=prepared["gross_current"],
            discount_reversal=prepared["discount_current"],
            post_offer_reversal=prepared["post_offer_current"],
            taxable_reversal=prepared["taxable_current"],
            tax_reversal=prepared["tax_current"],
            line_total_reversal=prepared["line_total_current"],
            credit_amount=prepared["credit_current"],
            evidence_snapshot={
                "schema_version": 1,
                "original_sales_revision_id": int(revision.id),
                "original_visit_item_id": item_id,
                "commercial_context_id": int(revision.commercial_context_id),
                "commercial_calculated_at": revision.commercial_calculated_at.isoformat(),
                "transaction_currency_code": str(revision.transaction_currency_code),
                "functional_currency_code": str(revision.functional_currency_code),
                "original": {
                    "gross_amount": format(_d(item.gross_amount or 0), "f"),
                    "discount_amount": format(_d(item.discount_amount or 0), "f"),
                    "post_offer_amount": format(prepared["original_post_offer"], "f"),
                    "taxable_amount": format(_d(item.taxable_amount or 0), "f"),
                    "tax_amount": format(_d(item.tax_amount or 0), "f"),
                    "net_amount": format(_d(item.net_amount or 0), "f"),
                    "offer_snapshot": item.offer_snapshot,
                    "tax_snapshot": item.tax_snapshot,
                },
            },
        )
        db.add(line)
        await db.flush()

        for source_component in source_components:
            cid = int(source_component.id)
            req_qty, base_delta, gross_delta, _new_qty = quantity_results[cid]
            db.add(
                SalesReturnQuantityComponent(
                    company_id=int(company_id),
                    sales_return_line_id=int(line.id),
                    original_price_component_id=cid,
                    uom_id=int(source_component.uom_id),
                    quantity=req_qty,
                    base_quantity=base_delta,
                    gross_reversal=gross_delta,
                    evidence_snapshot={
                        "schema_version": 1,
                        "price_entry_id": int(source_component.price_entry_id),
                        "price_publication_revision": int(
                            source_component.price_publication_revision
                        ),
                        "assignment_revision": int(source_component.assignment_revision),
                        "unit_price": format(_d(source_component.unit_price), "f"),
                        "original_quantity": format(_d(source_component.quantity), "f"),
                        "original_base_quantity": format(
                            _d(source_component.base_quantity), "f"
                        ),
                        "original_gross_amount": format(
                            _d(source_component.gross_amount), "f"
                        ),
                    },
                )
            )

        for adjustment, delta in prepared["adjustment_results"]:
            db.add(
                SalesReturnAdjustment(
                    company_id=int(company_id),
                    sales_return_line_id=int(line.id),
                    original_adjustment_id=int(adjustment.id),
                    uom_id=int(adjustment.uom_id),
                    adjustment_reversal=delta,
                    evidence_snapshot={
                        "schema_version": 1,
                        "offer_version_id": int(adjustment.offer_version_id),
                        "rule_id": int(adjustment.rule_id),
                        "rule_version": int(adjustment.rule_version),
                        "rule_type": str(adjustment.rule_type),
                        "source_metadata": dict(adjustment.metadata_snapshot or {}),
                    },
                )
            )

        for tax_component, taxable_delta, tax_delta in prepared["tax_results"]:
            db.add(
                SalesReturnTaxComponent(
                    company_id=int(company_id),
                    sales_return_line_id=int(line.id),
                    original_tax_component_id=int(tax_component.id),
                    taxable_reversal=taxable_delta,
                    tax_reversal=tax_delta,
                    evidence_snapshot={
                        "schema_version": 1,
                        "tax_rule_set_id": int(tax_component.tax_rule_set_id),
                        "tax_rule_set_version_id": int(
                            tax_component.tax_rule_set_version_id
                        ),
                        "tax_revision": int(tax_component.tax_revision),
                        "tax_component_id": int(tax_component.tax_component_id),
                        "component_code": str(tax_component.component_code),
                        "name": str(tax_component.tax_name),
                        "rate": format(_d(tax_component.rate), "f"),
                        "basis_mode": str(tax_component.basis_mode),
                        "reporting_code": tax_component.reporting_code,
                        "matched_jurisdiction_id": tax_component.matched_jurisdiction_id,
                        "jurisdiction_distance": tax_component.jurisdiction_distance,
                        "source_metadata": dict(tax_component.metadata_snapshot or {}),
                    },
                )
            )

    db.add(
        SystemAuditLog(
            company_id=int(company_id),
            admin_id=int(actor_id),
            target_id=f"SalesReturn_{int(document.id)}",
            action_type="SALES_RETURN_POSTED",
            old_value=json.dumps(
                {
                    "original_visit_id": int(visit.id),
                    "original_sales_revision_id": int(revision.id),
                    "original_final_amount": format(_d(revision.final_amount), "f"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            new_value=json.dumps(
                {
                    "request_id": str(payload.request_id),
                    "credit_amount": format(document.credit_amount, "f"),
                    "settlement_status": "UNSETTLED",
                    "reason": payload.reason,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    )

    await db.flush()
    return await get_sales_return(
        db,
        company_id=company_id,
        return_id=int(document.id),
    )


async def list_sales_returns(
    db: AsyncSession,
    *,
    company_id: int,
    limit: int = 50,
    before_id: int | None = None,
) -> dict:
    safe_limit = max(1, min(int(limit), 100))
    stmt = (
        select(
            SalesReturnDocument,
            Shop.name.label("shop_name"),
        )
        .join(
            Shop,
            (Shop.company_id == SalesReturnDocument.company_id)
            & (Shop.id == SalesReturnDocument.shop_id),
        )
        .where(SalesReturnDocument.company_id == int(company_id))
        .order_by(SalesReturnDocument.id.desc())
        .limit(safe_limit + 1)
    )
    if before_id is not None:
        stmt = stmt.where(SalesReturnDocument.id < int(before_id))

    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > safe_limit
    rows = rows[:safe_limit]
    items = [
        {
            "id": int(doc.id),
            "original_visit_id": int(doc.original_visit_id),
            "original_sales_revision_id": int(doc.original_sales_revision_id),
            "shop_id": int(doc.shop_id),
            "shop_name": str(shop_name),
            "transaction_currency_code": str(doc.transaction_currency_code),
            "credit_amount": format(_d(doc.credit_amount), "f"),
            "settlement_status": "UNSETTLED",
            "reason": str(doc.reason),
            "posted_at": doc.posted_at.isoformat(),
        }
        for doc, shop_name in rows
    ]
    return {
        "items": items,
        "has_more": has_more,
        "next_cursor": str(items[-1]["id"]) if has_more and items else None,
    }


async def get_sales_return(
    db: AsyncSession,
    *,
    company_id: int,
    return_id: int,
) -> dict:
    row = (
        await db.execute(
            select(
                SalesReturnDocument,
                Shop.name.label("shop_name"),
            )
            .join(
                Shop,
                (Shop.company_id == SalesReturnDocument.company_id)
                & (Shop.id == SalesReturnDocument.shop_id),
            )
            .where(
                SalesReturnDocument.company_id == int(company_id),
                SalesReturnDocument.id == int(return_id),
            )
        )
    ).one_or_none()
    if row is None:
        raise SalesReturnError(
            "SALES_RETURN_NOT_FOUND",
            "Sales return was not found in this company.",
            status_code=404,
        )
    doc, shop_name = row

    lines = (
        await db.execute(
            select(
                SalesReturnLine,
                ProductVariant.variant_name.label("product_name"),
            )
            .join(
                ProductVariant,
                (ProductVariant.company_id == SalesReturnLine.company_id)
                & (ProductVariant.id == SalesReturnLine.product_variant_id),
            )
            .where(
                SalesReturnLine.company_id == int(company_id),
                SalesReturnLine.sales_return_id == int(return_id),
            )
            .order_by(SalesReturnLine.id)
        )
    ).all()

    line_ids = [int(line.id) for line, _name in lines]
    q_rows = []
    if line_ids:
        q_rows = (
            await db.execute(
                select(
                    SalesReturnQuantityComponent,
                    UOM.code.label("uom_code"),
                    UOM.name.label("uom_name"),
                )
                .join(UOM, UOM.id == SalesReturnQuantityComponent.uom_id)
                .where(
                    SalesReturnQuantityComponent.company_id == int(company_id),
                    SalesReturnQuantityComponent.sales_return_line_id.in_(line_ids),
                )
                .order_by(SalesReturnQuantityComponent.id)
            )
        ).all()
    q_map: dict[int, list[dict]] = {}
    for q, code, name in q_rows:
        q_map.setdefault(int(q.sales_return_line_id), []).append(
            {
                "original_price_component_id": int(q.original_price_component_id),
                "uom_id": int(q.uom_id),
                "uom_code": str(code),
                "uom_name": str(name),
                "quantity": format(_d(q.quantity), "f"),
                "base_quantity": format(_d(q.base_quantity), "f"),
                "gross_reversal": format(_d(q.gross_reversal), "f"),
            }
        )

    return {
        "id": int(doc.id),
        "original_visit_id": int(doc.original_visit_id),
        "original_sales_revision_id": int(doc.original_sales_revision_id),
        "shop": {"id": int(doc.shop_id), "name": str(shop_name)},
        "status": str(doc.status),
        "settlement_status": "UNSETTLED",
        "transaction_currency_code": str(doc.transaction_currency_code),
        "functional_currency_code": str(doc.functional_currency_code),
        "rounding_reversal": format(_d(doc.rounding_reversal), "f"),
        "credit_amount": format(_d(doc.credit_amount), "f"),
        "reason": str(doc.reason),
        "posted_at": doc.posted_at.isoformat(),
        "lines": [
            {
                "id": int(line.id),
                "original_visit_item_id": int(line.original_visit_item_id),
                "product_variant_id": int(line.product_variant_id),
                "product_name": str(product_name),
                "returned_base_quantity": format(_d(line.returned_base_quantity), "f"),
                "gross_reversal": format(_d(line.gross_reversal), "f"),
                "discount_reversal": format(_d(line.discount_reversal), "f"),
                "post_offer_reversal": format(_d(line.post_offer_reversal), "f"),
                "taxable_reversal": format(_d(line.taxable_reversal), "f"),
                "tax_reversal": format(_d(line.tax_reversal), "f"),
                "line_total_reversal": format(_d(line.line_total_reversal), "f"),
                "credit_amount": format(_d(line.credit_amount), "f"),
                "components": q_map.get(int(line.id), []),
            }
            for line, product_name in lines
        ],
    }
