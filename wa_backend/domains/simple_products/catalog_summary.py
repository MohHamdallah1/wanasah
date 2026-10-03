"""Read-only, company-wide catalog counters; never a product-state authority."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Product, ProductVariant


class CatalogSummaryResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal[2] = 2
    company_id: int = Field(gt=0)
    total: int = Field(ge=0)
    families: int = Field(ge=0)
    available: int = Field(ge=0)
    stopped: int = Field(ge=0)
    archived: int = Field(ge=0)


async def load_catalog_summary(
    db: AsyncSession, *, company_id: int,
) -> CatalogSummaryResponse:
    """One aggregate snapshot, independent of list search, filters or pagination.

    The summary mirrors the three-state commercial presentation only. Backend
    lifecycle/hold authority stays independent and unchanged. ``stopped`` means
    any non-archived SKU that is not exactly ACTIVE + NONE, including drafts,
    temporary sales holds, problem holds and retiring products.
    """
    family_count = (
        select(func.count())
        .select_from(Product)
        .where(Product.company_id == company_id)
        .scalar_subquery()
    )
    stopped_predicate = and_(
        ProductVariant.lifecycle_status != "ARCHIVED",
        or_(
            ProductVariant.lifecycle_status != "ACTIVE",
            ProductVariant.operational_hold != "NONE",
        ),
    )
    row = (await db.execute(
        select(
            func.count().label("total"),
            family_count.label("families"),
            func.count().filter(and_(
                ProductVariant.lifecycle_status == "ACTIVE",
                ProductVariant.operational_hold == "NONE",
            )).label("available"),
            func.count().filter(stopped_predicate).label("stopped"),
            func.count().filter(
                ProductVariant.lifecycle_status == "ARCHIVED",
            ).label("archived"),
        ).select_from(ProductVariant).where(
            ProductVariant.company_id == company_id,
        )
    )).mappings().one()
    return CatalogSummaryResponse(company_id=company_id, **dict(row))
