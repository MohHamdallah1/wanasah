"""Authorized Product Import lineage application service."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domains.simple_products.imports.domain.retention import (
    DEFAULT_PRODUCT_IMPORT_RETENTION,
)
from domains.simple_products.imports.infrastructure.audit_repository import (
    fetch_import_lineage_page,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)


def _iso(
    value,
) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _lineage_expired(
    *,
    finished_at: datetime | None,
    has_rows: bool,
) -> bool:
    if (
        has_rows
        or finished_at is None
    ):
        return False

    now = (
        datetime.now(
            timezone.utc
        )
        .replace(
            tzinfo=None
        )
    )
    return (
        finished_at
        <= (
            now
            - DEFAULT_PRODUCT_IMPORT_RETENTION.compact_lineage
        )
    )


async def get_import_lineage(
    *,
    company_id: int,
    job_id: UUID,
    after_row_number: int = 0,
    limit: int = 100,
) -> dict[str, object] | None:
    token, db = await open_tenant_session(
        int(
            company_id
        )
    )
    try:
        (
            job,
            rows,
            has_more,
        ) = await fetch_import_lineage_page(
            db,
            company_id=int(
                company_id
            ),
            job_id=job_id,
            after_row_number=
                int(
                    after_row_number
                ),
            limit=int(
                limit
            ),
        )
        if job is None:
            return None

        items = [
            {
                "row_number":
                    int(
                        row.row_number
                    ),
                "row_identity":
                    str(
                        row.row_identity
                    ),
                "status":
                    str(
                        row.status
                    ),
                "product_variant_id": (
                    int(
                        row.product_variant_id
                    )
                    if row.product_variant_id
                    is not None
                    else None
                ),
                "error_code":
                    row.error_code,
                "error_message":
                    row.error_message,
                "raw_data":
                    dict(
                        row.raw_data
                        or {}
                    ),
                "normalized_data":
                    dict(
                        row.normalized_data
                        or {}
                    ),
                "compacted_at":
                    _iso(
                        row.compacted_at
                    ),
                "created_at":
                    _iso(
                        row.created_at
                    ),
                "updated_at":
                    _iso(
                        row.updated_at
                    ),
            }
            for row in rows
        ]

        return {
            "job_id":
                str(
                    job.id
                ),
            "file_name":
                str(
                    job.file_name
                ),
            "source_sha256":
                str(
                    job.source_sha256
                ),
            "status":
                str(
                    job.status
                ),
            "total_rows":
                int(
                    job.total_rows
                ),
            "processed_rows":
                int(
                    job.processed_rows
                ),
            "valid_rows":
                int(
                    job.valid_rows
                ),
            "failed_rows":
                int(
                    job.failed_rows
                ),
            "source_payload_retained":
                job.source_payload
                is not None,
            "source_payload_cleared_at":
                _iso(
                    job.source_payload_cleared_at
                ),
            "created_at":
                _iso(
                    job.created_at
                ),
            "finished_at":
                _iso(
                    job.finished_at
                ),
            "lineage_expired":
                _lineage_expired(
                    finished_at=
                        job.finished_at,
                    has_rows=
                        bool(
                            items
                        ),
                ),
            "rows":
                items,
            "has_more":
                bool(
                    has_more
                ),
            "next_after_row_number": (
                int(
                    rows[
                        -1
                    ].row_number
                )
                if has_more
                and rows
                else None
            ),
        }
    finally:
        await close_tenant_session(
            token,
            db,
        )
