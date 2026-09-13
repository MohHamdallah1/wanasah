from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.offers.contracts import (
    OfferCandidate,
    OfferProductRef,
    ProductTargetRef,
)
from domains.offers.core import OfferError
from domains.offers.models import (
    OfferVersion,
    OfferVersionProduct,
    OfferVersionScope,
)
from models import Branch, Shop


def _aware(value: datetime) -> datetime:
    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise OfferError(
            "OFFER_AS_OF_TIMEZONE_REQUIRED",
            "Offer calculation time must include a UTC offset.",
            status_code=422,
        )
    return value.astimezone(
        timezone.utc
    )


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
                Shop.company_id
                == company_id,
                Shop.id
                == int(customer_id),
            )
        )
        if exists is None:
            raise OfferError(
                "OFFER_CUSTOMER_NOT_FOUND",
                "Customer is not available inside this company.",
                status_code=404,
            )
    if branch_id is not None:
        exists = await db.scalar(
            select(Branch.id).where(
                Branch.company_id
                == company_id,
                Branch.id
                == int(branch_id),
            )
        )
        if exists is None:
            raise OfferError(
                "OFFER_BRANCH_NOT_FOUND",
                "Branch is not available inside this company.",
                status_code=404,
            )


async def current_offer_revision_ceiling(
    db: AsyncSession,
    *,
    company_id: int,
    as_of: datetime,
) -> int:
    when = _aware(as_of)
    value = await db.scalar(
        select(
            func.max(
                OfferVersion.revision
            )
        ).where(
            OfferVersion.company_id
            == company_id,
            OfferVersion.status.in_(
                (
                    "PUBLISHED",
                    "SUPERSEDED",
                )
            ),
            OfferVersion.published_at
            .is_not(None),
            OfferVersion.published_at
            <= when,
        )
    )
    return int(value or 0)


def _scope_matches(
    scopes: list[
        OfferVersionScope
    ],
    *,
    customer_id: Optional[int],
    branch_id: Optional[int],
    channel_code: Optional[str],
) -> bool:
    by_type: dict[
        str,
        set,
    ] = defaultdict(set)

    for scope in scopes:
        if (
            scope.scope_type
            == "CUSTOMER"
        ):
            by_type[
                "CUSTOMER"
            ].add(
                int(scope.customer_id)
            )
        elif (
            scope.scope_type
            == "BRANCH"
        ):
            by_type[
                "BRANCH"
            ].add(
                int(scope.branch_id)
            )
        elif (
            scope.scope_type
            == "CHANNEL"
        ):
            by_type[
                "CHANNEL"
            ].add(
                str(
                    scope.channel_code
                ).upper()
            )

    if (
        by_type["CUSTOMER"]
        and customer_id
        not in by_type["CUSTOMER"]
    ):
        return False
    if (
        by_type["BRANCH"]
        and branch_id
        not in by_type["BRANCH"]
    ):
        return False

    normalized_channel = (
        channel_code.upper()
        if channel_code
        else None
    )
    if (
        by_type["CHANNEL"]
        and normalized_channel
        not in by_type["CHANNEL"]
    ):
        return False
    return True


