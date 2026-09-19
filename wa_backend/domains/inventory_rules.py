from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, or_

from models import ProductBatch


def batch_sellability_predicate(
    as_of_date: date,
    *,
    expiry_control_mode,
    minimum_remaining_shelf_life_days=None,
):
    """Single SQL authority for batch sellability across inventory reads/writes/projections."""
    if type(as_of_date) is not date:
        raise ValueError("as_of_date must be an explicit date.")

    min_days = (
        func.coalesce(minimum_remaining_shelf_life_days, 0)
        if minimum_remaining_shelf_life_days is not None
        else 0
    )
    expiry_meets_policy = and_(
        ProductBatch.expiry_date.is_not(None),
        (ProductBatch.expiry_date - as_of_date) >= min_days,
    )
    no_expiry_allowed = and_(
        ProductBatch.expiry_date.is_(None),
        min_days == 0,
    )

    return and_(
        ProductBatch.is_active.is_(True),
        ProductBatch.disposition == "RELEASED",
        or_(
            ProductBatch.production_date.is_(None),
            ProductBatch.production_date <= as_of_date,
        ),
        or_(
            and_(
                expiry_control_mode == "NONE",
                no_expiry_allowed,
            ),
            and_(
                expiry_control_mode == "OPTIONAL",
                or_(no_expiry_allowed, expiry_meets_policy),
            ),
            and_(
                expiry_control_mode == "REQUIRED",
                expiry_meets_policy,
            ),
        ),
    )
