from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Branch,
    PriceBook,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    RouteCommercialContext,
    ProductUomConversion,
    ProductVariant,
    Shop,
)

from .core import (
    PricingError,
    acquire_pricing_company_lock,
    maker_checker_enabled,
    money_20_6,
    next_assignment_revision,
    next_publication_revision,
    require_aware_datetime,
    utc_now,
)


SUPPORTED_ASSIGNMENT_SCOPES = frozenset(
    {"CUSTOMER", "BRANCH", "COMPANY_DEFAULT"}
)
RESERVED_ASSIGNMENT_SCOPES = frozenset({"CUSTOMER_GROUP", "CHANNEL"})


def _range(
    effective_from: datetime,
    effective_to: Optional[datetime],
    *,
    field_prefix: str = "effectivity",
) -> Range[datetime]:
    lower = require_aware_datetime(effective_from, f"{field_prefix}.from")
    upper = (
        require_aware_datetime(effective_to, f"{field_prefix}.to")
        if effective_to is not None
        else None
    )
    if upper is not None and upper <= lower:
        raise PricingError(
            "PRICE_EFFECTIVITY_INVALID",
            "نهاية فترة السريان يجب أن تكون بعد بدايتها.",
            status_code=422,
        )
    return Range(lower, upper, bounds="[)")


async def _active_book(
    db: AsyncSession,
    *,
    company_id: int,
    book_id: int,
    lock: bool = False,
) -> PriceBook:
    stmt = select(PriceBook).where(
        PriceBook.company_id == int(company_id),
        PriceBook.id == int(book_id),
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise PricingError(
            "PRICE_BOOK_NOT_FOUND",
            "دفتر الأسعار غير موجود.",
            status_code=404,
            context={"price_book_id": int(book_id)},
        )
    if row.status != "ACTIVE":
        raise PricingError(
            "PRICE_BOOK_INACTIVE",
            "دفتر الأسعار غير فعال ولا يقبل تعديلات تجارية جديدة.",
            context={"price_book_id": int(book_id), "status": row.status},
        )
    return row


async def create_price_book(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    code: str,
    name: str,
    currency_code: str,
    applicability_metadata: Optional[dict[str, Any]] = None,
) -> PriceBook:
    await acquire_pricing_company_lock(db, company_id)
    row = PriceBook(
        company_id=int(company_id),
        code=str(code).strip().upper(),
        name=str(name).strip(),
        currency_code=str(currency_code).strip().upper(),
        status="ACTIVE",
        applicability_metadata=dict(applicability_metadata or {}),
        version=1,
        created_by=int(actor_id),
    )
    db.add(row)
    await db.flush()
    return row


async def create_publication(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    book_id: int,
    expected_book_version: int,
    effective_at: datetime,
    request_id: UUID,
) -> PricePublication:
    effective_at = require_aware_datetime(effective_at, "effective_at")
    await acquire_pricing_company_lock(db, company_id)
    book = await _active_book(
        db, company_id=company_id, book_id=book_id, lock=True
    )
    if int(book.version) != int(expected_book_version):
        raise PricingError(
            "PRICE_BOOK_VERSION_CONFLICT",
            "تغير دفتر الأسعار؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(book.version)},
        )
    revision = await next_publication_revision(db, company_id)
    row = PricePublication(
        company_id=int(company_id),
        price_book_id=int(book_id),
        revision=revision,
        status="DRAFT",
        effective_at=effective_at,
        created_by=int(actor_id),
        request_id=request_id,
        version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def _draft_publication(
    db: AsyncSession,
    *,
    company_id: int,
    publication_id: int,
    expected_version: int,
) -> PricePublication:
    row = await db.scalar(
        select(PricePublication)
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.id == int(publication_id),
        )
        .with_for_update()
    )
    if row is None:
        raise PricingError(
            "PRICE_PUBLICATION_NOT_FOUND",
            "نسخة النشر غير موجودة.",
            status_code=404,
        )
    if row.status != "DRAFT":
        raise PricingError(
            "PRICE_PUBLICATION_NOT_EDITABLE",
            "يمكن تعديل إدخالات السعر داخل DRAFT فقط.",
            context={"status": row.status},
        )
    if int(row.version) != int(expected_version):
        raise PricingError(
            "PRICE_PUBLICATION_VERSION_CONFLICT",
            "تغيرت نسخة النشر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(row.version)},
        )
    return row


async def _variant_uom_valid(
    db: AsyncSession,
    *,
    company_id: int,
    variant_id: int,
    uom_id: int,
) -> bool:
    row = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.base_uom_id,
                ProductVariant.lifecycle_status,
            ).where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id == int(variant_id),
            )
        )
    ).one_or_none()
    if row is None:
        return False
    if str(row.lifecycle_status) not in {"ACTIVE", "RETIRING"}:
        return False
    if int(row.base_uom_id) == int(uom_id):
        return True
    conversion = await db.scalar(
        select(ProductUomConversion.id).where(
            ProductUomConversion.company_id == int(company_id),
            ProductUomConversion.product_variant_id == int(variant_id),
            or_(
                ProductUomConversion.from_uom_id == int(uom_id),
                ProductUomConversion.to_uom_id == int(uom_id),
            ),
        )
    )
    return conversion is not None


