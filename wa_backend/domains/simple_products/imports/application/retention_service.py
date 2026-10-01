"""Product Import retention orchestration and bounded tenant scheduling."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select

from database import AsyncSessionLocal
from domains.simple_products.imports.application.source_store import (
    TransactionalSourceStore,
)
from domains.simple_products.imports.domain.retention import (
    DEFAULT_PRODUCT_IMPORT_RETENTION,
    ProductImportRetentionPolicy,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)
from domains.simple_products.imports.infrastructure.retention_repository import (
    clear_expired_source_payloads,
    compact_expired_row_details,
    delete_expired_row_lineage,
    clear_expired_stored_sources,
)
from models import Company


RETENTION_COMPANY_PAGE = 1_000


@dataclass(slots=True)
class ProductImportRetentionResult:
    company_id: int
    payloads_cleared: int = 0
    rows_compacted: int = 0
    barcode_rows_pruned: int = 0
    lineage_rows_deleted: int = 0
    committed_batches: int = 0
    batch_limit_reached: bool = False

    def as_dict(
        self,
    ) -> dict[str, int | bool]:
        return asdict(
            self
        )


def _utc_naive_now() -> datetime:
    return (
        datetime.now(
            timezone.utc
        )
        .replace(
            tzinfo=None
        )
    )


async def iter_retention_company_id_pages(
    *,
    page_size: int =
        RETENTION_COMPANY_PAGE,
) -> AsyncIterator[list[int]]:
    if (
        isinstance(
            page_size,
            bool,
        )
        or not isinstance(
            page_size,
            int,
        )
        or page_size <= 0
        or page_size > 5_000
    ):
        raise ValueError(
            "page_size must be between 1 and 5000."
        )

    after_company_id = 0
    while True:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    Company.id
                )
                .where(
                    Company.id
                    > after_company_id
                )
                .order_by(
                    Company.id.asc()
                )
                .limit(
                    int(
                        page_size
                    )
                )
            )
            company_ids = [
                int(
                    value
                )
                for value in result.scalars().fetchmany(
                    int(
                        page_size
                    )
                )
            ]
            if db.in_transaction():
                await db.rollback()

        if not company_ids:
            break

        yield company_ids
        after_company_id = (
            company_ids[
                -1
            ]
        )
        if len(
            company_ids
        ) < int(
            page_size
        ):
            break


async def run_product_import_retention(
    *,
    company_id: int,
    policy: ProductImportRetentionPolicy =
        DEFAULT_PRODUCT_IMPORT_RETENTION,
    now: datetime | None = None,
    source_store: TransactionalSourceStore | None = None,
) -> dict[str, int | bool]:
    effective_now = (
        now
        if now is not None
        else _utc_naive_now()
    )
    if effective_now.tzinfo is not None:
        effective_now = (
            effective_now
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

    result = ProductImportRetentionResult(
        company_id=int(
            company_id
        )
    )
    token, db = await open_tenant_session(
        int(
            company_id
        )
    )
    try:
        source_cutoff = (
            effective_now
            - policy.upload_bytes
        )
        detail_cutoff = (
            effective_now
            - policy.full_row_detail
        )
        lineage_cutoff = (
            effective_now
            - policy.compact_lineage
        )

        async def commit_batch() -> None:
            await db.commit()
            result.committed_batches += 1

        if source_store is not None:
            # Tenant setup did not lock business rows. Source cleanup uses one
            # caller-owned SourceStore transaction, including job markers.
            if db.in_transaction():
                await db.rollback()
            for batch_index in range(policy.max_batches_per_run):
                marked = await clear_expired_stored_sources(
                    company_id=int(company_id), cutoff=source_cutoff,
                    limit=policy.batch_size, source_store=source_store,
                )
                if not marked:
                    break
                result.committed_batches += 1
                result.payloads_cleared += marked
                if marked < policy.batch_size:
                    break
                if batch_index == policy.max_batches_per_run - 1:
                    result.batch_limit_reached = True

        for batch_index in range(
            policy.max_batches_per_run
        ):
            cleared = (
                await clear_expired_source_payloads(
                    db,
                    company_id=
                        int(
                            company_id
                        ),
                    cutoff=
                        source_cutoff,
                    limit=
                        policy.batch_size,
                )
            )
            await commit_batch()
            result.payloads_cleared += (
                cleared
            )
            if (
                cleared
                < policy.batch_size
            ):
                break
            if (
                batch_index
                == policy.max_batches_per_run
                - 1
            ):
                result.batch_limit_reached = (
                    True
                )

        # Delete lineage already beyond its final retention window before
        # spending work compacting it.
        for batch_index in range(
            policy.max_batches_per_run
        ):
            deleted = (
                await delete_expired_row_lineage(
                    db,
                    company_id=
                        int(
                            company_id
                        ),
                    cutoff=
                        lineage_cutoff,
                    limit=
                        policy.batch_size,
                )
            )
            await commit_batch()
            result.lineage_rows_deleted += (
                deleted
            )
            if (
                deleted
                < policy.batch_size
            ):
                break
            if (
                batch_index
                == policy.max_batches_per_run
                - 1
            ):
                result.batch_limit_reached = (
                    True
                )

        for batch_index in range(
            policy.max_batches_per_run
        ):
            (
                compacted,
                pruned_barcodes,
            ) = (
                await compact_expired_row_details(
                    db,
                    company_id=
                        int(
                            company_id
                        ),
                    cutoff=
                        detail_cutoff,
                    limit=
                        policy.batch_size,
                )
            )
            await commit_batch()
            result.rows_compacted += (
                compacted
            )
            result.barcode_rows_pruned += (
                pruned_barcodes
            )
            if (
                compacted
                < policy.batch_size
            ):
                break
            if (
                batch_index
                == policy.max_batches_per_run
                - 1
            ):
                result.batch_limit_reached = (
                    True
                )

        return result.as_dict()
    except Exception:
        await db.rollback()
        raise
    finally:
        await close_tenant_session(
            token,
            db,
        )
