from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

from sqlalchemy import text

from database import engine
from product_lifecycle import (
    DRAFT_DELETE_ALLOWED_VARIANT_REFERENCES,
    DRAFT_DELETE_BLOCKER_REFERENCE_GROUPS,
)


ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "wa_backend" / "product_lifecycle.py"
CATALOG = ROOT / "wa_backend" / "api" / "catalog.py"
ACTIONS = (
    ROOT
    / "dashboard"
    / "src"
    / "pages"
    / "inventory"
    / "catalog"
    / "CatalogLifecycleActions.tsx"
)
NORMAL_MANAGER = (
    ROOT
    / "dashboard"
    / "src"
    / "pages"
    / "products"
    / "lifecycle"
    / "ProductLifecycleManager.tsx"
)
I18N = ROOT / "dashboard" / "src" / "i18n" / "resources.ts"
FOUNDATION = ROOT / "INVENTORY_COMMERCIAL_FOUNDATION_PLAN.md"

checks: list[tuple[str, bool, str]] = []


def check(
    name: str,
    condition: bool,
    detail: str = "",
) -> None:
    checks.append((name, bool(condition), detail))
    suffix = f" — {detail}" if detail else ""
    print(
        f"[{'PASS' if condition else 'FAIL'}] "
        f"{name}{suffix}"
    )


lifecycle = LIFECYCLE.read_text(encoding="utf-8")
catalog = CATALOG.read_text(encoding="utf-8")
actions = ACTIONS.read_text(encoding="utf-8")
normal_manager = NORMAL_MANAGER.read_text(encoding="utf-8")
i18n = I18N.read_text(encoding="utf-8")
foundation = FOUNDATION.read_text(encoding="utf-8")

check(
    "foundation forbids hard delete after publish",
    "Hard delete بعد Publish." in foundation,
)
check(
    "never-used draft policy has a dedicated blocker authority",
    "async def draft_delete_blockers(" in lifecycle
    and "DRAFT_DELETE_BLOCKER_REFERENCE_GROUPS" in lifecycle,
)
check(
    "draft-owned references are explicitly narrow",
    DRAFT_DELETE_ALLOWED_VARIANT_REFERENCES
    == {
        "product_barcodes": "product_variant_id",
        "product_uom_conversions": "product_variant_id",
        "inventory_live_stock_projection": "product_variant_id",
    },
)
check(
    "delete endpoint rejects lifecycle history before hard delete",
    "row.published_at" in catalog
    and "row.retired_at" in catalog
    and "row.archived_at" in catalog
    and "PRODUCT_DELETE_DRAFT_TRANSITION_INVALID" in catalog,
)
check(
    "delete endpoint rechecks business references transactionally",
    "await draft_delete_blockers(" in catalog
    and "PRODUCT_DRAFT_DELETE_BLOCKED" in catalog,
)
check(
    "draft delete keeps only draft-owned cleanup",
    "delete(ProductBarcode)" in catalog
    and "delete(ProductUomConversion)" in catalog
    and 'event_type="ProductDraftDeleted"' in catalog,
)
check(
    "dedicated delete preflight is backend-authoritative",
    '@router.get("/variants/{variant_id}/delete-draft-preflight")'
    in catalog
    and '"can_delete": not blockers' in catalog,
)
check(
    "advanced UI checks delete safety before exposing hard delete",
    "checkDeleteDraft" in actions
    and "delete-draft-preflight" in actions
    and "deletePreflight?.can_delete" in actions
    and "deletePreflightRequired" in actions,
)
check(
    "normal Products lifecycle UI still does not expose hard delete",
    "onVariantDeleted=" not in normal_manager,
)
check(
    "delete blockers have Arabic and English operator copy",
    i18n.count("WAREHOUSE_OR_STOCK_REFERENCE") >= 2
    and i18n.count("SALES_REFERENCE") >= 2
    and i18n.count("IMPORT_REFERENCE") >= 2
    and i18n.count("PRICING_REFERENCE") >= 2
    and i18n.count("OFFER_REFERENCE") >= 2
    and i18n.count("TAX_REFERENCE") >= 2,
)


async def check_schema_coverage() -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.table_name, c.column_name
                    FROM information_schema.columns c
                    WHERE c.table_schema='public'
                      AND c.column_name IN (
                        'product_variant_id',
                        'scope_product_variant_id'
                      )
                      AND EXISTS (
                        SELECT 1
                        FROM information_schema.columns company_col
                        WHERE company_col.table_schema=c.table_schema
                          AND company_col.table_name=c.table_name
                          AND company_col.column_name='company_id'
                      )
                    ORDER BY c.table_name, c.column_name
                    """
                )
            )
        ).all()

    actual = {
        (str(table_name), str(column_name))
        for table_name, column_name in rows
    }
    covered = {
        (table_name, column_name)
        for references in DRAFT_DELETE_BLOCKER_REFERENCE_GROUPS.values()
        for table_name, column_name in references
    }
    covered.update(
        DRAFT_DELETE_ALLOWED_VARIANT_REFERENCES.items()
    )

    missing = sorted(actual - covered)
    stale = sorted(covered - actual)
    check(
        "every company-scoped ProductVariant reference is classified",
        not missing and not stale,
        f"actual={len(actual)} covered={len(covered)} "
        f"missing={missing} stale={stale}",
    )


asyncio.run(check_schema_coverage())

failures = [
    name
    for name, passed, _ in checks
    if not passed
]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for failure in failures:
    print(f"FAILED_CHECK={failure}")

if failures:
    print(
        "PRODUCTS_P9_DELETE_ARCHIVE_POLICY_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    "PRODUCTS_P9_DELETE_ARCHIVE_POLICY_GATE=PASS"
)