async def create_draft_entry(
    db: AsyncSession,
    *,
    company_id: int,
    publication_id: int,
    expected_publication_version: int,
    product_variant_id: int,
    uom_id: int,
    amount: Any,
    effective_from: datetime,
    effective_to: Optional[datetime],
    priority: int,
    metadata: Optional[dict[str, Any]],
) -> PriceBookEntry:
    publication = await _draft_publication(
        db,
        company_id=company_id,
        publication_id=publication_id,
        expected_version=expected_publication_version,
    )
    if not await _variant_uom_valid(
        db,
        company_id=company_id,
        variant_id=product_variant_id,
        uom_id=uom_id,
    ):
        raise PricingError(
            "PRICE_UOM_MAPPING_UNRESOLVED",
            "وحدة السعر لا ترتبط بهذا الـSKU أو أن الصنف غير صالح للنشر التجاري.",
            context={
                "product_variant_id": int(product_variant_id),
                "uom_id": int(uom_id),
            },
        )
    effectivity = _range(effective_from, effective_to)
    if publication.effective_at is None:
        raise PricingError(
            "PRICE_PUBLICATION_EFFECTIVE_AT_REQUIRED",
            "نسخة النشر لا تحمل effective_at صالحاً.",
        )
    if effectivity.lower < publication.effective_at:
        raise PricingError(
            "PRICE_EFFECTIVITY_BEFORE_PUBLICATION",
            "بداية سعر الإدخال لا يجوز أن تسبق effective_at لنسخة النشر.",
        )
    row = PriceBookEntry(
        company_id=int(company_id),
        price_book_id=int(publication.price_book_id),
        publication_id=int(publication.id),
        product_variant_id=int(product_variant_id),
        uom_id=int(uom_id),
        amount=money_20_6(amount),
        effectivity=effectivity,
        priority=int(priority),
        is_published=False,
        entry_metadata=dict(metadata or {}),
        version=1,
    )
    db.add(row)
    publication.version += 1
    publication.updated_at = utc_now()
    await db.flush()
    return row


