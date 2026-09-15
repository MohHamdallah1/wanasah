from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import case, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Branch,
    PriceBook,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    Shop,
)

from .core import (
    PricingError,
    current_assignment_revision_ceiling,
    current_publication_revision_ceiling,
    require_aware_datetime,
    utc_now,
)


_SCOPE_RANK = {
    "CUSTOMER": 300,
    "CUSTOMER_GROUP": 250,
    "BRANCH": 200,
    "CHANNEL": 200,
    "COMPANY_DEFAULT": 100,
}


@dataclass(frozen=True)
class PriceResolution:
    price_book_id: int
    assignment_id: int
    assignment_revision: int
    assignment_scope_type: str
    assignment_priority: int
    price_entry_id: int
    price_publication_id: int
    price_publication_revision: int
    product_variant_id: int
    uom_id: int
    amount: Decimal
    currency_code: str
    resolved_at: datetime


async def _validate_context(
    db: AsyncSession,
    *,
    company_id: int,
    customer_id: Optional[int],
    branch_id: Optional[int],
) -> None:
    if customer_id is not None:
        exists = await db.scalar(
            select(Shop.id).where(
                Shop.company_id == int(company_id),
                Shop.id == int(customer_id),
            )
        )
        if exists is None:
            raise PricingError(
                "PRICE_CUSTOMER_NOT_FOUND",
                "العميل غير موجود داخل الشركة.",
                status_code=404,
            )
    if branch_id is not None:
        exists = await db.scalar(
            select(Branch.id).where(
                Branch.company_id == int(company_id),
                Branch.id == int(branch_id),
            )
        )
        if exists is None:
            raise PricingError(
                "PRICE_BRANCH_NOT_FOUND",
                "الفرع غير موجود داخل الشركة.",
                status_code=404,
            )


async def resolve_assignment(
    db: AsyncSession,
    *,
    company_id: int,
    as_of: datetime,
    customer_id: Optional[int],
    branch_id: Optional[int],
    assignment_revision_ceiling: int,
) -> PriceBookAssignment:
    await _validate_context(
        db,
        company_id=company_id,
        customer_id=customer_id,
        branch_id=branch_id,
    )
    predicates = [
        PriceBookAssignment.company_id == int(company_id),
        PriceBookAssignment.revision <= int(assignment_revision_ceiling),
        PriceBookAssignment.effectivity.contains(as_of),
    ]
    scope_predicates = [PriceBookAssignment.scope_type == "COMPANY_DEFAULT"]
    if customer_id is not None:
        scope_predicates.append(
            (
                PriceBookAssignment.scope_type == "CUSTOMER"
            )
            & (PriceBookAssignment.scope_id == int(customer_id))
        )
    if branch_id is not None:
        scope_predicates.append(
            (
                PriceBookAssignment.scope_type == "BRANCH"
            )
            & (PriceBookAssignment.scope_id == int(branch_id))
        )

    rank = case(
        (PriceBookAssignment.scope_type == "CUSTOMER", 300),
        (PriceBookAssignment.scope_type == "BRANCH", 200),
        (PriceBookAssignment.scope_type == "COMPANY_DEFAULT", 100),
        else_=0,
    )
    rows = list(
        (
            await db.scalars(
                select(PriceBookAssignment)
                .where(*predicates, or_(*scope_predicates))
                .order_by(
                    rank.desc(),
                    PriceBookAssignment.priority.desc(),
                    PriceBookAssignment.revision.desc(),
                    PriceBookAssignment.id.desc(),
                )
                .limit(2)
            )
        ).all()
    )
    if not rows:
        raise PricingError(
            "PRICE_NOT_RESOLVED",
            "لا يوجد PriceBook Assignment صالح للسياق المطلوب.",
            context={
                "customer_id": customer_id,
                "branch_id": branch_id,
                "assignment_revision_ceiling": int(
                    assignment_revision_ceiling
                ),
            },
        )

    top = rows[0]
    top_rank = _SCOPE_RANK.get(str(top.scope_type), 0)
    if len(rows) > 1:
        second = rows[1]
        second_rank = _SCOPE_RANK.get(str(second.scope_type), 0)
        if (
            second_rank == top_rank
            and int(second.priority) == int(top.priority)
        ):
            raise PricingError(
                "PRICE_ASSIGNMENT_TIE",
                "تعادل غير محسوم في أولوية PriceBook Assignment.",
                context={
                    "assignment_ids": [int(top.id), int(second.id)],
                    "scope_type": str(top.scope_type),
                    "priority": int(top.priority),
                },
            )
    return top


