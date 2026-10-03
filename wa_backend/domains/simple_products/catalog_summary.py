"""Read-only, company-wide catalog counters; never a product-state authority."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProductVariant


class CatalogSummaryResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal[1] = 1
    company_id: int = Field(gt=0)
    total: int = Field(ge=0)
    available: int = Field(ge=0)
    retiring: int = Field(ge=0)
    archived: int = Field(ge=0)
    sales_restricted: int = Field(ge=0)


async def load_catalog_summary(
    db: AsyncSession, *, company_id: int,
) -> CatalogSummaryResponse:
    """One aggregate snapshot, independent of list search, filters or pagination.

    Total includes every SKU, including drafts. Hold counts may overlap lifecycle
    counts; availability means exactly ACTIVE + NONE, not inventory or pricing
    readiness. The caller retains catalog.read and the existing tenant/RLS scope.
    """
    row = (await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(and_(
                ProductVariant.lifecycle_status == "ACTIVE",
                ProductVariant.operational_hold == "NONE",
            )).label("available"),
            func.count().filter(
                ProductVariant.lifecycle_status == "RETIRING",
            ).label("retiring"),
            func.count().filter(
                ProductVariant.lifecycle_status == "ARCHIVED",
            ).label("archived"),
            func.count().filter(
                ProductVariant.operational_hold.in_(("SALES_HOLD", "RECALL")),
            ).label("sales_restricted"),
        ).select_from(ProductVariant).where(
            ProductVariant.company_id == company_id,
        )
    )).mappings().one()
    return CatalogSummaryResponse(company_id=company_id, **dict(row))