async def update_draft_entry(
    db: AsyncSession,
    *,
    company_id: int,
    entry_id: int,
    expected_entry_version: int,
    expected_publication_version: int,
    amount: Any,
    effective_from: datetime,
    effective_to: Optional[datetime],
    priority: int,
    metadata: Optional[dict[str, Any]],
) -> PriceBookEntry:
    entry = await db.scalar(
        select(PriceBookEntry)
        .where(
            PriceBookEntry.company_id == int(company_id),
            PriceBookEntry.id == int(entry_id),
        )
        .with_for_update()
    )
    if entry is None:
        raise PricingError(
            "PRICE_ENTRY_NOT_FOUND",
            "إدخال السعر غير موجود.",
            status_code=404,
        )
    if entry.is_published:
        raise PricingError(
            "PRICE_ENTRY_IMMUTABLE",
            "السعر المنشور immutable ولا يعدل مباشرة.",
        )
    publication = await _draft_publication(
        db,
        company_id=company_id,
        publication_id=int(entry.publication_id),
        expected_version=expected_publication_version,
    )
    if int(entry.version) != int(expected_entry_version):
        raise PricingError(
            "PRICE_ENTRY_VERSION_CONFLICT",
            "تغير إدخال السعر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(entry.version)},
        )
    effectivity = _range(effective_from, effective_to)
    if publication.effective_at is None or effectivity.lower < publication.effective_at:
        raise PricingError(
            "PRICE_EFFECTIVITY_BEFORE_PUBLICATION",
            "بداية سعر الإدخال لا يجوز أن تسبق effective_at لنسخة النشر.",
        )
    entry.amount = money_20_6(amount)
    entry.effectivity = effectivity
    entry.priority = int(priority)
    entry.entry_metadata = dict(metadata or {})
    entry.version += 1
    entry.updated_at = utc_now()
    publication.version += 1
    publication.updated_at = utc_now()
    await db.flush()
    return entry


async def delete_draft_entry(
    db: AsyncSession,
    *,
    company_id: int,
    entry_id: int,
    expected_entry_version: int,
    expected_publication_version: int,
) -> int:
    entry = await db.scalar(
        select(PriceBookEntry)
        .where(
            PriceBookEntry.company_id == int(company_id),
            PriceBookEntry.id == int(entry_id),
        )
        .with_for_update()
    )
    if entry is None:
        raise PricingError(
            "PRICE_ENTRY_NOT_FOUND",
            "إدخال السعر غير موجود.",
            status_code=404,
        )
    if entry.is_published:
        raise PricingError(
            "PRICE_ENTRY_IMMUTABLE",
            "السعر المنشور immutable ولا يحذف.",
        )
    publication = await _draft_publication(
        db,
        company_id=company_id,
        publication_id=int(entry.publication_id),
        expected_version=expected_publication_version,
    )
    if int(entry.version) != int(expected_entry_version):
        raise PricingError(
            "PRICE_ENTRY_VERSION_CONFLICT",
            "تغير إدخال السعر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(entry.version)},
        )
    await db.delete(entry)
    publication.version += 1
    publication.updated_at = utc_now()
    await db.flush()
    return int(publication.version)


