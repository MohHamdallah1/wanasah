from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

from fastapi import HTTPException
from sqlalchemy import text

import gate_products_p9_family_reassignment as family_gate
import gate_products_read_contract_p2 as p2_gate
from api.catalog import (
    LifecycleCommand,
    delete_draft_variant,
    variant_delete_draft_preflight,
)
from database import engine
from models import Driver
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


async def _runtime_actor_session(
    conn,
    company_id: int,
    actor_id: int,
):
    db = await family_gate.scoped_session(
        conn,
        company_id,
    )
    actor = await db.get(
        Driver,
        actor_id,
    )
    if actor is None:
        await db.close()
        raise RuntimeError(
            "P9 delete-policy actor is not visible."
        )
    return db, actor


def _http_code(
    exc: HTTPException,
) -> str | None:
    if isinstance(exc.detail, dict):
        value = exc.detail.get("code")
        if isinstance(value, str):
            return value
    return None


async def check_runtime_policy() -> None:
    async with p2_gate.engine_su.connect() as conn:
        outer = await conn.begin()
        try:
            ids = await family_gate.seed(
                conn
            )
            company_id = ids[
                "company_id"
            ]
            actor_id = ids[
                "actor_id"
            ]
            draft_variant_id = ids[
                "draft_variant_id"
            ]

            db, actor = (
                await _runtime_actor_session(
                    conn,
                    company_id,
                    actor_id,
                )
            )
            try:
                clean_preflight = (
                    await variant_delete_draft_preflight(
                        variant_id=draft_variant_id,
                        db=db,
                        actor=actor,
                    )
                )
            finally:
                await db.close()

            check(
                "unused unpublished draft passes delete preflight",
                clean_preflight[
                    "can_delete"
                ]
                is True
                and clean_preflight[
                    "blockers"
                ]
                == [],
                str(clean_preflight),
            )

            batch_id = int(
                (
                    await conn.execute(
                        text(
                            "INSERT INTO product_batches "
                            "(company_id, product_variant_id, "
                            "batch_number, disposition, "
                            "disposition_revision, is_active, "
                            "created_at, updated_at) "
                            "VALUES "
                            "(:company_id, :variant_id, "
                            ":batch_number, 'RELEASED', "
                            "1, true, "
                            "TIMEZONE('UTC', CURRENT_TIMESTAMP), "
                            "TIMEZONE('UTC', CURRENT_TIMESTAMP)) "
                            "RETURNING id"
                        ),
                        {
                            "company_id":
                                company_id,
                            "variant_id":
                                draft_variant_id,
                            "batch_number":
                                "P9-DELETE-"
                                + uuid4().hex[:10],
                        },
                    )
                ).scalar_one()
            )

            db, actor = (
                await _runtime_actor_session(
                    conn,
                    company_id,
                    actor_id,
                )
            )
            try:
                blocked_preflight = (
                    await variant_delete_draft_preflight(
                        variant_id=draft_variant_id,
                        db=db,
                        actor=actor,
                    )
                )
            finally:
                await db.close()

            blocker_codes = {
                str(item["code"])
                for item in blocked_preflight[
                    "blockers"
                ]
            }
            check(
                "draft business history blocks preflight with an operator category",
                blocked_preflight[
                    "can_delete"
                ]
                is False
                and "WAREHOUSE_OR_STOCK_REFERENCE"
                in blocker_codes,
                str(blocked_preflight),
            )

            db, actor = (
                await _runtime_actor_session(
                    conn,
                    company_id,
                    actor_id,
                )
            )
            blocked_code = None
            try:
                try:
                    await delete_draft_variant(
                        variant_id=draft_variant_id,
                        payload=LifecycleCommand(
                            request_id=uuid4(),
                            expected_version=1,
                            reason=(
                                "P9 delete policy "
                                "blocked-history test"
                            ),
                        ),
                        db=db,
                        actor=actor,
                    )
                except HTTPException as exc:
                    blocked_code = (
                        _http_code(exc)
                    )
            finally:
                await db.close()
            check(
                "hard delete rechecks blockers instead of trusting UI preflight",
                blocked_code
                == "PRODUCT_DRAFT_DELETE_BLOCKED",
                str(blocked_code),
            )

            await conn.execute(
                text(
                    "DELETE FROM product_batches "
                    "WHERE company_id=:company_id "
                    "AND id=:batch_id"
                ),
                {
                    "company_id":
                        company_id,
                    "batch_id":
                        batch_id,
                },
            )

            db, actor = (
                await _runtime_actor_session(
                    conn,
                    company_id,
                    actor_id,
                )
            )
            try:
                deleted = (
                    await delete_draft_variant(
                        variant_id=draft_variant_id,
                        payload=LifecycleCommand(
                            request_id=uuid4(),
                            expected_version=1,
                            reason=(
                                "P9 delete policy "
                                "clean-draft test"
                            ),
                        ),
                        db=db,
                        actor=actor,
                    )
                )
            finally:
                await db.close()

            remaining = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM product_variants "
                            "WHERE company_id=:company_id "
                            "AND id=:variant_id"
                        ),
                        {
                            "company_id":
                                company_id,
                            "variant_id":
                                draft_variant_id,
                        },
                    )
                ).scalar_one()
            )
            audit_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM domain_audit_events "
                            "WHERE company_id=:company_id "
                            "AND entity_type='ProductVariant' "
                            "AND entity_id=:entity_id "
                            "AND event_type='ProductDraftDeleted'"
                        ),
                        {
                            "company_id":
                                company_id,
                            "entity_id":
                                str(
                                    draft_variant_id
                                ),
                        },
                    )
                ).scalar_one()
            )
            check(
                "clean never-used draft can be physically deleted with audit evidence",
                deleted.get(
                    "variant_id"
                )
                == draft_variant_id
                and remaining == 0
                and audit_count == 1,
                (
                    f"remaining={remaining} "
                    f"audit={audit_count}"
                ),
            )

            active_variant_id = ids[
                "active_variant_id"
            ]
            active_version = int(
                (
                    await conn.execute(
                        text(
                            "SELECT version "
                            "FROM product_variants "
                            "WHERE company_id=:company_id "
                            "AND id=:variant_id"
                        ),
                        {
                            "company_id":
                                company_id,
                            "variant_id":
                                active_variant_id,
                        },
                    )
                ).scalar_one()
            )
            db, actor = (
                await _runtime_actor_session(
                    conn,
                    company_id,
                    actor_id,
                )
            )
            published_code = None
            try:
                try:
                    await delete_draft_variant(
                        variant_id=active_variant_id,
                        payload=LifecycleCommand(
                            request_id=uuid4(),
                            expected_version=
                                active_version,
                            reason=(
                                "P9 published hard-delete "
                                "must fail"
                            ),
                        ),
                        db=db,
                        actor=actor,
                    )
                except HTTPException as exc:
                    published_code = (
                        _http_code(exc)
                    )
            finally:
                await db.close()
            check(
                "published Product cannot be hard deleted and must use lifecycle",
                published_code
                == "PRODUCT_DELETE_DRAFT_TRANSITION_INVALID",
                str(published_code),
            )
        finally:
            await outer.rollback()


asyncio.run(check_schema_coverage())
asyncio.run(check_runtime_policy())

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
