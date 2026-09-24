from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


checks = 0
failures: list[str] = []


def record(
    label: str,
    condition: bool,
    detail: str = "",
) -> None:
    global checks
    checks += 1
    prefix = "[PASS]" if condition else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"{prefix} {label}{suffix}")
    if not condition:
        failures.append(label)


class FakeSession:
    def __init__(self, row) -> None:
        self.row = row
        self.scalar_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.row


async def runtime_checks() -> None:
    from api.catalog import _draft_variant

    active = SimpleNamespace(
        id=101,
        lifecycle_status="ACTIVE",
    )
    active_db = FakeSession(active)
    blocked = False
    code = ""
    try:
        await _draft_variant(
            active_db,
            7,
            101,
        )
    except HTTPException as exc:
        blocked = exc.status_code == 409
        detail = exc.detail
        if isinstance(detail, dict):
            code = str(
                detail.get("code", "")
            )

    record(
        "published variant UOM structure is locked at runtime",
        blocked
        and code == "UOM_STRUCTURE_LOCKED"
        and active_db.scalar_calls == 1,
        (
            f"status_blocked={blocked} "
            f"code={code or '-'}"
        ),
    )

    draft = SimpleNamespace(
        id=102,
        lifecycle_status="DRAFT",
    )
    draft_db = FakeSession(draft)
    returned = await _draft_variant(
        draft_db,
        7,
        102,
    )
    record(
        "draft variant remains eligible for UOM structure editing",
        returned is draft
        and draft_db.scalar_calls == 1,
    )


def source_contract_checks() -> None:
    from api import catalog

    update_variant_source = inspect.getsource(
        catalog.update_variant
    )
    create_conversion_source = inspect.getsource(
        catalog.create_conversion
    )
    update_conversion_source = inspect.getsource(
        catalog.update_conversion
    )

    record(
        "base UOM and structural variant edits remain DRAFT-only",
        (
            'row.lifecycle_status != "DRAFT"'
            in update_variant_source
            and '"VARIANT_STRUCTURE_LOCKED"'
            in update_variant_source
            and '"base_uom_id"'
            in update_variant_source
        ),
    )

    record(
        "conversion create delegates to the shared DRAFT guard",
        (
            "await _draft_variant("
            in create_conversion_source
        ),
    )
    record(
        "conversion update delegates to the shared DRAFT guard",
        (
            "await _draft_variant("
            in update_conversion_source
        ),
    )

    conversion_delete_routes = [
        route
        for route in catalog.router.routes
        if getattr(route, "path", "").endswith(
            "/conversions/{conversion_id}"
        )
        and "DELETE"
        in (
            getattr(
                route,
                "methods",
                set(),
            )
            or set()
        )
    ]
    record(
        "catalog exposes no destructive UOM conversion delete route",
        not conversion_delete_routes,
    )

    tab_source = (
        ROOT
        / "dashboard/src/pages/inventory/TabProductCatalog.tsx"
    ).read_text(encoding="utf-8")
    record(
        "legacy catalog only exposes conversion creation for DRAFT variants",
        (
            'managedVariant?.lifecycle_status === "DRAFT"'
            in tab_source
            and "void addConversion()"
            in tab_source
        ),
    )


async def main() -> int:
    try:
        await runtime_checks()
        source_contract_checks()
    except Exception as exc:
        record(
            "P5 UOM safety gate completed without unexpected exception",
            False,
            repr(exc),
        )

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for label in failures:
        print(f"FAIL: {label}")

    if failures:
        print(
            "PRODUCTS_P5_UOM_SAFETY_GATE=FAIL"
        )
        return 1

    print(
        "PRODUCTS_P5_UOM_SAFETY_GATE=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
