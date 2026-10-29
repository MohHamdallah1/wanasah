from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from models import ProductUomConversion, ProductVariant, UOM


def display_uom_one_subquery(*, company_id: int, alias_prefix: str):
    """Return one unambiguous larger display UOM for a product variant.

    When a variant has zero or multiple larger conversions, callers keep the
    base UOM so reads never guess which commercial unit is preferred.
    """
    display_uom = aliased(UOM, name=f"{alias_prefix}_uom")
    display_factor_expression = (
        ProductUomConversion.numerator
        / ProductUomConversion.denominator
    )
    return (
        select(
            func.count(ProductUomConversion.id).label("candidate_count"),
            func.min(display_uom.id).label("display_uom_id_raw"),
            func.min(display_uom.code).label("display_uom_code_raw"),
            func.min(display_uom.name).label("display_uom_name_raw"),
            func.min(display_factor_expression).label(
                "display_factor_to_base_raw"
            ),
            func.min(ProductUomConversion.quantity_scale).label(
                "display_quantity_scale_raw"
            ),
        )
        .select_from(ProductUomConversion)
        .join(
            display_uom,
            display_uom.id == ProductUomConversion.from_uom_id,
        )
        .where(
            ProductUomConversion.company_id == company_id,
            ProductUomConversion.product_variant_id == ProductVariant.id,
            ProductUomConversion.to_uom_id == ProductVariant.base_uom_id,
            ProductUomConversion.numerator
            > ProductUomConversion.denominator,
        )
        .lateral(f"{alias_prefix}_one")
    )
