from __future__ import annotations

from domains.offers.handlers.bundle import bundle
from domains.offers.handlers.cross_product import buy_x_get_y, free_goods
from domains.offers.handlers.quantity import quantity_tiers
from domains.offers.handlers.simple import fixed_discount, percentage_discount


HANDLERS = {
    "PERCENTAGE_DISCOUNT": percentage_discount,
    "FIXED_DISCOUNT": fixed_discount,
    "BUY_X_GET_Y": buy_x_get_y,
    "FREE_GOODS": free_goods,
    "QUANTITY_TIERS": quantity_tiers,
    "BUNDLE": bundle,
}
