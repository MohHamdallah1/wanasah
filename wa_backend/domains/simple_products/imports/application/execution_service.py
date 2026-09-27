"""Product Import execution service.

The current batch transaction boundaries and all-or-nothing validation policy
are intentionally preserved during Phase 2.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid5

from fastapi import HTTPException

from domains.simple_products.imports.application.state_machine import (
    transition_job,
    transition_row,
    utc_naive_now,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    count_job_rows,
    delete_job_rows,
    list_job_rows,
    load_active_actor,
    load_job,
    open_tenant_session,
)
from domains.simple_products.service import (
    SimpleProductSpec,
    create_products_and_prices,
)
from inventory_access import InventoryAccess


IMPORT_BATCH = 100


def build_product_spec(
    data: dict[str, object],
) -> SimpleProductSpec:
    return SimpleProductSpec(
        name=str(
            data["name"]
        ),
        family_name=data.get(
            "family_name"
        ),
        package_uom_code=data.get(
            "package_uom_code"
        ),
        units_per_package=int(
            data[
                "units_per_package"
            ]
        ),
        package_price=(
            Decimal(
                str(
                    data[
                        "package_price"
                    ]
                )
            )
            if data.get(
                "package_price"
            )
            is not None
            else None
        ),
        unit_price=Decimal(
            str(
                data[
                    "unit_price"
                ]
            )
        ),
        unit_barcode=data.get(
            "unit_barcode"
        ),
        package_barcode=data.get(
            "package_barcode"
        ),
        lot_control_mode=str(
            data["lot_control_mode"]
        ),
        expiry_control_mode=str(
            data["expiry_control_mode"]
        ),
    )


async def execute_import(
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    while True:
        token, db = await open_tenant_session(
            company_id
        )
        try:
            job = await load_job(
                db,
                company_id=company_id,
                job_id=job_id,
                for_update=True,
            )
            if job is None:
                raise ValueError(
                    "Product import job not found."
                )

            actor = await load_active_actor(
                db,
                company_id=company_id,
                actor_id=int(
                    job.created_by
                ),
            )
            if actor is None:
                raise ProductImportTerminalError(
                    "The import actor is no longer active."
                )

            access = InventoryAccess(
                db,
                actor,
            )
            try:
                for permission in (
                    "catalog.manage",
                    "catalog.publish",
                    "pricing.manage",
                ):
                    await access.require(
                        permission,
                        any_location=True,
                    )
            except HTTPException as exc:
                raise ProductImportTerminalError(
                    "The import actor no longer has the required permissions."
                ) from exc

            rows = await list_job_rows(
                db,
                company_id=company_id,
                job_id=job_id,
                status="VALID",
                limit=IMPORT_BATCH,
                for_update_skip_locked=True,
            )

            if not rows:
                transition_job(
                    job,
                    "COMPLETED",
                    touch_updated_at=False,
                    processed_rows=int(
                        job.valid_rows
                    ),
                    finished_at=
                        utc_naive_now(),
                    error_summary={},
                )

                await delete_job_rows(
                    db,
                    company_id=company_id,
                    job_id=job_id,
                    status="IMPORTED",
                )
                await db.commit()
                return

            specs = [
                build_product_spec(
                    dict(
                        row.normalized_data
                        or {}
                    )
                )
                for row in rows
            ]

            request_id = uuid5(
                job_id,
                (
                    "rows:"
                    f"{int(rows[0].row_number)}:"
                    f"{int(rows[-1].row_number)}"
                ),
            )
            created = (
                await create_products_and_prices(
                    db,
                    actor=actor,
                    request_id=request_id,
                    specs=specs,
                )
            )

            for (
                row,
                (variant, _prices),
            ) in zip(
                rows,
                created,
                strict=True,
            ):
                transition_row(
                    row,
                    "IMPORTED",
                    product_variant_id=int(
                        variant.id
                    ),
                )

            imported = await count_job_rows(
                db,
                company_id=company_id,
                job_id=job_id,
                status="IMPORTED",
            )
            transition_job(
                job,
                "IMPORTING",
                processed_rows=int(
                    imported
                    or 0
                ),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await close_tenant_session(
                token,
                db,
            )
