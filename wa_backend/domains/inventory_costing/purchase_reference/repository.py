"""Tenant-scoped persistence and early transaction guards; never commits."""
from sqlalchemy import select, text

from models import Company, ProductVariant, UOM
from .errors import PurchaseReferenceError
from .models import PurchaseCostReference, PurchaseReferenceCommand


async def acquire_operation_guard(db, company_id, request_id):
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"purchase-reference-command:{company_id}:{request_id}"},
    )


async def acquire_writer_guard(db, *, company_id):
    """Must precede Product/Pricing/Inventory locks in every reference writer.

    Future Inbound integration calls this immediately after its durable replay
    branch, not from the movement/costing engine. Held until caller completion.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"purchase-reference-writer:{company_id}"},
    )


async def command_record(db, company_id, request_id):
    return await db.scalar(select(PurchaseReferenceCommand).where(
        PurchaseReferenceCommand.company_id == company_id,
        PurchaseReferenceCommand.request_id == request_id,
    ).execution_options(populate_existing=True))


async def current_reference(db, company_id, variant_id, *, lock=False):
    statement = select(PurchaseCostReference).where(
        PurchaseCostReference.company_id == company_id,
        PurchaseCostReference.product_variant_id == variant_id,
    ).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def variant_and_currency(db, company_id, variant_id, *, lock=False):
    statement = select(ProductVariant).where(
        ProductVariant.company_id == company_id, ProductVariant.id == variant_id,
    ).execution_options(populate_existing=True)
    if lock:
        # Catalog structural/conversion commands lock this same parent FOR UPDATE.
        # Do not lock conversion rows: the legacy editor locks child then parent.
        statement = statement.with_for_update(read=True)
    variant = await db.scalar(statement)
    if variant is None:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    currency_statement = select(Company.currency_code).where(Company.id == company_id)
    if lock:
        # Stabilize this command's currency without imposing global immutability.
        # Parent Product SHARE precedes Company SHARE, matching the touched
        # existing Product-price path's Product -> Company acquisition direction.
        currency_statement = currency_statement.with_for_update(read=True)
    currency = await db.scalar(currency_statement)
    return variant, currency


async def uom_codes(db, uom_ids):
    return dict((await db.execute(
        select(UOM.id, UOM.code).where(UOM.id.in_(sorted(set(uom_ids))))
    )).all())
