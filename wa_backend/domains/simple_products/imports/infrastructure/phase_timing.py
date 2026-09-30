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
