"""Bounded phase wall-time evidence, without polling or source-data logging."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from uuid import UUID


logger = logging.getLogger("wanasah_logger")


@contextmanager
def observe_import_phase(
    *,
    company_id: int,
    job_id: UUID,
    phase: str,
) -> Iterator[None]:
    """Measure wall time, not SQL server time or a confirmed commit outcome."""
    started = perf_counter()
    outcome = "returned"
    try:
        yield
    except BaseException:
        outcome = "interrupted"
        raise
    finally:
        logger.info(
            "PRODUCT_IMPORT_PHASE correlation_id=product-import:%s "
            "company_id=%s job_id=%s phase=%s outcome=%s wall_ms=%.3f",
            job_id, int(company_id), job_id, phase, outcome,
            (perf_counter() - started) * 1000,
        )



@contextmanager
def observe_import_staging_insert(
    *,
    company_id: int,
    job_id: UUID,
    batch_index: int,
    candidate_count: int,
    first_source_row: int,
    last_source_row: int,
) -> Iterator[None]:
    """Bounded stage-write marker, not a claim of a committed DB row.

    The START marker is emitted *before* driver parameter encoding and SQL
    transmission. If the driver hangs in ClientRead, absence of a matching
    STAGING_SQL phase completion narrows the exact bounded insert batch.
    Never log raw cells, barcodes, SQL statements or driver parameters.
    """
    logger.info(
        "PRODUCT_IMPORT_STAGING_BATCH_BEGIN correlation_id=product-import:%s "
        "company_id=%s job_id=%s batch_index=%s candidate_rows=%s "
        "first_source_row=%s last_source_row=%s",
        job_id, int(company_id), job_id, int(batch_index),
        int(candidate_count), int(first_source_row), int(last_source_row),
    )
    with observe_import_phase(
        company_id=company_id,
        job_id=job_id,
        phase="STAGING_SQL",
    ):
        yield
