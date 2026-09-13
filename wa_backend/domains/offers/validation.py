from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from domains.offers.core import OfferError
from domains.offers.schemas import (
    BundlePayload,
    BuyXGetYPayload,
    FixedDiscountPayload,
    FreeGoodsPayload,
    OfferProductInput,
    OfferScopeInput,
    PercentageDiscountPayload,
    QuantityTiersPayload,
)


_PAYLOAD_MODELS = {
    "PERCENTAGE_DISCOUNT": PercentageDiscountPayload,
    "FIXED_DISCOUNT": FixedDiscountPayload,
    "BUY_X_GET_Y": BuyXGetYPayload,
    "FREE_GOODS": FreeGoodsPayload,
    "QUANTITY_TIERS": QuantityTiersPayload,
    "BUNDLE": BundlePayload,
}


def _uses_money(offer_type: str, payload_model: Any) -> bool:
    uses_money = offer_type == "FIXED_DISCOUNT"
    if offer_type == "QUANTITY_TIERS":
        uses_money = any(
            tier.reward_type == "FIXED_DISCOUNT" for tier in payload_model.tiers
        )
    elif offer_type == "BUNDLE":
        uses_money = payload_model.reward_type in {"FIXED_DISCOUNT", "FIXED_PRICE"}
    caps = getattr(payload_model, "caps", None)
    return uses_money or bool(caps and caps.max_discount_amount is not None)


def validate_offer_configuration(
    *,
    offer_type: str,
    payload: dict[str, Any],
    currency_code: str | None,
    scopes: list[OfferScopeInput],
    products: list[OfferProductInput],
) -> dict[str, Any]:
    model_type = _PAYLOAD_MODELS.get(offer_type)
    if model_type is None:
        raise OfferError(
            "OFFER_TYPE_UNSUPPORTED",
            "Offer type is not supported.",
            status_code=422,
            context={"offer_type": offer_type},
        )
    try:
        parsed = model_type.model_validate(payload)
    except ValidationError as exc:
        raise OfferError(
            "OFFER_PAYLOAD_INVALID",
            "Offer parameters are invalid for the selected offer type.",
            status_code=422,
            context={"errors": exc.errors(include_url=False)},
        ) from exc

    if _uses_money(offer_type, parsed) and not currency_code:
        raise OfferError(
            "OFFER_CURRENCY_REQUIRED",
            "A currency is required when an offer contains a monetary amount.",
            status_code=422,
        )

    scope_keys = {
        (
            item.scope_type,
            item.product_variant_id,
            item.customer_id,
            item.branch_id,
            item.channel_code,
        )
        for item in scopes
    }
    if len(scope_keys) != len(scopes):
        raise OfferError(
            "OFFER_SCOPE_DUPLICATE",
            "Offer scope contains duplicate targets.",
            status_code=422,
        )

    product_keys = {(item.role, item.product_variant_id) for item in products}
    if len(product_keys) != len(products):
        raise OfferError(
            "OFFER_PRODUCT_DUPLICATE",
            "Offer product roles contain duplicate products.",
            status_code=422,
        )

    roles = {item.role for item in products}
    product_scopes = [
        item for item in scopes if item.scope_type == "PRODUCT_VARIANT"
    ]

    if offer_type in {"PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT"}:
        if products:
            raise OfferError(
                "OFFER_PRODUCT_ROLE_NOT_ALLOWED",
                "This offer type uses product scopes and does not accept cross-product roles.",
                status_code=422,
            )
    elif offer_type == "QUANTITY_TIERS":
        if products:
            raise OfferError(
                "OFFER_PRODUCT_ROLE_NOT_ALLOWED",
                "QUANTITY_TIERS uses a product scope and does not accept cross-product roles.",
                status_code=422,
            )
        if len(product_scopes) != 1:
            raise OfferError(
                "OFFER_QUANTITY_TIER_SCOPE_REQUIRED",
                "QUANTITY_TIERS must target exactly one product variant.",
                status_code=422,
            )
    elif offer_type in {"BUY_X_GET_Y", "FREE_GOODS"}:
        if product_scopes:
            raise OfferError(
                "OFFER_PRODUCT_SCOPE_NOT_ALLOWED",
                f"{offer_type} uses qualifying/reward products instead of product scopes.",
                status_code=422,
            )
        qualifying = [item for item in products if item.role == "QUALIFYING"]
        rewards = [item for item in products if item.role == "REWARD"]
        if not qualifying or len(rewards) != 1:
            raise OfferError(
                "OFFER_PRODUCT_ROLE_REQUIRED",
                f"{offer_type} requires one or more qualifying products and exactly one reward product.",
                status_code=422,
            )
        if roles - {"QUALIFYING", "REWARD"}:
            raise OfferError(
                "OFFER_PRODUCT_ROLE_NOT_ALLOWED",
                f"{offer_type} only accepts qualifying and reward products.",
                status_code=422,
            )
    elif offer_type == "BUNDLE":
        if product_scopes:
            raise OfferError(
                "OFFER_PRODUCT_SCOPE_NOT_ALLOWED",
                "BUNDLE uses bundle-component products instead of product scopes.",
                status_code=422,
            )
        components = [item for item in products if item.role == "BUNDLE_COMPONENT"]
        if len(components) < 2 or roles != {"BUNDLE_COMPONENT"}:
            raise OfferError(
                "OFFER_BUNDLE_COMPONENTS_REQUIRED",
                "BUNDLE requires at least two bundle component products.",
                status_code=422,
            )

    return parsed.model_dump(mode="json", exclude_none=True)