async def resolve_offer_candidates(
    db: AsyncSession,
    *,
    company_id: int,
    as_of: datetime,
    currency_code: str,
    customer_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    channel_code: Optional[str] = None,
    revision_ceiling: Optional[int] = None,
) -> tuple[
    list[OfferCandidate],
    int,
]:
    if company_id <= 0:
        raise OfferError(
            "OFFER_TENANT_INVALID",
            "company_id must be positive.",
            status_code=422,
        )

    when = _aware(as_of)
    currency = (
        str(currency_code)
        .strip()
        .upper()
    )
    if not currency:
        raise OfferError(
            "OFFER_CURRENCY_REQUIRED",
            "Transaction currency is required.",
            status_code=422,
        )
    channel = (
        channel_code.strip().upper()
        if channel_code
        else None
    )

    await _validate_context(
        db,
        company_id=company_id,
        customer_id=customer_id,
        branch_id=branch_id,
    )

    ceiling = (
        int(revision_ceiling)
        if revision_ceiling
        is not None
        else await current_offer_revision_ceiling(
            db,
            company_id=company_id,
            as_of=when,
        )
    )
    if ceiling < 0:
        raise OfferError(
            "OFFER_REVISION_INVALID",
            "Offer revision ceiling cannot be negative.",
            status_code=422,
        )
    if ceiling == 0:
        return [], 0

    latest = (
        select(
            OfferVersion
            .offer_definition_id
            .label("definition_id"),
            func.max(
                OfferVersion.revision
            ).label("revision"),
        )
        .where(
            OfferVersion.company_id
            == company_id,
            OfferVersion.status.in_(
                (
                    "PUBLISHED",
                    "SUPERSEDED",
                )
            ),
            OfferVersion.published_at
            .is_not(None),
            OfferVersion.published_at
            <= when,
            OfferVersion.revision
            <= ceiling,
            OfferVersion.effective_from
            <= when,
            or_(
                OfferVersion.effective_to
                .is_(None),
                OfferVersion.effective_to
                > when,
            ),
            or_(
                OfferVersion.currency_code
                .is_(None),
                OfferVersion.currency_code
                == currency,
            ),
        )
        .group_by(
            OfferVersion
            .offer_definition_id
        )
        .subquery()
    )

    rows = list(
        (
            await db.scalars(
                select(OfferVersion)
                .join(
                    latest,
                    (
                        latest.c.definition_id
                        == OfferVersion
                        .offer_definition_id
                    )
                    & (
                        latest.c.revision
                        == OfferVersion
                        .revision
                    ),
                )
                .where(
                    OfferVersion.company_id
                    == company_id
                )
                .order_by(
                    OfferVersion
                    .priority.desc(),
                    OfferVersion
                    .revision.desc(),
                    OfferVersion.id.asc(),
                )
            )
        ).all()
    )
    if not rows:
        return [], ceiling

    ids = [
        int(row.id)
        for row in rows
    ]
    scopes = list(
        (
            await db.scalars(
                select(
                    OfferVersionScope
                )
                .where(
                    OfferVersionScope
                    .company_id
                    == company_id,
                    OfferVersionScope
                    .offer_version_id
                    .in_(ids),
                )
                .order_by(
                    OfferVersionScope
                    .offer_version_id,
                    OfferVersionScope.id,
                )
            )
        ).all()
    )
    products = list(
        (
            await db.scalars(
                select(
                    OfferVersionProduct
                )
                .where(
                    OfferVersionProduct
                    .company_id
                    == company_id,
                    OfferVersionProduct
                    .offer_version_id
                    .in_(ids),
                )
                .order_by(
                    OfferVersionProduct
                    .offer_version_id,
                    OfferVersionProduct.id,
                )
            )
        ).all()
    )

    scope_map: dict[
        int,
        list[OfferVersionScope],
    ] = defaultdict(list)
    product_map: dict[
        int,
        list[OfferVersionProduct],
    ] = defaultdict(list)

    for scope in scopes:
        scope_map[
            int(
                scope.offer_version_id
            )
        ].append(scope)
    for product in products:
        product_map[
            int(
                product.offer_version_id
            )
        ].append(product)

    result: list[
        OfferCandidate
    ] = []
    for row in rows:
        row_scopes = scope_map[
            int(row.id)
        ]
        if not _scope_matches(
            row_scopes,
            customer_id=customer_id,
            branch_id=branch_id,
            channel_code=channel,
        ):
            continue

        result.append(
            OfferCandidate(
                version_id=int(row.id),
                definition_id=int(
                    row.offer_definition_id
                ),
                revision=int(
                    row.revision
                ),
                offer_type=str(
                    row.offer_type
                ),
                priority=int(
                    row.priority
                ),
                stacking_mode=str(
                    row.stacking_mode
                ),
                payload=dict(
                    row.validated_payload
                    or {}
                ),
                product_targets=tuple(
                    ProductTargetRef(
                        product_variant_id=int(
                            scope
                            .product_variant_id
                        ),
                        uom_id=(
                            int(scope.uom_id)
                            if scope.uom_id
                            is not None
                            else None
                        ),
                    )
                    for scope in row_scopes
                    if (
                        scope.scope_type
                        == "PRODUCT_VARIANT"
                        and scope
                        .product_variant_id
                        is not None
                    )
                ),
                products=tuple(
                    OfferProductRef(
                        role=str(
                            product.role
                        ),
                        product_variant_id=int(
                            product
                            .product_variant_id
                        ),
                        uom_id=int(
                            product.uom_id
                        ),
                        quantity_per_application=(
                            product
                            .quantity_per_application
                            if product
                            .quantity_per_application
                            is not None
                            else None
                        ),
                    )
                    for product
                    in product_map[
                        int(row.id)
                    ]
                ),
            )
        )

    return result, ceiling
