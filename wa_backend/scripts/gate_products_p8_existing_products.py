from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)


BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=False)

from domains.product_tracking import (
    ProductTrackingError,
    assert_tracking_mode_change_allowed,
)


MIGRATION_URL = os.environ["DATABASE_URL_MIGRATION"]

engine = create_async_engine(
    MIGRATION_URL,
    pool_size=1,
    max_overflow=0,
)
Session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autobegin=False,
)

MAX_SAMPLE_ROWS = 20

RESULTS: list[tuple[str, bool, str]] = []


def record(
    name: str,
    ok: bool,
    detail: str = "",
) -> None:
    RESULTS.append(
        (name, bool(ok), detail)
    )
    print(
        f"[{'PASS' if ok else 'FAIL'}] "
        f"{name}"
        + (
            f" — {detail}"
            if detail
            else ""
        )
    )


def alternate_tracking_mode(
    value: str,
) -> str:
    normalized = value.strip().upper()
    if normalized == "NONE":
        return "OPTIONAL"
    return "NONE"


CLASSIFIED_CTE = """
WITH batch_history AS (
    SELECT
        company_id,
        product_variant_id,
        count(*)::bigint AS batch_rows
    FROM product_batches
    GROUP BY
        company_id,
        product_variant_id
),
classified AS (
    SELECT
        pv.company_id,
        pv.id AS product_variant_id,
        pv.lifecycle_status,
        pv.lot_control_mode,
        pv.expiry_control_mode,
        COALESCE(
            bh.batch_rows,
            0
        )::bigint AS batch_rows,
        (
            pv.lot_control_mode = 'REQUIRED'
            AND pv.expiry_control_mode = 'REQUIRED'
        ) AS review_candidate,
        (
            COALESCE(
                bh.batch_rows,
                0
            ) > 0
        ) AS has_batch_history,
        (
            pv.lifecycle_status IN (
                'DRAFT',
                'ACTIVE'
            )
        ) AS lifecycle_editable
    FROM product_variants AS pv
    LEFT JOIN batch_history AS bh
        ON bh.company_id = pv.company_id
        AND bh.product_variant_id = pv.id
)
"""


async def authority_parity_check(
    session,
    *,
    row: Any | None,
    expect_locked: bool,
) -> tuple[bool, str]:
    if row is None:
        return (
            True,
            "no matching real SKU exists; parity is vacuously satisfied",
        )

    company_id = int(row.company_id)
    variant_id = int(
        row.product_variant_id
    )
    current_lot = str(
        row.lot_control_mode
    )
    current_expiry = str(
        row.expiry_control_mode
    )
    requested_lot = (
        alternate_tracking_mode(
            current_lot
        )
    )

    try:
        await assert_tracking_mode_change_allowed(
            session,
            company_id=company_id,
            product_variant_id=variant_id,
            current_lot_control_mode=current_lot,
            current_expiry_control_mode=current_expiry,
            requested_lot_control_mode=requested_lot,
            requested_expiry_control_mode=current_expiry,
        )
    except ProductTrackingError as exc:
        if (
            expect_locked
            and exc.code
            == "PRODUCT_TRACKING_LOCKED"
        ):
            return (
                True,
                (
                    f"company_id={company_id} "
                    f"variant_id={variant_id} "
                    f"code={exc.code}"
                ),
            )
        return (
            False,
            (
                f"company_id={company_id} "
                f"variant_id={variant_id} "
                f"unexpected_code={exc.code}"
            ),
        )

    if expect_locked:
        return (
            False,
            (
                f"company_id={company_id} "
                f"variant_id={variant_id} "
                "history-bearing SKU was not locked"
            ),
        )
    return (
        True,
        (
            f"company_id={company_id} "
            f"variant_id={variant_id} "
            "history-free SKU accepted by guard"
        ),
    )


