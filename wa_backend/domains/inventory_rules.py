from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, or_

from models import ProductBatch


def batch_expiry_policy_predicate(
    as_of_date: date,
    *,
    expiry_control_mode,
    minimum_remaining_shelf_life_days=None,
):
    """SQL authority for the expiry-policy portion of batch sellability."""
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

    return or_(
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
    )


def batch_sellability_predicate(
    as_of_date: date,
    *,
    expiry_control_mode,
    minimum_remaining_shelf_life_days=None,
):
    """Single SQL authority for batch sellability across inventory reads/writes/projections."""
    expiry_policy_allows = batch_expiry_policy_predicate(
        as_of_date,
        expiry_control_mode=expiry_control_mode,
        minimum_remaining_shelf_life_days=minimum_remaining_shelf_life_days,
    )

    return and_(
        ProductBatch.is_active.is_(True),
        ProductBatch.disposition == "RELEASED",
        or_(
            ProductBatch.production_date.is_(None),
            ProductBatch.production_date <= as_of_date,
        ),
        expiry_policy_allows,
    )


def batch_metadata_is_sellable(
    *,
    as_of_date: date,
    expiry_control_mode: str,
    production_date: date | None,
    expiry_date: date | None,
    minimum_remaining_shelf_life_days: int = 0,
    is_active: bool = True,
    disposition: str = "RELEASED",
) -> bool:
    """Pure-Python twin of batch_sellability_predicate for locked movement data."""
    if type(as_of_date) is not date:
        raise ValueError("as_of_date must be an explicit date.")
    minimum_days = int(minimum_remaining_shelf_life_days or 0)
    if minimum_days < 0:
        raise ValueError("minimum_remaining_shelf_life_days cannot be negative.")

    mode = str(expiry_control_mode or "").upper()
    if mode not in {"NONE", "OPTIONAL", "REQUIRED"}:
        raise ValueError("expiry_control_mode is invalid.")

    if not bool(is_active) or str(disposition or "").upper() != "RELEASED":
        return False
    if production_date is not None and production_date > as_of_date:
        return False

    if expiry_date is None:
        return mode in {"NONE", "OPTIONAL"} and minimum_days == 0

    if mode == "NONE":
        return False
    return (expiry_date - as_of_date).days >= minimum_days


def batch_next_transition_date(
    *,
    as_of_date: date,
    expiry_control_mode: str,
    production_date: date | None,
    expiry_date: date | None,
    minimum_remaining_shelf_life_days: int = 0,
    is_active: bool = True,
    disposition: str = "RELEASED",
) -> date | None:
    """Next date on which this batch can change Live Stock sellability."""
    if type(as_of_date) is not date:
        raise ValueError("as_of_date must be an explicit date.")
    if not bool(is_active) or str(disposition or "").upper() != "RELEASED":
        return None

    minimum_days = int(minimum_remaining_shelf_life_days or 0)
    if minimum_days < 0:
        raise ValueError("minimum_remaining_shelf_life_days cannot be negative.")

    mode = str(expiry_control_mode or "").upper()
    candidates: list[date] = []
    if production_date is not None and production_date > as_of_date:
        candidates.append(production_date)

    if mode in {"OPTIONAL", "REQUIRED"} and expiry_date is not None:
        expiry_transition = expiry_date - timedelta(days=minimum_days) + timedelta(days=1)
        if expiry_transition > as_of_date:
            candidates.append(expiry_transition)

    return min(candidates) if candidates else None
