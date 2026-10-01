"""Source-first QA for the Phase 19 synthetic import fixtures; no database."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from domains.simple_products.imports.domain.mapping import mapping_complete, suggest_mapping
from domains.simple_products.imports.infrastructure.parsers import open_source
from tools.product_import.phase19_fixture import (
    FixtureSpec,
    generate_fixture,
    headers,
    synthetic_row,
)


@pytest.mark.parametrize("locale", ["ar", "en", "mixed"])
def test_locale_rows_and_physical_blanks_roundtrip_parser(tmp_path: Path, locale: str):
    spec = FixtureSpec("safe-fixture-0042", "qa-sandbox", 102, locale=locale)
    manifest = generate_fixture(spec, tmp_path)
    assert manifest["source_rows"] == 102
    assert manifest["blank_physical_rows"] == 3
    assert manifest["last_physical_row"] == 106
    assert manifest["injected_failure_total"] == 4
    assert set(manifest["injected_failure_types"].values()) == {1}
    assert manifest["unique_barcodes"] >= 102
    data = (tmp_path / manifest["file_name"]).read_bytes()
    assert manifest["sha256"] == hashlib.sha256(data).hexdigest()
    assert data.startswith(b"\xef\xbb\xbf")
    with open_source(str(manifest["file_name"]), data) as source:
        assert source.headers == [headers(locale)[field] for field in headers(locale)]
        mapping = suggest_mapping(source.headers)
        assert mapping_complete(mapping)
        assert len(mapping) == 10
        rows = list(source.rows)
    assert len(rows) == 102
    assert rows[0].row_number == 2
    assert rows[30].row_number == 32
    assert rows[31].row_number == 34  # physical line 33 is a true empty line
    assert rows[-1].row_number == 106
    barcodes = [row.raw[headers(locale)["unit_barcode"]] for row in rows]
    assert all(isinstance(item, str) and len(item) == 13 for item in barcodes)
    assert barcodes[9].startswith("00")  # parser preserved barcode leading zeros
    assert len(set(barcodes)) == len(barcodes)


def test_defect_labels_match_exact_fixture_cells_and_valid_packaging():
    spec = FixtureSpec("safe-fixture-0043", "qa-sandbox", 100, locale="mixed")
    for index, expected in (
        (25, "MISSING_NAME"),
        (50, "MISSING_BOTH_PRICES"),
        (75, "MISSING_PACKAGE_FACTOR"),
        (100, "PACKAGE_BARCODE_WITHOUT_PACKAGE"),
    ):
        row, injected = synthetic_row(spec, index)
        assert injected == expected
        if index == 25:
            assert row["name"] == ""
        if index == 50:
            assert not row["unit_price"] and not row["package_price"]
        if index == 75:
            assert row["package_uom"] in {"Carton", "كرتونة"}
            assert row["units_per_package"] == ""
        if index == 100:
            assert row["package_barcode"]
            assert row["package_uom"] in {"No outer package", "بدون عبوة خارجية"}
    for index in (1, 2, 7, 10, 11, 13, 17, 31, 53, 73, 99):
        row, injected = synthetic_row(spec, index)
        assert injected is None
        assert row["name"] and row["unit_price"] and row["unit_barcode"]
        if row["package_uom"] in {"No outer package", "بدون عبوة خارجية"}:
            assert row["units_per_package"] == row["package_price"] == row["package_barcode"] == ""
        else:
            assert int(row["units_per_package"]) >= 2
            assert row["package_price"] and row["package_barcode"]


def test_repeatability_no_overwrite_and_enforced_dev_limits(tmp_path: Path):
    spec = FixtureSpec("safe-fixture-0044", "qa-sandbox", 100, locale="en")
    first = generate_fixture(spec, tmp_path / "first")
    second = generate_fixture(spec, tmp_path / "second")
    assert first["sha256"] == second["sha256"]
    assert first["source_bytes"] == second["source_bytes"]
    with pytest.raises(FileExistsError):
        generate_fixture(spec, tmp_path / "first")
    with pytest.raises(ValueError):
        generate_fixture(FixtureSpec("safe-fixture-0044", "qa-sandbox", 50_001), tmp_path)
    with pytest.raises(ValueError):
        generate_fixture(FixtureSpec("safe-fixture-0044", "production", 100), tmp_path)
    empty = generate_fixture(
        FixtureSpec("safe-fixture-0045", "qa-sandbox", 0), tmp_path,
    )
    assert empty["source_rows"] == 0
    assert empty["last_physical_row"] == 1