async def resolve_prices_bulk(
    db: AsyncSession,
    *,
    company_id: int,
    pairs: Sequence[tuple[int, int]],
    customer_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    as_of: Optional[datetime] = None,
    publication_revision_ceiling: Optional[int] = None,
    assignment_revision_ceiling: Optional[int] = None,
    allow_unresolved_pairs: bool = False,
) -> dict[tuple[int, int], PriceResolution]:
    if not pairs:
        return {}
    normalized_pairs = sorted(
        {(int(variant_id), int(uom_id)) for variant_id, uom_id in pairs}
    )
    if any(variant_id <= 0 or uom_id <= 0 for variant_id, uom_id in normalized_pairs):
        raise PricingError(
            "PRICE_RESOLVE_INPUT_INVALID",
            "معرفات SKU/UOM يجب أن تكون موجبة.",
            status_code=422,
        )
    when = require_aware_datetime(as_of or utc_now(), "as_of")
    pub_ceiling = (
        int(publication_revision_ceiling)
        if publication_revision_ceiling is not None
        else await current_publication_revision_ceiling(db, company_id)
    )
    assign_ceiling = (
        int(assignment_revision_ceiling)
        if assignment_revision_ceiling is not None
        else await current_assignment_revision_ceiling(db, company_id)
    )
    if pub_ceiling <= 0 or assign_ceiling <= 0:
        raise PricingError(
            "PRICE_NOT_RESOLVED",
            "لا توجد revisions منشورة وكافية لحل السعر.",
            context={
                "price_publication_revision": pub_ceiling,
                "assignment_revision": assign_ceiling,
            },
        )

    assignment = await resolve_assignment(
        db,
        company_id=company_id,
        as_of=when,
        customer_id=customer_id,
        branch_id=branch_id,
        assignment_revision_ceiling=assign_ceiling,
    )

    rows = (
        await db.execute(
            select(
                PriceBookEntry,
                PricePublication,
                PriceBook.currency_code,
            )
            .join(
                PricePublication,
                (PricePublication.company_id == PriceBookEntry.company_id)
                & (PricePublication.id == PriceBookEntry.publication_id),
            )
            .join(
                PriceBook,
                (PriceBook.company_id == PriceBookEntry.company_id)
                & (PriceBook.id == PriceBookEntry.price_book_id),
            )
            .where(
                PriceBookEntry.company_id == int(company_id),
                PriceBookEntry.price_book_id == int(assignment.price_book_id),
                PriceBookEntry.is_published.is_(True),
                PriceBookEntry.effectivity.contains(when),
                PricePublication.status.in_(("PUBLISHED", "SUPERSEDED")),
                PricePublication.published_at.is_not(None),
                PricePublication.published_at <= when,
                PricePublication.revision <= pub_ceiling,
                tuple_(
                    PriceBookEntry.product_variant_id,
                    PriceBookEntry.uom_id,
                ).in_(normalized_pairs),
            )
            .order_by(
                PriceBookEntry.product_variant_id,
                PriceBookEntry.uom_id,
                PricePublication.revision.desc(),
                PriceBookEntry.id.desc(),
            )
        )
    ).all()

    by_pair: dict[tuple[int, int], list[tuple]] = {}
    for row in rows:
        entry = row[0]
        by_pair.setdefault(
            (int(entry.product_variant_id), int(entry.uom_id)), []
        ).append(row)

    result: dict[tuple[int, int], PriceResolution] = {}
    missing = []
    for pair in normalized_pairs:
        candidates = by_pair.get(pair, [])
        if not candidates:
            missing.append(
                {"product_variant_id": pair[0], "uom_id": pair[1]}
            )
            continue
        if len(candidates) > 1:
            if allow_unresolved_pairs:
                continue
            raise PricingError(
                "PRICE_EFFECTIVITY_CONFLICT",
                "أكثر من سعر منشور فعال لنفس SKU/UOM.",
                context={
                    "product_variant_id": pair[0],
                    "uom_id": pair[1],
                    "entry_ids": [int(row[0].id) for row in candidates],
                },
            )
        entry, publication, currency_code = candidates[0]
        result[pair] = PriceResolution(
            price_book_id=int(entry.price_book_id),
            assignment_id=int(assignment.id),
            assignment_revision=int(assignment.revision),
            assignment_scope_type=str(assignment.scope_type),
            assignment_priority=int(assignment.priority),
            price_entry_id=int(entry.id),
            price_publication_id=int(publication.id),
            price_publication_revision=int(publication.revision),
            product_variant_id=int(entry.product_variant_id),
            uom_id=int(entry.uom_id),
            amount=Decimal(entry.amount),
            currency_code=str(currency_code),
            resolved_at=when,
        )

    if missing and not allow_unresolved_pairs:
        raise PricingError(
            "PRICE_NOT_RESOLVED",
            "تعذر حل سعر منشور لكل SKU/UOM مطلوب.",
            context={
                "missing": missing,
                "price_book_id": int(assignment.price_book_id),
                "assignment_id": int(assignment.id),
            },
        )
    return result


async def resolve_price(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    uom_id: int,
    customer_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    as_of: Optional[datetime] = None,
    publication_revision_ceiling: Optional[int] = None,
    assignment_revision_ceiling: Optional[int] = None,
) -> PriceResolution:
    pair = (int(product_variant_id), int(uom_id))
    rows = await resolve_prices_bulk(
        db,
        company_id=company_id,
        pairs=[pair],
        customer_id=customer_id,
        branch_id=branch_id,
        as_of=as_of,
        publication_revision_ceiling=publication_revision_ceiling,
        assignment_revision_ceiling=assignment_revision_ceiling,
    )
    return rows[pair]
