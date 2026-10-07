from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import TenantOperationalPolicy


WHOLE_PRODUCT_QUALITY_POLICY_CODE = "INVENTORY_WHOLE_PRODUCT_QUALITY_IN_PLACE"
WHOLE_PRODUCT_QUALITY_POLICY_SCHEMA_VERSION = 1


async def ensure_whole_product_quality_policy(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
) -> TenantOperationalPolicy:
    """Return immutable tenant evidence for in-place whole-product quality handling.

    This is system-managed policy evidence, not a user-configured destination policy.
    The physical stock stays at its current warehouse until terminal disposal/vendor
    handover removes it from company ownership.
    """
    # Serialize first creation per tenant/policy without introducing a global lock.
    lock_key = f"{WHOLE_PRODUCT_QUALITY_POLICY_CODE}:{int(company_id)}"
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )

    published = (
        await db.execute(
            select(TenantOperationalPolicy)
            .where(
                TenantOperationalPolicy.company_id == company_id,
                TenantOperationalPolicy.policy_code == WHOLE_PRODUCT_QUALITY_POLICY_CODE,
                TenantOperationalPolicy.status == "PUBLISHED",
            )
            .order_by(TenantOperationalPolicy.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if published is not None:
        return published

    max_revision = int(
        (
            await db.execute(
                select(func.coalesce(func.max(TenantOperationalPolicy.revision), 0)).where(
                    TenantOperationalPolicy.company_id == company_id,
                    TenantOperationalPolicy.policy_code == WHOLE_PRODUCT_QUALITY_POLICY_CODE,
                )
            )
        ).scalar_one()
        or 0
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    policy = TenantOperationalPolicy(
        company_id=company_id,
        policy_code=WHOLE_PRODUCT_QUALITY_POLICY_CODE,
        schema_version=WHOLE_PRODUCT_QUALITY_POLICY_SCHEMA_VERSION,
        revision=max_revision + 1,
        validated_payload={
            "schema_version": WHOLE_PRODUCT_QUALITY_POLICY_SCHEMA_VERSION,
            "mode": "IN_PLACE",
            "scope": "WHOLE_PRODUCT_QUALITY",
        },
        status="PUBLISHED",
        effective_from=now,
        effective_to=None,
        approved_by=actor_id,
        approved_at=now,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(policy)
    await db.flush()
    return policy
