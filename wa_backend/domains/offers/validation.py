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
            tier.reward_type == "FIXED_DISCOUNT"
            for tier in payload_model.tiers
        )
    elif offer_type == "BUNDLE":
        uses_money = payload_model.reward_type in {
            "FIXED_DISCOUNT",
            "FIXED_PRICE",
        }
    caps = getattr(payload_model, "caps", None)
    return uses_money or bool(
        caps and caps.max_discount_amount is not None
    )


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
            item.uom_id,
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

    product_keys = {
        (
            item.role,
            item.product_variant_id,
            item.uom_id,
        )
        for item in products
    }
    if len(product_keys) != len(products):
        raise OfferError(
            "OFFER_PRODUCT_DUPLICATE",
            "Offer product roles contain duplicate product/UOM targets.",
            status_code=422,
        )

    roles = {item.role for item in products}
    product_scopes = [
        item
        for item in scopes
        if item.scope_type == "PRODUCT_VARIANT"
    ]

    targets_by_variant: dict[int, list[OfferScopeInput]] = {}
    for item in product_scopes:
        targets_by_variant.setdefault(
            int(item.product_variant_id),
            [],
        ).append(item)
    for variant_id, targets in targets_by_variant.items():
        if (
            len(targets) > 1
            and any(item.uom_id is None for item in targets)
        ):
            raise OfferError(
                "OFFER_PRODUCT_TARGET_OVERLAP",
                "An all-UOM target cannot be combined with UOM-specific targets for the same product.",
                status_code=422,
                context={"product_variant_id": variant_id},
            )

    if offer_type in {
        "PERCENTAGE_DISCOUNT",
        "FIXED_DISCOUNT",
    }:
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
        if (
            len(product_scopes) != 1
            or product_scopes[0].uom_id is None
        ):
            raise OfferError(
                "OFFER_QUANTITY_TIER_SCOPE_REQUIRED",
                "QUANTITY_TIERS must target exactly one product variant and one explicit UOM.",
                status_code=422,
            )

    elif offer_type in {
        "BUY_X_GET_Y",
        "FREE_GOODS",
    }:
        if product_scopes:
            raise OfferError(
                "OFFER_PRODUCT_SCOPE_NOT_ALLOWED",
                f"{offer_type} uses qualifying/reward products instead of product scopes.",
                status_code=422,
            )
        qualifying = [
            item
            for item in products
            if item.role == "QUALIFYING"
        ]
        rewards = [
            item
            for item in products
            if item.role == "REWARD"
        ]
        if not qualifying or not rewards:
            raise OfferError(
                "OFFER_PRODUCT_ROLE_REQUIRED",
                f"{offer_type} requires one or more qualifying products and one or more reward products.",
                status_code=422,
            )
        if roles - {"QUALIFYING", "REWARD"}:
            raise OfferError(
                "OFFER_PRODUCT_ROLE_NOT_ALLOWED",
                f"{offer_type} only accepts qualifying and reward products.",
                status_code=422,
            )
        qualifying_uoms = {
            int(item.uom_id)
            for item in qualifying
        }
        if len(qualifying_uoms) != 1:
            raise OfferError(
                "OFFER_QUALIFYING_UOM_CONFLICT",
                f"{offer_type} qualifying pool must use one explicit UOM.",
                status_code=422,
            )
        if any(
            item.quantity_per_application is not None
            for item in qualifying
        ):
            raise OfferError(
                "OFFER_QUALIFYING_QUANTITY_NOT_ALLOWED",
                f"{offer_type} qualifying threshold lives in the typed payload, not product rows.",
                status_code=422,
            )
        if any(
            item.quantity_per_application is None
            for item in rewards
        ):
            raise OfferError(
                "OFFER_REWARD_QUANTITY_REQUIRED",
                f"{offer_type} requires an explicit quantity for every reward product/UOM.",
                status_code=422,
            )
        caps = getattr(parsed, "caps", None)
        if caps and caps.max_reward_quantity is not None:
            raise OfferError(
                "OFFER_REWARD_CAP_DIMENSION_INVALID",
                "max_reward_quantity is ambiguous for multi-UOM rewards; cap applications instead.",
                status_code=422,
            )

    elif offer_type == "BUNDLE":
        if product_scopes:
            raise OfferError(
                "OFFER_PRODUCT_SCOPE_NOT_ALLOWED",
                "BUNDLE uses bundle-component products instead of product scopes.",
                status_code=422,
            )
        components = [
            item
            for item in products
            if item.role == "BUNDLE_COMPONENT"
        ]
        if (
            len(components) < 2
            or len(
                {
                    int(item.product_variant_id)
                    for item in components
                }
            ) < 2
            or roles != {"BUNDLE_COMPONENT"}
            or any(
                item.quantity_per_application is None
                for item in components
            )
        ):
            raise OfferError(
                "OFFER_BUNDLE_COMPONENTS_REQUIRED",
                "BUNDLE requires at least two distinct products, each with explicit UOM and quantity.",
                status_code=422,
            )

    return parsed.model_dump(
        mode="json",
        exclude_none=True,
    )
