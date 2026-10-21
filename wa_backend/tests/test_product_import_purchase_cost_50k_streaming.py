"""50k streaming CSV profile: legacy vs optional-cost file without PostgreSQL writes.

This protects import parsing, mapping, normalization and bounded iteration.
It is not a claim about full 50k worker execution/lock wait/commit timings.
"""
from __future__ import annotations

import csv
from io import StringIO
from statistics import median
from time import perf_counter

import pytest

from domains.simple_products.imports.domain.mapping import suggest_mapping, validate_mapping
from domains.simple_products.imports.domain.normalization import normalize_raw_row
from domains.simple_products.imports.infrastructure.parsers import open_source


TOTAL = 50_000
FIELDS = [
    "name", "family", "package_uom", "units_per_package",
    "package_price", "unit_price", "unit_barcode", "package_barcode",
    "lot_control_mode", "expiry_control_mode",
]


def build_csv(with_cost: bool) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([*FIELDS, *(["purchase_unit_cost"] if with_cost else [])])
    for i in range(TOTAL):
        values = [f"Safe 50k import {i}", "", "NONE", "", "", "2.000000",
                  "", "", "NONE", "NONE"]
        if with_cost:
            values.append("1.250000")
        writer.writerow(values)
    result = buffer.getvalue().encode("utf-8")
    assert len(result) < 25_000_000
    return result


def parsed_normalized_count(payload: bytes, with_cost: bool) -> float:
    start = perf_counter()
    with open_source("50k-compatible-import.csv", payload) as source:
        assert len(source.headers) == (11 if with_cost else 10)
        mapping = validate_mapping(source.headers, suggest_mapping(source.headers))
        rows = 0
        for row in source.rows:
            data = normalize_raw_row(
                row.raw, mapping, default_lot_control_mode="NONE",
                default_expiry_control_mode="NONE",
            )
            assert data["purchase_unit_cost"] == ("1.250000" if with_cost else None)
            assert data["unit_price"] == "2.000000"
            rows += 1
        assert rows == TOTAL
    return perf_counter() - start


@pytest.mark.parametrize("warm_up", [False])
def test_real_50k_streaming_parsing_legacy_and_cost_profile(warm_up):
    old = build_csv(False)
    new = build_csv(True)
    old_runs, new_runs = [], []
    for _ in range(2):
        old_runs.append(parsed_normalized_count(old, False))
        new_runs.append(parsed_normalized_count(new, True))
    old_wall, new_wall = median(old_runs), median(new_runs)
    ratio = new_wall / max(old_wall, 0.001)
    print(f"IMPORT_50K_STREAMING legacy_seconds={old_wall:.3f} "
          f"with_purchase_cost_seconds={new_wall:.3f} ratio={ratio:.3f}", flush=True)
    # Prevent a major parser regression; end-to-end worker performance is
    # independently gated by the real PostgreSQL 200-row transaction test.
    assert ratio <= 1.50, "50k parsing cost-column regression exceeded 50% budget"
