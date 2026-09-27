from __future__ import annotations

import asyncio
import gc
import io
import sys
import tracemalloc
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
sys.path.insert(
    0,
    str(BACKEND),
)

from domains.simple_products.imports.infrastructure.parsers import (  # noqa: E402
    MAX_IMPORT_ROWS,
    open_source,
)
from domains.simple_products.imports.infrastructure.repository import (  # noqa: E402
    insert_staged_rows,
)


BATCH_SIZE = 1_000
MEMORY_SLACK_BYTES = (
    768 * 1024
)

checks = 0
failures: list[str] = []


def check(
    condition: bool,
    label: str,
    detail: str = "",
) -> None:
    global checks
    checks += 1
    prefix = (
        "[PASS]"
        if condition
        else "[FAIL]"
    )
    suffix = (
        f" — {detail}"
        if detail
        else ""
    )
    print(
        f"{prefix} {label}{suffix}"
    )
    if not condition:
        failures.append(label)


class FakeDb:
    def __init__(
        self,
    ) -> None:
        self.max_batch = 0
        self.calls = 0

    async def execute(
        self,
        _statement,
        parameters,
    ) -> None:
        size = len(parameters)
        self.max_batch = max(
            self.max_batch,
            size,
        )
        self.calls += 1


def csv_payload(
    count: int,
) -> bytes:
    buffer = io.BytesIO()
    buffer.write(
        b"Product,Unit Price\n"
    )
    for index in range(
        count
    ):
        buffer.write(
            (
                f"P{index},1.000\n"
            ).encode("utf-8")
        )
    return buffer.getvalue()


async def measure_peak(
    count: int,
) -> tuple[int, int, int]:
    payload = csv_payload(
        count
    )
    db = FakeDb()

    # Source bytes and the already-open immutable source wrapper are excluded
    # deliberately: Phase 4 measures the incremental parser/staging working
    # set. SourceStore/blob memory is owned by Phase 12.
    with open_source(
        "products.csv",
        payload,
    ) as source:
        gc.collect()
        tracemalloc.start()
        try:
            total = await insert_staged_rows(
                db,
                company_id=1,
                job_id=uuid4(),
                rows=source.rows,
                batch_size=BATCH_SIZE,
                max_rows=MAX_IMPORT_ROWS,
            )
            _current, peak = (
                tracemalloc.get_traced_memory()
            )
        finally:
            tracemalloc.stop()

    return (
        total,
        int(peak),
        int(db.max_batch),
    )


async def main() -> None:
    parser_source = (
        BACKEND
        / "domains"
        / "simple_products"
        / "imports"
        / "infrastructure"
        / "parsers.py"
    ).read_text(
        encoding="utf-8"
    )
    repository_source = (
        BACKEND
        / "domains"
        / "simple_products"
        / "imports"
        / "infrastructure"
        / "repository.py"
    ).read_text(
        encoding="utf-8"
    )

    check(
        "rows.append(" not in parser_source
        and "list[dict[str, Any]]"
        not in parser_source,
        "Parser does not materialize an import-sized Product row list",
    )
    check(
        "yield parsed" in parser_source
        and "ParsedRow" in parser_source,
        "Parser contract yields Product rows incrementally with source row numbers",
    )
    check(
        "read_only=True"
        in parser_source
        and parser_source.index(
            "_validate_xlsx_archive("
        )
        < parser_source.index(
            "load_workbook("
        ),
        "XLSX archive security remains ahead of workbook traversal",
    )
    check(
        "batch.clear()"
        in repository_source
        and "max_rows"
        in repository_source,
        "Repository flushes fixed staging batches and enforces a defensive row ceiling",
    )

    # Warm SQLAlchemy mapper/statement construction before measuring.
    await measure_peak(100)

    measurements: dict[
        int,
        tuple[int, int, int],
    ] = {}
    for count in (
        1_000,
        10_000,
        50_000,
    ):
        measurements[count] = (
            await measure_peak(
                count
            )
        )

    for (
        count,
        (
            total,
            peak,
            max_batch,
        ),
    ) in measurements.items():
        check(
            total == count,
            f"{count:,}-row stream stages every row",
            f"total={total}",
        )
        check(
            max_batch
            <= BATCH_SIZE,
            f"{count:,}-row stream never exceeds configured staging batch",
            f"max_batch={max_batch}",
        )
        print(
            "MEMORY_PEAK_"
            f"{count}="
            f"{peak}"
        )

    baseline_peak = (
        measurements[
            1_000
        ][1]
    )
    ten_k_peak = (
        measurements[
            10_000
        ][1]
    )
    fifty_k_peak = (
        measurements[
            50_000
        ][1]
    )
    allowed_peak = (
        baseline_peak
        + MEMORY_SLACK_BYTES
    )

    check(
        ten_k_peak
        <= allowed_peak,
        "10,000-row incremental working set stays within fixed memory envelope",
        (
            f"baseline={baseline_peak} "
            f"peak={ten_k_peak} "
            f"limit={allowed_peak}"
        ),
    )
    check(
        fifty_k_peak
        <= allowed_peak,
        "50,000-row incremental working set stays within the same fixed memory envelope as 1,000 rows",
        (
            f"baseline={baseline_peak} "
            f"peak={fifty_k_peak} "
            f"limit={allowed_peak}"
        ),
    )

    if failures:
        print(
            f"CHECKS={checks}"
        )
        print(
            f"FAILURES={len(failures)}"
        )
        for failure in failures:
            print(
                f"FAIL: {failure}"
            )
        print(
            "PRODUCT_IMPORT_PHASE4_STREAMING_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        f"CHECKS={checks}"
    )
    print("FAILURES=0")
    print(
        "PRODUCT_IMPORT_PHASE4_STREAMING_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
