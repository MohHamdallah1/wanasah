"""Atomic Product Import admission and capacity accounting."""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from domains.simple_products.imports.domain.admission import (
    ProductImportAdmissionDenied,
    ProductImportAdmissionPolicy,
)
from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


_ACTIVE_JOB_STATUSES = (
    "QUEUED",
    "PARSING",
    "NEEDS_MAPPING",
    "VALIDATING",
    "IMPORTING",
    "RETRYING",
)


@dataclass(frozen=True, slots=True)
class ProductImportCapacitySnapshot:
    user_recent_uploads: int
    tenant_recent_uploads: int
    tenant_active_jobs: int
    tenant_live_source_bytes: int
    global_live_source_bytes: int


def _denied(
    *,
    code: str,
    message: str,
    current_value: int,
    limit_value: int,
    policy: ProductImportAdmissionPolicy,
) -> ProductImportAdmissionDenied:
    return ProductImportAdmissionDenied(
        code=code,
        message=message,
        current_value=
            int(
                current_value
            ),
        limit_value=
            int(
                limit_value
            ),
        retry_after_seconds=
            int(
                policy.retry_after_seconds
            ),
    )


async def _ensure_tenant_capacity_row(
    connection,
    *,
    company_id: int,
) -> None:
    await connection.execute(
        """
        INSERT INTO product_import_tenant_source_capacity (
            company_id,
            live_bytes,
            high_water_bytes,
            updated_at
        )
        VALUES (
            %s,0,0,CURRENT_TIMESTAMP
        )
        ON CONFLICT (company_id)
        DO NOTHING
        """,
        [
            int(
                company_id
            )
        ],
    )


async def check_import_admission_before_persist(
    connection,
    *,
    company_id: int,
    actor_id: int,
    incoming_bytes: int,
    policy: ProductImportAdmissionPolicy,
) -> ProductImportCapacitySnapshot:
    """Fail before source persistence when tenant/user capacity is already full."""
    incoming = int(
        incoming_bytes
    )
    if incoming <= 0:
        raise ValueError(
            "incoming_bytes must be positive."
        )

    # Serializes admissions only inside one tenant. Cross-tenant uploads may
    # persist concurrently; the global counter is rechecked atomically later.
    await connection.execute(
        "SELECT pg_advisory_xact_lock("
        "%s, hashtext(%s))",
        [
            int(
                company_id
            ),
            "product-import-admission",
        ],
    )
    await _ensure_tenant_capacity_row(
        connection,
        company_id=
            int(
                company_id
            ),
    )

    cursor = await connection.execute(
        """
        SELECT
            count(*) FILTER (
                WHERE created_by = %s
            )::bigint AS user_recent,
            count(*)::bigint AS tenant_recent
        FROM product_import_jobs
        WHERE company_id = %s
          AND created_at >= (
              CURRENT_TIMESTAMP
              - (%s * INTERVAL '1 second')
          )
        """,
        [
            int(
                actor_id
            ),
            int(
                company_id
            ),
            int(
                policy.user_window_seconds
            ),
        ],
    )
    (
        user_recent,
        tenant_recent,
    ) = await cursor.fetchone()

    cursor = await connection.execute(
        """
        SELECT count(*)::bigint
        FROM product_import_jobs
        WHERE company_id = %s
          AND status = ANY(%s)
        """,
        [
            int(
                company_id
            ),
            list(
                _ACTIVE_JOB_STATUSES
            ),
        ],
    )
    active_jobs = int(
        (
            await cursor.fetchone()
        )[
            0
        ]
        or 0
    )

    cursor = await connection.execute(
        """
        SELECT live_bytes
        FROM product_import_tenant_source_capacity
        WHERE company_id = %s
        FOR UPDATE
        """,
        [
            int(
                company_id
            )
        ],
    )
    tenant_live = int(
        (
            await cursor.fetchone()
        )[
            0
        ]
        or 0
    )

    cursor = await connection.execute(
        """
        SELECT live_bytes
        FROM product_import_global_source_capacity
        WHERE id = 1
        """
    )
    global_live = int(
        (
            await cursor.fetchone()
        )[
            0
        ]
        or 0
    )

    user_recent = int(
        user_recent
        or 0
    )
    tenant_recent = int(
        tenant_recent
        or 0
    )

    if (
        user_recent
        >= int(
            policy.max_uploads_per_user_window
        )
    ):
        raise _denied(
            code=
                "PRODUCT_IMPORT_USER_RATE_LIMITED",
            message=
                "Too many Product Import uploads were submitted by this user recently.",
            current_value=
                user_recent,
            limit_value=
                policy.max_uploads_per_user_window,
            policy=policy,
        )

    if (
        tenant_recent
        >= int(
            policy.max_uploads_per_tenant_window
        )
    ):
        raise _denied(
            code=
                "PRODUCT_IMPORT_TENANT_RATE_LIMITED",
            message=
                "Too many Product Import uploads were submitted by this company recently.",
            current_value=
                tenant_recent,
            limit_value=
                policy.max_uploads_per_tenant_window,
            policy=policy,
        )

    if (
        active_jobs
        >= int(
            policy.max_active_jobs_per_tenant
        )
    ):
        raise _denied(
            code=
                "PRODUCT_IMPORT_ACTIVE_JOB_LIMIT",
            message=
                "This company already has the maximum number of active Product Import jobs.",
            current_value=
                active_jobs,
            limit_value=
                policy.max_active_jobs_per_tenant,
            policy=policy,
        )

    if (
        tenant_live
        + incoming
        > int(
            policy.max_live_source_bytes_per_tenant
        )
    ):
        raise _denied(
            code=
                "PRODUCT_IMPORT_TENANT_SOURCE_CAPACITY",
            message=
                "This company has reached its temporary Product Import source-storage capacity.",
            current_value=
                tenant_live,
            limit_value=
                policy.max_live_source_bytes_per_tenant,
            policy=policy,
        )

    if (
        global_live
        + incoming
        > int(
            policy.global_live_source_bytes
        )
    ):
        raise _denied(
            code=
                "PRODUCT_IMPORT_GLOBAL_SOURCE_CAPACITY",
            message=
                "Product Import source storage is temporarily at capacity.",
            current_value=
                global_live,
            limit_value=
                policy.global_live_source_bytes,
            policy=policy,
        )

    return ProductImportCapacitySnapshot(
        user_recent_uploads=
            user_recent,
        tenant_recent_uploads=
            tenant_recent,
        tenant_active_jobs=
            active_jobs,
        tenant_live_source_bytes=
            tenant_live,
        global_live_source_bytes=
            global_live,
    )


