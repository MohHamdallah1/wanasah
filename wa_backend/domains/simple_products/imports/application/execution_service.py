"""Best-effort Product Import execution.

Validation-invalid rows never enter execution. Valid rows are processed in
bounded transactions. Deterministic row-level execution failures are isolated
with savepoints and recorded as IMPORT_FAILED; unexpected/system failures still
abort the job so the queue/runtime failure path can handle them.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    RowStatus,
    transition_job,
    transition_row,
    utc_naive_now,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.domain.errors import (
    ProductImportRowExecutionError,
)
from domains.simple_products.imports.infrastructure.repository import (
    ProductImportProgress,
    close_tenant_session,
    count_job_progress,
    list_job_rows,
    load_active_actor,
    load_job,
    open_tenant_session,
)
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    create_products_and_prices,
)
from services import (
    begin_idempotent_operation,
    complete_idempotent_operation,
)
from inventory_access import InventoryAccess


IMPORT_BATCH = 100
_ROW_CREATE_OPERATION = "PRODUCT_IMPORT_ROW_CREATE"


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


def _constraint_name(
    exc: IntegrityError,
) -> str | None:
    original = getattr(
        exc,
        "orig",
        None,
    )
    for candidate in (
        getattr(
            original,
            "constraint_name",
            None,
        ),
        getattr(
            getattr(
                original,
                "diag",
                None,
            ),
            "constraint_name",
            None,
        ),
    ):
        if candidate:
            return str(candidate)

    message = str(exc)
    if (
        "uq_active_product_barcode"
        in message
    ):
        return (
            "uq_active_product_barcode"
        )
    return None


def classify_execution_row_error(
    exc: Exception,
) -> ProductImportRowExecutionError | None:
    if isinstance(
        exc,
        SimpleProductError,
    ):
        if int(
            exc.status_code
        ) >= 500:
            return None
        return ProductImportRowExecutionError(
            exc.code,
            exc.message,
        )

    if isinstance(
        exc,
        IntegrityError,
    ) and (
        _constraint_name(exc)
        == "uq_active_product_barcode"
    ):
        return ProductImportRowExecutionError(
            "IMPORT_BARCODE_CONFLICT",
            "Barcode is already active.",
        )

    return None


def completion_outcome(
    progress: ProductImportProgress,
) -> JobStatus:
    if int(
        progress.pending_rows
    ) != 0:
        raise ProductImportTerminalError(
            "Product import cannot be finalized while rows are still pending."
        )

    if (
        int(
            progress.invalid_rows
        )
        > 0
        or int(
            progress.import_failed_rows
        )
        > 0
    ):
        return (
            JobStatus.COMPLETED_WITH_ERRORS
        )

    return JobStatus.COMPLETED


def _row_identity(
    row: Any,
) -> str:
    value = getattr(
        row,
        "row_identity",
        None,
    )
    if value is None:
        raise ProductImportTerminalError(
            "Product Import row identity is missing."
        )
    return str(value)


def _batch_request_id(
    job_id: UUID,
    rows: list[Any],
) -> UUID:
    identities = ",".join(
        _row_identity(row)
        for row in rows
    )
    return uuid5(
        job_id,
        "product-import-rows:"
        + identities,
    )


def _batch_request_hash(
    rows: list[Any],
) -> str:
    payload = [
        {
            "row_identity":
                _row_identity(row),
            "normalized_data":
                dict(
                    row.normalized_data
                    or {}
                ),
        }
        for row in rows
    ]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        canonical
    ).hexdigest()


def _replayed_variant_ids(
    replay: dict[str, object],
    rows: list[Any],
) -> list[int]:
    stored = replay.get(
        "rows"
    )
    if not isinstance(
        stored,
        list,
    ):
        raise ProductImportTerminalError(
            "Product Import idempotency response is malformed."
        )

    by_identity: dict[
        str,
        int,
    ] = {}
    for item in stored:
        if not isinstance(
            item,
            dict,
        ):
            raise ProductImportTerminalError(
                "Product Import idempotency response is malformed."
            )
        identity = str(
            item.get(
                "row_identity",
                "",
            )
        )
        variant_id = item.get(
            "product_variant_id"
        )
        if (
            not identity
            or isinstance(
                variant_id,
                bool,
            )
            or not isinstance(
                variant_id,
                int,
            )
            or int(
                variant_id
            )
            <= 0
            or identity
            in by_identity
        ):
            raise ProductImportTerminalError(
                "Product Import idempotency response is malformed."
            )
        by_identity[
            identity
        ] = int(
            variant_id
        )

    expected = [
        _row_identity(
            row
        )
        for row in rows
    ]
    if set(
        by_identity
    ) != set(
        expected
    ):
        raise ProductImportTerminalError(
            "Product Import idempotency response does not match the requested rows."
        )

    return [
        by_identity[
            identity
        ]
        for identity
        in expected
    ]


async def _execute_rows_once(
    db,
    *,
    actor,
    job_id: UUID,
    rows: list[Any],
) -> None:
    specs = [
        build_product_spec(
            dict(
                row.normalized_data
                or {}
            )
        )
        for row in rows
    ]
    request_id = _batch_request_id(
        job_id,
        rows,
    )
    request_hash = (
        _batch_request_hash(
            rows
        )
    )

    (
        idempotency,
        replay,
    ) = await begin_idempotent_operation(
        db,
        company_id=int(
            actor.company_id
        ),
        actor_id=int(
            actor.id
        ),
        operation=
            _ROW_CREATE_OPERATION,
        request_id=str(
            request_id
        ),
        request_hash=
            request_hash,
    )

    if replay is not None:
        variant_ids = (
            _replayed_variant_ids(
                replay,
                rows,
            )
        )
        for (
            row,
            variant_id,
        ) in zip(
            rows,
            variant_ids,
            strict=True,
        ):
            transition_row(
                row,
                RowStatus.IMPORTED,
                product_variant_id=
                    int(
                        variant_id
                    ),
                error_code=None,
                error_message=None,
            )
        return

    created = (
        await create_products_and_prices(
            db,
            actor=actor,
            request_id=request_id,
            specs=specs,
        )
    )

    response_rows: list[
        dict[str, object]
    ] = []
    for (
        row,
        (variant, _prices),
    ) in zip(
        rows,
        created,
        strict=True,
    ):
        variant_id = int(
            variant.id
        )
        response_rows.append(
            {
                "row_identity":
                    _row_identity(
                        row
                    ),
                "product_variant_id":
                    variant_id,
            }
        )
        transition_row(
            row,
            RowStatus.IMPORTED,
            product_variant_id=
                variant_id,
            error_code=None,
            error_message=None,
        )

    complete_idempotent_operation(
        idempotency,
        {
            "rows":
                response_rows,
        },
    )


async def _execute_rows_best_effort(
    db,
    *,
    actor,
    job_id: UUID,
    rows: list[Any],
) -> tuple[int, int]:
    try:
        async with db.begin_nested():
            await _execute_rows_once(
                db,
                actor=actor,
                job_id=job_id,
                rows=rows,
            )
        return (
            len(rows),
            0,
        )
    except Exception as exc:
        row_error = (
            classify_execution_row_error(
                exc
            )
        )
        if row_error is None:
            raise

        if len(rows) == 1:
            transition_row(
                rows[0],
                RowStatus.IMPORT_FAILED,
                product_variant_id=None,
                error_code=
                    row_error.code,
                error_message=
                    row_error.message,
            )
            return (
                0,
                1,
            )

        midpoint = (
            len(rows)
            // 2
        )
        left = (
            await _execute_rows_best_effort(
                db,
                actor=actor,
                job_id=job_id,
                rows=rows[
                    :midpoint
                ],
            )
        )
        right = (
            await _execute_rows_best_effort(
                db,
                actor=actor,
                job_id=job_id,
                rows=rows[
                    midpoint:
                ],
            )
        )
        return (
            left[0]
            + right[0],
            left[1]
            + right[1],
        )


def _completion_summary(
    progress: ProductImportProgress,
) -> dict[str, object]:
    if (
        progress.invalid_rows == 0
        and progress.import_failed_rows
        == 0
    ):
        return {}

    return {
        "code":
            "PRODUCT_IMPORT_COMPLETED_WITH_ERRORS",
        "imported_rows":
            int(
                progress.imported_rows
            ),
        "invalid_rows":
            int(
                progress.invalid_rows
            ),
        "import_failed_rows":
            int(
                progress.import_failed_rows
            ),
    }


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
            if (
                str(job.status)
                == JobStatus.CANCELLED.value
            ):
                await db.rollback()
                return
            if (
                str(job.status)
                != JobStatus.IMPORTING.value
            ):
                raise ProductImportTerminalError(
                    "Product import execution can only run from IMPORTING state."
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
                status=RowStatus.VALID.value,
                limit=IMPORT_BATCH,
                for_update_skip_locked=True,
            )

            if not rows:
                progress = (
                    await count_job_progress(
                        db,
                        company_id=
                            company_id,
                        job_id=job_id,
                    )
                )

                if (
                    progress.total_rows
                    != int(
                        job.total_rows
                    )
                ):
                    raise ProductImportTerminalError(
                        "Product import outcome counts do not match the staged import total."
                    )

                if (
                    progress.pending_rows
                    > 0
                ):
                    # Another delivery may currently own the remaining
                    # SKIP LOCKED rows. Never finalize while durable pending
                    # outcomes still exist.
                    await db.rollback()
                    return

                target = (
                    completion_outcome(
                        progress
                    )
                )
                transition_job(
                    job,
                    target,
                    touch_updated_at=False,
                    processed_rows=int(
                        progress.imported_rows
                    ),
                    finished_at=
                        utc_naive_now(),
                    error_summary=
                        _completion_summary(
                            progress
                        ),
                )

                await db.commit()
                return

            (
                imported_delta,
                _failed_delta,
            ) = await _execute_rows_best_effort(
                db,
                actor=actor,
                job_id=job_id,
                rows=rows,
            )

            # Do not rescan the whole staged job after every bounded batch.
            # The job row is locked by this transaction, so the durable
            # imported counter can advance by the committed batch delta.
            # One authoritative aggregate scan remains at finalization.
            transition_job(
                job,
                JobStatus.IMPORTING,
                processed_rows=(
                    int(
                        job.processed_rows
                    )
                    + int(
                        imported_delta
                    )
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