async def main() -> int:
    try:
        async with Session() as session:
            await session.begin()
            await session.execute(
                text(
                    "SET TRANSACTION READ ONLY"
                )
            )

            read_only = str(
                (
                    await session.execute(
                        text(
                            "SHOW transaction_read_only"
                        )
                    )
                ).scalar_one()
            ).strip().lower()
            record(
                "existing-product audit transaction is read-only",
                read_only == "on",
                (
                    "transaction_read_only="
                    + read_only
                ),
            )

            stats = (
                await session.execute(
                    text(
                        CLASSIFIED_CTE
                        + """
SELECT
    count(*)::bigint AS total_variants,
    count(*) FILTER (
        WHERE review_candidate
    )::bigint AS review_candidates,
    count(*) FILTER (
        WHERE review_candidate
        AND has_batch_history
    )::bigint AS review_history_locked,
    count(*) FILTER (
        WHERE review_candidate
        AND NOT has_batch_history
        AND lifecycle_editable
    )::bigint AS reviewable_now,
    count(*) FILTER (
        WHERE review_candidate
        AND NOT has_batch_history
        AND NOT lifecycle_editable
    )::bigint AS review_lifecycle_blocked,
    count(*) FILTER (
        WHERE has_batch_history
    )::bigint AS history_bearing_total,
    count(*) FILTER (
        WHERE NOT has_batch_history
    )::bigint AS history_free_total,
    count(*) FILTER (
        WHERE lot_control_mode NOT IN (
            'NONE',
            'OPTIONAL',
            'REQUIRED'
        )
        OR expiry_control_mode NOT IN (
            'NONE',
            'OPTIONAL',
            'REQUIRED'
        )
    )::bigint AS invalid_tracking_modes,
    count(*) FILTER (
        WHERE lifecycle_status NOT IN (
            'DRAFT',
            'ACTIVE',
            'RETIRING',
            'ARCHIVED'
        )
    )::bigint AS invalid_lifecycle_states
FROM classified
"""
                    )
                )
            ).one()

            total = int(
                stats.total_variants
            )
            review_candidates = int(
                stats.review_candidates
            )
            review_history_locked = int(
                stats.review_history_locked
            )
            reviewable_now = int(
                stats.reviewable_now
            )
            review_lifecycle_blocked = int(
                stats.review_lifecycle_blocked
            )
            history_bearing_total = int(
                stats.history_bearing_total
            )
            history_free_total = int(
                stats.history_free_total
            )
            invalid_tracking = int(
                stats.invalid_tracking_modes
            )
            invalid_lifecycle = int(
                stats.invalid_lifecycle_states
            )

            record(
                "all existing product tracking modes are valid",
                invalid_tracking == 0,
                (
                    "invalid_tracking_modes="
                    f"{invalid_tracking}"
                ),
            )
            record(
                "all existing product lifecycle states are valid",
                invalid_lifecycle == 0,
                (
                    "invalid_lifecycle_states="
                    f"{invalid_lifecycle}"
                ),
            )
            record(
                "every existing product variant is history-classified",
                (
                    history_bearing_total
                    + history_free_total
                    == total
                ),
                (
                    f"total={total} "
                    f"history_bearing="
                    f"{history_bearing_total} "
                    f"history_free="
                    f"{history_free_total}"
                ),
            )
            record(
                "every REQUIRED/REQUIRED review candidate has a safe disposition",
                (
                    review_history_locked
                    + reviewable_now
                    + review_lifecycle_blocked
                    == review_candidates
                ),
                (
                    f"candidates="
                    f"{review_candidates} "
                    f"history_locked="
                    f"{review_history_locked} "
                    f"reviewable_now="
                    f"{reviewable_now} "
                    f"lifecycle_blocked="
                    f"{review_lifecycle_blocked}"
                ),
            )

            orphan_batches = int(
                (
                    await session.execute(
                        text(
                            """
SELECT count(*)::bigint
FROM product_batches AS pb
LEFT JOIN product_variants AS pv
    ON pv.company_id = pb.company_id
    AND pv.id = pb.product_variant_id
WHERE pv.id IS NULL
"""
                        )
                    )
                ).scalar_one()
            )
            record(
                "batch history remains tenant-consistent with product variants",
                orphan_batches == 0,
                (
                    "orphan_or_cross_tenant_batches="
                    f"{orphan_batches}"
                ),
            )

            history_sample = (
                await session.execute(
                    text(
                        CLASSIFIED_CTE
                        + """
SELECT
    company_id,
    product_variant_id,
    lot_control_mode,
    expiry_control_mode
FROM classified
WHERE has_batch_history
ORDER BY
    company_id,
    product_variant_id
LIMIT 1
"""
                    )
                )
            ).one_or_none()
            locked_ok, locked_detail = (
                await authority_parity_check(
                    session,
                    row=history_sample,
                    expect_locked=True,
                )
            )
            record(
                "real history classification matches PRODUCT_TRACKING_LOCKED authority",
                locked_ok,
                locked_detail,
            )

            history_free_sample = (
                await session.execute(
                    text(
                        CLASSIFIED_CTE
                        + """
SELECT
    company_id,
    product_variant_id,
    lot_control_mode,
    expiry_control_mode
FROM classified
WHERE NOT has_batch_history
ORDER BY
    company_id,
    product_variant_id
LIMIT 1
"""
                    )
                )
            ).one_or_none()
            free_ok, free_detail = (
                await authority_parity_check(
                    session,
                    row=history_free_sample,
                    expect_locked=False,
                )
            )
            record(
                "real history-free classification matches tracking-history guard",
                free_ok,
                free_detail,
            )

            mode_rows = (
                await session.execute(
                    text(
                        CLASSIFIED_CTE
                        + """
SELECT
    lot_control_mode,
    expiry_control_mode,
    count(*)::bigint AS variants,
    count(*) FILTER (
        WHERE has_batch_history
    )::bigint AS with_history
FROM classified
GROUP BY
    lot_control_mode,
    expiry_control_mode
ORDER BY
    lot_control_mode,
    expiry_control_mode
"""
                    )
                )
            ).all()

            candidate_samples = (
                await session.execute(
                    text(
                        CLASSIFIED_CTE
                        + """
SELECT
    company_id,
    product_variant_id,
    lifecycle_status,
    batch_rows,
    CASE
        WHEN has_batch_history
            THEN 'HISTORY_LOCKED'
        WHEN lifecycle_editable
            THEN 'REVIEWABLE_NOW'
        ELSE 'LIFECYCLE_BLOCKED'
    END AS disposition
FROM classified
WHERE review_candidate
ORDER BY
    company_id,
    product_variant_id
LIMIT :limit
"""
                    ),
                    {
                        "limit":
                            MAX_SAMPLE_ROWS,
                    },
                )
            ).all()

            print(
                "PRODUCTS_EXISTING_TRACKING_TOTAL="
                f"{total}"
            )
            print(
                "PRODUCTS_EXISTING_TRACKING_REVIEW_CANDIDATES="
                f"{review_candidates}"
            )
            print(
                "PRODUCTS_EXISTING_TRACKING_REVIEW_HISTORY_LOCKED="
                f"{review_history_locked}"
            )
            print(
                "PRODUCTS_EXISTING_TRACKING_REVIEWABLE_NOW="
                f"{reviewable_now}"
            )
            print(
                "PRODUCTS_EXISTING_TRACKING_REVIEW_LIFECYCLE_BLOCKED="
                f"{review_lifecycle_blocked}"
            )

            for row in mode_rows:
                print(
                    "PRODUCTS_EXISTING_TRACKING_MODE="
                    f"{row.lot_control_mode}/"
                    f"{row.expiry_control_mode} "
                    f"VARIANTS={int(row.variants)} "
                    f"WITH_HISTORY="
                    f"{int(row.with_history)}"
                )

            for row in candidate_samples:
                print(
                    "PRODUCTS_EXISTING_TRACKING_CANDIDATE="
                    f"company:{int(row.company_id)} "
                    f"variant:{int(row.product_variant_id)} "
                    f"lifecycle:{row.lifecycle_status} "
                    f"batch_rows:{int(row.batch_rows)} "
                    f"disposition:{row.disposition}"
                )

            if (
                review_candidates
                > MAX_SAMPLE_ROWS
            ):
                print(
                    "PRODUCTS_EXISTING_TRACKING_CANDIDATE_SAMPLE_TRUNCATED="
                    f"{review_candidates - MAX_SAMPLE_ROWS}"
                )

            # No commit is ever attempted. Keep the transaction explicitly
            # read-only and roll it back after evidence collection.
            await session.rollback()

        failures = [
            item
            for item in RESULTS
            if not item[1]
        ]
        print(
            f"CHECKS={len(RESULTS)}"
        )
        print(
            f"FAILURES={len(failures)}"
        )
        for name, _, detail in failures:
            print(
                "FAILED_CHECK="
                + name
                + (
                    f" — {detail}"
                    if detail
                    else ""
                )
            )

        if failures:
            print(
                "PRODUCTS_P8_EXISTING_PRODUCTS_GATE=FAIL"
            )
            return 1

        print(
            "PRODUCTS_P8_EXISTING_PRODUCTS_GATE=PASS"
        )
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