async def _validate_publication_entries(
    db: AsyncSession,
    *,
    company_id: int,
    publication: PricePublication,
) -> list[PriceBookEntry]:
    entries = list(
        (
            await db.scalars(
                select(PriceBookEntry)
                .where(
                    PriceBookEntry.company_id == int(company_id),
                    PriceBookEntry.publication_id == int(publication.id),
                )
                .order_by(
                    PriceBookEntry.product_variant_id,
                    PriceBookEntry.uom_id,
                    func.lower(PriceBookEntry.effectivity),
                    PriceBookEntry.id,
                )
                .with_for_update()
            )
        ).all()
    )
    if not entries:
        raise PricingError(
            "PRICE_PUBLICATION_EMPTY",
            "لا يمكن نشر نسخة أسعار بلا إدخالات.",
        )
    if publication.effective_at is None:
        raise PricingError(
            "PRICE_PUBLICATION_EFFECTIVE_AT_REQUIRED",
            "effective_at مطلوب قبل النشر.",
        )

    variant_ids = sorted({int(row.product_variant_id) for row in entries})
    variant_rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.base_uom_id,
                ProductVariant.lifecycle_status,
            ).where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id.in_(variant_ids),
            )
        )
    ).all()
    variants = {
        int(row.id): (int(row.base_uom_id), str(row.lifecycle_status))
        for row in variant_rows
    }
    conversion_rows = (
        await db.execute(
            select(
                ProductUomConversion.product_variant_id,
                ProductUomConversion.from_uom_id,
                ProductUomConversion.to_uom_id,
            ).where(
                ProductUomConversion.company_id == int(company_id),
                ProductUomConversion.product_variant_id.in_(variant_ids),
            )
        )
    ).all()
    mapped: dict[int, set[int]] = {
        variant_id: {base_uom}
        for variant_id, (base_uom, _) in variants.items()
    }
    for row in conversion_rows:
        mapped.setdefault(int(row.product_variant_id), set()).update(
            {int(row.from_uom_id), int(row.to_uom_id)}
        )

    grouped: dict[tuple[int, int], list[PriceBookEntry]] = {}
    for entry in entries:
        variant_id = int(entry.product_variant_id)
        uom_id = int(entry.uom_id)
        variant = variants.get(variant_id)
        if variant is None or variant[1] not in {"ACTIVE", "RETIRING"}:
            raise PricingError(
                "PRODUCT_NOT_OPERATIONAL",
                "نسخة السعر تحتوي SKU غير صالح للنشر التجاري.",
                context={"product_variant_id": variant_id},
            )
        if uom_id not in mapped.get(variant_id, set()):
            raise PricingError(
                "PRICE_UOM_MAPPING_UNRESOLVED",
                "نسخة السعر تحتوي UOM غير مرتبط بالـSKU.",
                context={"product_variant_id": variant_id, "uom_id": uom_id},
            )
        if entry.effectivity.lower < publication.effective_at:
            raise PricingError(
                "PRICE_EFFECTIVITY_BEFORE_PUBLICATION",
                "بداية سعر إدخال تسبق effective_at لنسخة النشر.",
                context={"entry_id": int(entry.id)},
            )
        grouped.setdefault((variant_id, uom_id), []).append(entry)

    for pair, rows in grouped.items():
        previous = None
        for row in rows:
            if previous is not None:
                if previous.effectivity.upper is None or (
                    row.effectivity.lower < previous.effectivity.upper
                ):
                    raise PricingError(
                        "PRICE_EFFECTIVITY_CONFLICT",
                        "نسخة النشر تحتوي فترات أسعار متداخلة لنفس SKU/UOM.",
                        context={
                            "product_variant_id": pair[0],
                            "uom_id": pair[1],
                            "entry_ids": [int(previous.id), int(row.id)],
                        },
                    )
            previous = row
    return entries


async def submit_publication(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    publication_id: int,
    expected_version: int,
) -> PricePublication:
    await acquire_pricing_company_lock(db, company_id)
    if not await maker_checker_enabled(db, company_id):
        raise PricingError(
            "PRICING_APPROVAL_NOT_ENABLED",
            "Maker/Checker غير مفعّل؛ استخدم أمر النشر المباشر.",
        )
    row = await db.scalar(
        select(PricePublication)
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.id == int(publication_id),
        )
        .with_for_update()
    )
    if row is None:
        raise PricingError("PRICE_PUBLICATION_NOT_FOUND", "نسخة النشر غير موجودة.", status_code=404)
    if row.status != "DRAFT":
        raise PricingError(
            "PRICE_PUBLICATION_STATE_CONFLICT",
            "فقط DRAFT يمكن إرساله للموافقة.",
            context={"status": row.status},
        )
    if int(row.version) != int(expected_version):
        raise PricingError(
            "PRICE_PUBLICATION_VERSION_CONFLICT",
            "تغيرت نسخة النشر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(row.version)},
        )
    await _active_book(db, company_id=company_id, book_id=int(row.price_book_id), lock=True)
    await _validate_publication_entries(db, company_id=company_id, publication=row)
    row.status = "PENDING_APPROVAL"
    row.version += 1
    row.updated_at = utc_now()
    await db.flush()
    return row