async def reserve_source_capacity_after_persist(
    connection,
    *,
    company_id: int,
    incoming_bytes: int,
    policy: ProductImportAdmissionPolicy,
) -> None:
    """Atomically reserve tenant/global bytes before the upload transaction commits."""
    incoming = int(
        incoming_bytes
    )

    global_result = await connection.execute(
        """
        UPDATE product_import_global_source_capacity
        SET live_bytes =
                live_bytes + %s,
            high_water_bytes =
                GREATEST(
                    high_water_bytes,
                    live_bytes + %s
                ),
            updated_at =
                CURRENT_TIMESTAMP
        WHERE id = 1
          AND live_bytes + %s <= %s
        """,
        [
            incoming,
            incoming,
            incoming,
            int(
                policy.global_live_source_bytes
            ),
        ],
    )
    if int(
        global_result.rowcount
        or 0
    ) != 1:
        cursor = await connection.execute(
            """
            SELECT live_bytes
            FROM product_import_global_source_capacity
            WHERE id = 1
            """
        )
        current = int(
            (
                await cursor.fetchone()
            )[
                0
            ]
            or 0
        )
        raise _denied(
            code=
                "PRODUCT_IMPORT_GLOBAL_SOURCE_CAPACITY",
            message=
                "Product Import source storage is temporarily at capacity.",
            current_value=
                current,
            limit_value=
                policy.global_live_source_bytes,
            policy=policy,
        )

    tenant_result = await connection.execute(
        """
        UPDATE product_import_tenant_source_capacity
        SET live_bytes =
                live_bytes + %s,
            high_water_bytes =
                GREATEST(
                    high_water_bytes,
                    live_bytes + %s
                ),
            updated_at =
                CURRENT_TIMESTAMP
        WHERE company_id = %s
          AND live_bytes + %s <= %s
        """,
        [
            incoming,
            incoming,
            int(
                company_id
            ),
            incoming,
            int(
                policy.max_live_source_bytes_per_tenant
            ),
        ],
    )
    if int(
        tenant_result.rowcount
        or 0
    ) != 1:
        cursor = await connection.execute(
            """
            SELECT live_bytes
            FROM product_import_tenant_source_capacity
            WHERE company_id = %s
            """,
            [
                int(
                    company_id
                )
            ],
        )
        row = await cursor.fetchone()
        current = int(
            (
                row[
                    0
                ]
                if row
                else 0
            )
            or 0
        )
        raise _denied(
            code=
                "PRODUCT_IMPORT_TENANT_SOURCE_CAPACITY",
            message=
                "This company has reached its temporary Product Import source-storage capacity.",
            current_value=
                current,
            limit_value=
                policy.max_live_source_bytes_per_tenant,
            policy=policy,
        )


async def record_admission_rejection(
    *,
    company_id: int,
    actor_id: int,
    denial: ProductImportAdmissionDenied,
) -> None:
    """Persist rejection telemetry outside the rolled-back admission transaction."""
    async with await psycopg.AsyncConnection.connect(
        product_import_psycopg_dsn()
    ) as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config("
                "'app.current_tenant', %s, true)",
                [
                    str(
                        int(
                            company_id
                        )
                    )
                ],
            )
            await connection.execute(
                """
                INSERT INTO product_import_admission_rejections (
                    company_id,
                    actor_id,
                    code,
                    current_value,
                    limit_value,
                    retry_after_seconds,
                    created_at
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,
                    CURRENT_TIMESTAMP
                )
                """,
                [
                    int(
                        company_id
                    ),
                    int(
                        actor_id
                    ),
                    denial.code,
                    int(
                        denial.current_value
                    ),
                    int(
                        denial.limit_value
                    ),
                    int(
                        denial.retry_after_seconds
                    ),
                ],
            )
