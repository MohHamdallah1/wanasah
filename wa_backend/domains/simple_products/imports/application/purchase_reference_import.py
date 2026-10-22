"""Bounded, atomic purchase-reference writer for Product Import.

Runs only when at least one validated row contains optional purchase cost.
No changes to import staging, row locks, 200-row batching or worker scheduling.
The owning Product Import transaction commits Product/Pricing/reference/audit once.

Performance rule: all imported reference current-state + immutable history +
idempotency command evidence for one 200-row batch are written by ONE PostgreSQL
statement. The legacy no-cost path never calls this writer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text


def has_import_cost(rows) -> bool:
    return any((row.normalized_data or {}).get("purchase_unit_cost") is not None for row in rows)


async def record_import_reference_batch(
    db, *, access, company_id: int, job_id, request_id, request_hash, rows, created,
) -> None:
    """Store at most 200 explicit base-unit references in one SQL round trip.

    Caller acquires the canonical writer guard before Product/Pricing locks and
    checks MANAGE authorization. The SQL keeps command -> immutable history ->
    current reference dependency inside the caller's existing import transaction.
    Absent reference values cause no I/O and no inferred historical cost.
    """
    selected = [
        (row, result[0])
        for row, result in zip(rows, created, strict=True)
        if (row.normalized_data or {}).get("purchase_unit_cost") is not None
    ]
    if not selected:
        return
    if len(selected) > 200 or access.company_id != company_id:
        raise ValueError("Invalid bounded import reference scope")

    timestamp = datetime.now(timezone.utc)
    payload_rows: list[dict[str, object]] = []
    for row, variant in selected:
        if int(variant.company_id) != company_id:
            raise ValueError("New Product Import variant has unexpected company")
        amount = Decimal(str(row.normalized_data["purchase_unit_cost"]))
        payload_rows.append(
            {
                "product_variant_id": int(variant.id),
                "amount": format(amount, ".6f"),
                "base_uom_id": int(variant.base_uom_id),
                "provenance": {
                    "operation": "PRODUCT_IMPORT_ROW_CREATE",
                    "job_id": str(job_id),
                    "request_id": str(request_id),
                    "source_row_id": int(row.id),
                },
            }
        )

    # command_row is consumed by immutable_history; immutable_history is consumed
    # by current rows. PostgreSQL therefore preserves the required dependency
    # chain inside a single statement and the surrounding import transaction.
    statement = text(
        """
        WITH command_row AS (
            INSERT INTO purchase_cost_reference_commands (
                company_id, request_id, operation,
                actor_principal_id, actor_backoffice_user_id,
                request_hash, response_json, created_at
            )
            VALUES (
                :company_id, :request_id, 'PRODUCT_IMPORT_SET',
                :actor_principal_id, :actor_backoffice_user_id,
                :request_hash, CAST(:response_json AS jsonb), :changed_at
            )
            RETURNING request_id
        ),
        source_rows AS (
            SELECT
                src.product_variant_id,
                src.amount::numeric(20, 6) AS amount,
                src.base_uom_id,
                company.currency_code,
                src.provenance
            FROM jsonb_to_recordset(CAST(:rows_json AS jsonb)) AS src(
                product_variant_id integer,
                amount text,
                base_uom_id integer,
                provenance jsonb
            )
            JOIN uom AS base_uom
              ON base_uom.id = src.base_uom_id
             AND base_uom.code = 'EACH'
            JOIN companies AS company
              ON company.id = :company_id
        ),
        immutable_history AS (
            INSERT INTO purchase_cost_reference_changes (
                company_id, product_variant_id, revision,
                request_id, before_snapshot,
                amount, purchase_uom_id, base_uom_id,
                factor_numerator, factor_denominator,
                currency_code, source, source_cost_event_id,
                provenance, changed_at
            )
            SELECT
                :company_id, src.product_variant_id, 1,
                command_row.request_id, NULL,
                src.amount, src.base_uom_id, src.base_uom_id,
                1, 1,
                src.currency_code, 'PRODUCT_IMPORT', NULL,
                src.provenance, :changed_at
            FROM source_rows AS src
            CROSS JOIN command_row
            RETURNING
                company_id, product_variant_id, revision,
                amount, purchase_uom_id, base_uom_id,
                factor_numerator, factor_denominator,
                currency_code, source, source_cost_event_id,
                provenance, changed_at
        )
        INSERT INTO purchase_cost_references (
            company_id, product_variant_id, revision,
            amount, purchase_uom_id, base_uom_id,
            factor_numerator, factor_denominator,
            currency_code, source, source_cost_event_id,
            provenance, changed_at
        )
        SELECT
            company_id, product_variant_id, revision,
            amount, purchase_uom_id, base_uom_id,
            factor_numerator, factor_denominator,
            currency_code, source, source_cost_event_id,
            provenance, changed_at
        FROM immutable_history
        RETURNING product_variant_id
        """
    )
    result = await db.execute(
        statement,
        {
            "company_id": company_id,
            "request_id": request_id,
            "actor_principal_id": access.subject.principal_id,
            "actor_backoffice_user_id": access.subject.backoffice_user_id,
            "request_hash": request_hash,
            "response_json": json.dumps(
                {"job_id": str(job_id), "count": len(selected)},
                separators=(",", ":"),
            ),
            "changed_at": timestamp,
            "rows_json": json.dumps(payload_rows, separators=(",", ":")),
        },
    )
    inserted = [int(value) for value in result.scalars().all()]
    if len(inserted) != len(selected):
        raise ValueError(
            "Purchase import reference batch did not persist every selected base-unit row"
        )
