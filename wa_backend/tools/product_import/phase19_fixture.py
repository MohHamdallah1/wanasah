"""Generate unique synthetic, dev-only Product Import CSVs; no HTTP/DB writes.

Run from wa_backend: python -m tools.product_import.phase19_fixture --help
The manifest records injected fixture defects, not predicted live worker outcomes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from domains.simple_products.imports.domain.localization import (
    AR_IMPORT_LOCALE,
    CANONICAL_IMPORT_FIELDS,
    EN_IMPORT_LOCALE,
)

MAX_SOURCE_ROWS = 50_000
MAX_INGRESS_FIXTURE_BYTES = 9 * 1024 * 1024
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{6,64}\Z")
TENANT_LABEL_PATTERN = re.compile(r"[A-Za-z0-9_-]{3,32}\Z")

INJECTED_FAILURES = (
    "MISSING_NAME",
    "MISSING_BOTH_PRICES",
    "MISSING_PACKAGE_FACTOR",
    "PACKAGE_BARCODE_WITHOUT_PACKAGE",
)


@dataclass(frozen=True)
class FixtureSpec:
    run_id: str
    tenant_label: str
    rows: int
    locale: str = "mixed"
    invalid_every: int = 25
    blank_every: int = 31

    def validate(self) -> None:
        if not RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("Fixture run id must be 6..64 URL-safe characters.")
        if not TENANT_LABEL_PATTERN.fullmatch(self.tenant_label):
            raise ValueError("Use a short synthetic development-tenant label.")
        if self.tenant_label.lower().startswith(("prod", "live", "customer")):
            raise ValueError("Fixture must not be labeled as live/customer data.")
        if self.locale not in {"ar", "en", "mixed"}:
            raise ValueError("Locale must be ar, en or mixed.")
        if not 0 <= self.rows <= MAX_SOURCE_ROWS:
            raise ValueError("Row count exceeds the V1 50,000-row source limit.")
        if self.invalid_every < 2 or self.blank_every < 2:
            raise ValueError("Invalid/blank intervals must be at least 2.")


def headers(locale: str) -> dict[str, str]:
    en = EN_IMPORT_LOCALE.template.headers
    ar = AR_IMPORT_LOCALE.template.headers
    if locale == "ar":
        return dict(ar)
    if locale == "en":
        return dict(en)
    return {
        field: (ar if index % 2 == 0 else en)[field]
        for index, field in enumerate(CANONICAL_IMPORT_FIELDS)
    }


def _ean13(prefix12: str) -> str:
    if len(prefix12) != 12 or not prefix12.isascii() or not prefix12.isdigit():
        raise ValueError("The fixture barcode prefix must have 12 ASCII digits.")
    digits = [int(digit) for digit in prefix12]
    check = (10 - sum((1 if i % 2 == 0 else 3) * value
                      for i, value in enumerate(digits)) % 10) % 10
    return prefix12 + str(check)


def _barcode(run_id: str, number: int, *, outer: bool) -> str:
    # 00/28/29 are synthetic/private test prefixes; never attach these goods
    # to real customers or claim GS1 allocations. Full-run barcode uniqueness
    # is checked before any fixture is returned.
    tag = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest(), 16) % 100_000
    prefix = "28" if outer else ("00" if number % 10 == 0 else "29")
    return _ean13(f"{prefix}{tag:05d}{number:05d}")


def _tracking(index: int, locale: str) -> tuple[str, str]:
    labels = (
        ("", "", ""),
        ("بدون", "اختياري", "إلزامي") if locale == "ar"
        else ("None", "Optional", "Required"),
    )
    if index % 17 == 0:
        return labels[1][2], labels[1][2]
    if index % 13 == 0:
        return labels[1][1], labels[1][0]
    if index % 5 == 0:
        return labels[1][0], labels[1][1]
    return labels[0][0], labels[0][0]


def synthetic_row(spec: FixtureSpec, index: int) -> tuple[dict[str, str], str | None]:
    """One deterministic candidate; injected failures are not DB predictions."""
    spec.validate()
    if not 1 <= index <= spec.rows:
        raise ValueError("Synthetic row is outside this fixture's range.")
    arabic = index % 3 != 2
    text_locale = "ar" if arabic else "en"
    tag = hashlib.sha256(spec.run_id.encode("utf-8")).hexdigest()[:10]
    name = (
        f"منتج تجريبي {tag}-{index:05d}"
        if index % 3 == 0 else
        f"QA test product {tag}-{index:05d}"
        if index % 3 == 2 else
        f"تجريبي Mixed {tag}-{index:05d}"
    )
    unit_minor = 100 + (index % 700)
    unit_price = f"{unit_minor // 100}.{unit_minor % 100:02d}"
    outer = index % 7 == 0 or index % 11 == 0
    factor = 24 if index % 7 == 0 else 12
    type_name = (
        "كرتونة" if index % 7 == 0 else "صندوق"
    ) if text_locale == "ar" else (
        "Carton" if index % 7 == 0 else "Case"
    )
    no_package = "بدون عبوة خارجية" if text_locale == "ar" else "No outer package"
    lot, expiry = _tracking(index, text_locale)
    item: dict[str, str] = {
        "name": name,
        "family": "",
        "package_uom": type_name if outer else no_package,
        "units_per_package": str(factor) if outer else "",
        "package_price": (
            f"{(unit_minor * factor) // 100}.{(unit_minor * factor) % 100:02d}"
            if outer else ""
        ),
        "unit_price": unit_price,
        "unit_barcode": _barcode(spec.run_id, index, outer=False),
        "package_barcode": _barcode(spec.run_id, index, outer=True) if outer else "",
        "lot_control_mode": lot,
        "expiry_control_mode": expiry,
    }
    defect: str | None = None
    if index % spec.invalid_every == 0:
        defect = INJECTED_FAILURES[
            (index // spec.invalid_every - 1) % len(INJECTED_FAILURES)
        ]
        if defect == "MISSING_NAME":
            item["name"] = ""
        elif defect == "MISSING_BOTH_PRICES":
            item["unit_price"] = ""
            item["package_price"] = ""
        elif defect == "MISSING_PACKAGE_FACTOR":
            item["package_uom"] = "كرتونة" if text_locale == "ar" else "Carton"
            item["units_per_package"] = ""
        else:
            item["package_uom"] = no_package
            item["units_per_package"] = ""
            item["package_price"] = ""
            item["package_barcode"] = _barcode(spec.run_id, index, outer=True)
    return item, defect


def iter_source_rows(
    spec: FixtureSpec,
) -> Iterator[tuple[int, list[str], str | None]]:
    """Emit data rows with their actual physical source line numbers."""
    selected = headers(spec.locale)
    physical = 1
    for index in range(1, spec.rows + 1):
        if index > 1 and (index - 1) % spec.blank_every == 0:
            physical += 1
            yield physical, [], None
        item, defect = synthetic_row(spec, index)
        physical += 1
        yield physical, [item[field] for field in CANONICAL_IMPORT_FIELDS], defect


def generate_fixture(spec: FixtureSpec, output_dir: Path) -> dict[str, object]:
    """Create a new immutable CSV + manifest; never overwrite an existing run."""
    spec.validate()
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"p19-{spec.tenant_label}-{spec.run_id}-{spec.locale}-{spec.rows}"
    csv_path = output_dir / f"{base}.csv"
    manifest_path = output_dir / f"{base}.manifest.json"
    if csv_path.exists() or manifest_path.exists():
        raise FileExistsError("Fixture run already exists; choose a fresh --run-id.")

    selected = headers(spec.locale)
    seen_barcodes: set[str] = set()
    injected: dict[str, int] = {kind: 0 for kind in INJECTED_FAILURES}
    physical_blanks = 0
    last_physical = 1
    with csv_path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([selected[field] for field in CANONICAL_IMPORT_FIELDS])
        for physical, values, defect in iter_source_rows(spec):
            writer.writerow(values)
            last_physical = physical
            if not values:
                physical_blanks += 1
                continue
            for field in ("unit_barcode", "package_barcode"):
                code = values[list(CANONICAL_IMPORT_FIELDS).index(field)]
                if code:
                    if code in seen_barcodes:
                        raise ValueError("Synthetic fixture contains a duplicate barcode.")
                    seen_barcodes.add(code)
            if defect:
                injected[defect] += 1

    digest = hashlib.sha256()
    file_size = 0
    with csv_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
            file_size += len(chunk)
    if file_size > MAX_INGRESS_FIXTURE_BYTES:
        csv_path.unlink()
        raise ValueError("Synthetic fixture exceeds the 9 MiB upload headroom budget.")

    manifest: dict[str, object] = {
        "schema": 1,
        "synthetic_development_only": True,
        "tenant_label": spec.tenant_label,
        "run_id": spec.run_id,
        "source_locale": spec.locale,
        "file_name": csv_path.name,
        "sha256": digest.hexdigest(),
        "source_bytes": file_size,
        "source_rows": spec.rows,
        "blank_physical_rows": physical_blanks,
        "last_physical_row": last_physical,
        "unique_barcodes": len(seen_barcodes),
        "injected_failure_types": injected,
        "injected_failure_total": sum(injected.values()),
        "candidate_without_injected_failure": spec.rows - sum(injected.values()),
        "note": (
            "No HTTP/DB/worker calls. These are injected fixture defects, "
            "not a prediction of final validation/published product counts."
        ),
    }
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--tenant-label", required=True)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--locale", choices=("ar", "en", "mixed"), default="mixed")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--invalid-every", type=int, default=25)
    parser.add_argument("--blank-every", type=int, default=31)
    parser.add_argument(
        "--confirm-development-only", action="store_true",
        help="Explicitly acknowledge that this creates a synthetic fixture, not customer data.",
    )
    args = parser.parse_args()
    if not args.confirm_development_only:
        parser.error("--confirm-development-only is required.")
    spec = FixtureSpec(
        run_id=args.run_id or uuid.uuid4().hex,
        tenant_label=args.tenant_label,
        rows=args.rows,
        locale=args.locale,
        invalid_every=args.invalid_every,
        blank_every=args.blank_every,
    )
    print(json.dumps(generate_fixture(spec, args.output_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