async def _close_predecessor_ranges(
    db: AsyncSession,
    *,
    company_id: int,
    publication: PricePublication,
) -> None:
    locked_context_conflict = await db.scalar(
        text(
            """
            WITH new_starts AS (
                SELECT
                    product_variant_id,
                    uom_id,
                    MIN(lower(effectivity)) AS new_start
                FROM price_book_entries
                WHERE company_id = :company_id
                  AND publication_id = :publication_id
                GROUP BY product_variant_id, uom_id
            ),
            candidates AS (
                SELECT
                    old.id,
                    old.company_id,
                    old.price_book_id,
                    old.publication_id,
                    old.effectivity,
                    ns.new_start
                FROM price_book_entries AS old
                JOIN new_starts AS ns
                  ON ns.product_variant_id = old.product_variant_id
                 AND ns.uom_id = old.uom_id
                WHERE old.company_id = :company_id
                  AND old.price_book_id = :price_book_id
                  AND old.publication_id <> :publication_id
                  AND old.is_published IS TRUE
                  AND upper_inf(old.effectivity)
                  AND lower(old.effectivity) < ns.new_start
            )
            SELECT EXISTS (
                SELECT 1
                FROM candidates AS candidate
                JOIN price_publications AS old_publication
                  ON old_publication.company_id = candidate.company_id
                 AND old_publication.id = candidate.publication_id
                 AND old_publication.price_book_id = candidate.price_book_id
                JOIN route_commercial_contexts AS context
                  ON context.company_id = candidate.company_id
                WHERE old_publication.published_at IS NOT NULL
                  AND old_publication.published_at <= context.pricing_locked_at
                  AND old_publication.revision
                      <= context.price_publication_revision
                  AND candidate.effectivity @> context.pricing_locked_at
                  AND context.pricing_locked_at >= candidate.new_start
                  AND EXISTS (
                        SELECT 1
                        FROM price_book_assignments AS assignment
                        WHERE assignment.company_id = candidate.company_id
                          AND assignment.price_book_id = candidate.price_book_id
                          AND assignment.revision
                              <= context.assignment_revision
                          AND assignment.effectivity
                              @> context.pricing_locked_at
                  )
            )
            """
        ),
        {
            "company_id": int(company_id),
            "publication_id": int(publication.id),
            "price_book_id": int(publication.price_book_id),
        },
    )
    if locked_context_conflict:
        raise PricingError(
            "COMMERCIAL_CONTEXT_LOCKED",
            "لا يمكن نشر هذه النسخة لأن إغلاق السعر السابق سيغير التاريخ التجاري لمسار تم قفله مسبقاً.",
            context={
                "publication_id": int(publication.id),
                "price_book_id": int(publication.price_book_id),
            },
        )

    now = utc_now()
    await db.execute(
        text(
            """
            WITH new_starts AS (
                SELECT
                    product_variant_id,
                    uom_id,
                    MIN(lower(effectivity)) AS new_start
                FROM price_book_entries
                WHERE company_id = :company_id
                  AND publication_id = :publication_id
                GROUP BY product_variant_id, uom_id
            ),
            candidates AS (
                SELECT old.id, ns.new_start
                FROM price_book_entries AS old
                JOIN new_starts AS ns
                  ON ns.product_variant_id = old.product_variant_id
                 AND ns.uom_id = old.uom_id
                WHERE old.company_id = :company_id
                  AND old.price_book_id = :price_book_id
                  AND old.publication_id <> :publication_id
                  AND old.is_published IS TRUE
                  AND upper_inf(old.effectivity)
                  AND lower(old.effectivity) < ns.new_start
            )
            UPDATE price_book_entries AS old
            SET effectivity = tstzrange(
                    lower(old.effectivity),
                    candidates.new_start,
                    '[)'
                ),
                version = old.version + 1,
                updated_at = :updated_at
            FROM candidates
            WHERE old.id = candidates.id
            """
        ),
        {
            "company_id": int(company_id),
            "publication_id": int(publication.id),
            "price_book_id": int(publication.price_book_id),
            "updated_at": now,
        },
    )

    conflict = await db.scalar(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM price_book_entries AS old
                JOIN price_book_entries AS fresh
                  ON fresh.company_id = old.company_id
                 AND fresh.price_book_id = old.price_book_id
                 AND fresh.product_variant_id = old.product_variant_id
                 AND fresh.uom_id = old.uom_id
                 AND fresh.publication_id = :publication_id
                WHERE old.company_id = :company_id
                  AND old.price_book_id = :price_book_id
                  AND old.publication_id <> :publication_id
                  AND old.is_published IS TRUE
                  AND old.effectivity && fresh.effectivity
            )
            """
        ),
        {
            "company_id": int(company_id),
            "price_book_id": int(publication.price_book_id),
            "publication_id": int(publication.id),
        },
    )
    if conflict:
        raise PricingError(
            "PRICE_EFFECTIVITY_CONFLICT",
            "يوجد سعر منشور متداخل لا يمكن إغلاقه تلقائياً دون تغيير التاريخ.",
            context={"publication_id": int(publication.id)},
        )


async def _publish_locked(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    publication: PricePublication,
) -> PricePublication:
    await _active_book(
        db,
        company_id=company_id,
        book_id=int(publication.price_book_id),
        lock=True,
    )
    await _validate_publication_entries(
        db, company_id=company_id, publication=publication
    )
    await _close_predecessor_ranges(
        db, company_id=company_id, publication=publication
    )

    now = utc_now()
    await db.execute(
        update(PriceBookEntry)
        .where(
            PriceBookEntry.company_id == int(company_id),
            PriceBookEntry.publication_id == int(publication.id),
            PriceBookEntry.is_published.is_(False),
        )
        .values(
            is_published=True,
            version=PriceBookEntry.version + 1,
            updated_at=now,
        )
    )

    await db.execute(
        update(PricePublication)
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.price_book_id == int(publication.price_book_id),
            PricePublication.status == "PUBLISHED",
            PricePublication.id != int(publication.id),
        )
        .values(
            status="SUPERSEDED",
            version=PricePublication.version + 1,
            updated_at=now,
        )
    )

    publication.status = "PUBLISHED"
    publication.approved_by = int(actor_id)
    publication.approved_at = now
    publication.published_at = now
    publication.version += 1
    publication.updated_at = now
    await db.flush()
    return publication


async def publish_publication(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    publication_id: int,
    expected_version: int,
) -> PricePublication:
    await acquire_pricing_company_lock(db, company_id)
    if await maker_checker_enabled(db, company_id):
        raise PricingError(
            "PRICING_APPROVAL_REQUIRED",
            "Maker/Checker مفعّل؛ يجب Submit ثم Approve.",
        )
    row = await db.scalar(
        select(PricePublication)
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.id == int(publication_id),
        )
        .with_for_update()
    )
    if row is None:
        raise PricingError("PRICE_PUBLICATION_NOT_FOUND", "نسخة النشر غير موجودة.", status_code=404)
    if row.status != "DRAFT":
        raise PricingError(
            "PRICE_PUBLICATION_STATE_CONFLICT",
            "النشر المباشر مسموح من DRAFT فقط.",
            context={"status": row.status},
        )
    if int(row.version) != int(expected_version):
        raise PricingError(
            "PRICE_PUBLICATION_VERSION_CONFLICT",
            "تغيرت نسخة النشر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(row.version)},
        )
    return await _publish_locked(
        db,
        company_id=company_id,
        actor_id=actor_id,
        publication=row,
    )


async def approve_publication(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    publication_id: int,
    expected_version: int,
) -> PricePublication:
    await acquire_pricing_company_lock(db, company_id)
    if not await maker_checker_enabled(db, company_id):
        raise PricingError(
            "PRICING_APPROVAL_NOT_ENABLED",
            "Maker/Checker غير مفعّل.",
        )
    row = await db.scalar(
        select(PricePublication)
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.id == int(publication_id),
        )
        .with_for_update()
    )
    if row is None:
        raise PricingError("PRICE_PUBLICATION_NOT_FOUND", "نسخة النشر غير موجودة.", status_code=404)
    if row.status != "PENDING_APPROVAL":
        raise PricingError(
            "PRICE_PUBLICATION_STATE_CONFLICT",
            "يمكن اعتماد نسخة PENDING_APPROVAL فقط.",
            context={"status": row.status},
        )
    if int(row.version) != int(expected_version):
        raise PricingError(
            "PRICE_PUBLICATION_VERSION_CONFLICT",
            "تغيرت نسخة النشر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(row.version)},
        )
    if int(row.created_by) == int(actor_id):
        raise PricingError(
            "PRICING_SEPARATION_OF_DUTIES",
            "منشئ نسخة السعر لا يجوز أن يعتمدها عند تفعيل Maker/Checker.",
        )
    return await _publish_locked(
        db,
        company_id=company_id,
        actor_id=actor_id,
        publication=row,
    )


async def cancel_publication(
    db: AsyncSession,
    *,
    company_id: int,
    publication_id: int,
    expected_version: int,
) -> PricePublication:
    await acquire_pricing_company_lock(db, company_id)
    row = await db.scalar(
        select(PricePublication)
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.id == int(publication_id),
        )
        .with_for_update()
    )
    if row is None:
        raise PricingError("PRICE_PUBLICATION_NOT_FOUND", "نسخة النشر غير موجودة.", status_code=404)
    if row.status not in {"DRAFT", "PENDING_APPROVAL"}:
        raise PricingError(
            "PRICE_PUBLICATION_STATE_CONFLICT",
            "لا يمكن إلغاء نسخة منشورة أو مستبدلة.",
            context={"status": row.status},
        )
    if int(row.version) != int(expected_version):
        raise PricingError(
            "PRICE_PUBLICATION_VERSION_CONFLICT",
            "تغيرت نسخة النشر؛ حدّث البيانات وأعد المحاولة.",
            context={"current_version": int(row.version)},
        )
    row.status = "CANCELLED"
    row.version += 1
    row.updated_at = utc_now()
    await db.flush()
    return row


async def _validate_assignment_scope(
    db: AsyncSession,
    *,
    company_id: int,
    scope_type: str,
    scope_id: Optional[int],
) -> None:
    scope_type = str(scope_type).upper()
    if scope_type in RESERVED_ASSIGNMENT_SCOPES:
        raise PricingError(
            "PRICE_ASSIGNMENT_SCOPE_RESERVED",
            "هذا النطاق محجوز حتى إنشاء كيانه الحقيقي في النظام.",
            status_code=422,
            context={"scope_type": scope_type},
        )
    if scope_type not in SUPPORTED_ASSIGNMENT_SCOPES:
        raise PricingError(
            "PRICE_ASSIGNMENT_SCOPE_INVALID",
            "نطاق ربط دفتر الأسعار غير صالح.",
            status_code=422,
            context={"scope_type": scope_type},
        )
    if scope_type == "COMPANY_DEFAULT":
        if scope_id is not None:
            raise PricingError(
                "PRICE_ASSIGNMENT_SCOPE_INVALID",
                "COMPANY_DEFAULT لا يقبل scope_id.",
                status_code=422,
            )
        return
    if scope_id is None or int(scope_id) <= 0:
        raise PricingError(
            "PRICE_ASSIGNMENT_SCOPE_INVALID",
            "scope_id مطلوب لهذا النطاق.",
            status_code=422,
        )
    if scope_type == "CUSTOMER":
        exists = await db.scalar(
            select(Shop.id).where(
                Shop.company_id == int(company_id),
                Shop.id == int(scope_id),
            )
        )
    else:
        exists = await db.scalar(
            select(Branch.id).where(
                Branch.company_id == int(company_id),
                Branch.id == int(scope_id),
            )
        )
    if exists is None:
        raise PricingError(
            "PRICE_ASSIGNMENT_SCOPE_NOT_FOUND",
            "النطاق المطلوب غير موجود داخل الشركة.",
            status_code=404,
            context={"scope_type": scope_type, "scope_id": int(scope_id)},
        )


async def create_assignment(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    price_book_id: int,
    scope_type: str,
    scope_id: Optional[int],
    allow_offers: bool,
    priority: int,
    effective_from: datetime,
    effective_to: Optional[datetime],
) -> PriceBookAssignment:
    await acquire_pricing_company_lock(db, company_id)
    await _active_book(
        db, company_id=company_id, book_id=price_book_id, lock=True
    )
    scope_type = str(scope_type).upper()
    await _validate_assignment_scope(
        db,
        company_id=company_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    effectivity = _range(
        effective_from, effective_to, field_prefix="assignment_effectivity"
    )

    stmt = (
        select(PriceBookAssignment)
        .where(
            PriceBookAssignment.company_id == int(company_id),
            PriceBookAssignment.scope_type == scope_type,
            PriceBookAssignment.priority == int(priority),
            PriceBookAssignment.effectivity.op("&&")(effectivity),
        )
        .with_for_update()
    )
    if scope_type == "COMPANY_DEFAULT":
        stmt = stmt.where(PriceBookAssignment.scope_id.is_(None))
    else:
        stmt = stmt.where(PriceBookAssignment.scope_id == int(scope_id))
    overlaps = list((await db.scalars(stmt)).all())

    if overlaps:
        if (
            len(overlaps) == 1
            and overlaps[0].effectivity.upper is None
            and overlaps[0].effectivity.lower < effectivity.lower
        ):
            old = overlaps[0]
            locked_context_id = await db.scalar(
                select(RouteCommercialContext.id)
                .where(
                    RouteCommercialContext.company_id == int(company_id),
                    RouteCommercialContext.assignment_revision
                    >= int(old.revision),
                    RouteCommercialContext.pricing_locked_at
                    >= effectivity.lower,
                )
                .order_by(RouteCommercialContext.id.asc())
                .limit(1)
            )
            if locked_context_id is not None:
                raise PricingError(
                    "COMMERCIAL_CONTEXT_LOCKED",
                    "لا يمكن إغلاق Assignment السابق بهذا التاريخ لأنه سيغير سياقاً تجارياً لمسار تم قفله مسبقاً.",
                    context={
                        "assignment_id": int(old.id),
                        "commercial_context_id": int(locked_context_id),
                        "requested_effective_from": effectivity.lower.isoformat(),
                    },
                )

            old.effectivity = Range(
                old.effectivity.lower, effectivity.lower, bounds="[)"
            )
            old.version += 1
            old.updated_at = utc_now()
            await db.flush()
        else:
            raise PricingError(
                "PRICE_EFFECTIVITY_CONFLICT",
                "يوجد Assignment متداخل لا يمكن تغييره دون المساس بالتاريخ.",
                context={
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "priority": int(priority),
                },
            )

    revision = await next_assignment_revision(db, company_id)
    row = PriceBookAssignment(
        company_id=int(company_id),
        price_book_id=int(price_book_id),
        scope_type=scope_type,
        scope_id=int(scope_id) if scope_id is not None else None,
        allow_offers=bool(allow_offers),
        priority=int(priority),
        effectivity=effectivity,
        revision=revision,
        version=1,
        created_by=int(actor_id),
    )
    db.add(row)
    await db.flush()
    return row
