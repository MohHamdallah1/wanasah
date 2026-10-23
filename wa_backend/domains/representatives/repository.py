from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.types import PrincipalType
from models import Driver, OperationIdempotency, SystemAuditLog

from .contracts import RepresentativeError
from domains.authorization.field_provisioning import assign_new_representative_default
from domains.authorization.field_role_policy import FieldRoleError


MONEY_MAX = Decimal("999999999.999")
MONEY_QUANT = Decimal("0.001")
_REPRESENTATIVE_IDEMPOTENT_OPERATIONS = frozenset(
    {
        "REPRESENTATIVE_CREATE",
        "REPRESENTATIVE_UPDATE",
        "REPRESENTATIVE_DEACTIVATE",
        "REPRESENTATIVE_REACTIVATE",
        "REPRESENTATIVE_CREDENTIAL_RESET",
        "REPRESENTATIVE_FIELD_ROLE_GRANT",
        "REPRESENTATIVE_FIELD_ROLE_REVOKE",
    }
)


def normalize_debt_limit(value: Decimal) -> Decimal:
    """Normalize the persisted NUMERIC(12,3) representative debt limit."""
    try:
        amount = Decimal(value)
    except Exception as exc:
        raise RepresentativeError(
            "REPRESENTATIVE_DEBT_LIMIT_INVALID",
            "Maximum debt limit is invalid.",
            status_code=422,
        ) from exc
    if not amount.is_finite() or amount < 0 or amount > MONEY_MAX:
        raise RepresentativeError(
            "REPRESENTATIVE_DEBT_LIMIT_INVALID",
            "Maximum debt limit is outside the supported range.",
            status_code=422,
        )
    normalized = amount.quantize(MONEY_QUANT)
    if normalized != amount:
        raise RepresentativeError(
            "REPRESENTATIVE_DEBT_LIMIT_PRECISION_INVALID",
            "Maximum debt limit supports at most 3 decimal places.",
            status_code=422,
        )
    return normalized


async def guard_representative_request_identity(
    db: AsyncSession,
    *,
    company_id: int,
    request_id: str,
    operation: str,
) -> str:
    """Serialize Representative command request ids across operation types.

    The project-wide idempotency table is keyed by operation as well as request id.
    Representative lifecycle/reset additionally freezes one request id to one
    Representative operation so a lost-response retry cannot be reinterpreted as
    another lifecycle or credential command.
    """
    if operation not in _REPRESENTATIVE_IDEMPOTENT_OPERATIONS:
        raise ValueError("Unsupported Representative idempotency operation")
    try:
        canonical_request_id = str(UUID(str(request_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RepresentativeError(
            "REPRESENTATIVE_REQUEST_ID_INVALID",
            "Representative request id is invalid.",
            status_code=422,
        ) from exc

    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                int(company_id),
                func.hashtext(f"representative-request:{canonical_request_id}"),
            )
        )
    )
    existing_operations = list(
        (
            await db.execute(
                select(OperationIdempotency.operation)
                .where(
                    OperationIdempotency.company_id == int(company_id),
                    OperationIdempotency.request_id == canonical_request_id,
                    OperationIdempotency.operation.in_(
                        tuple(sorted(_REPRESENTATIVE_IDEMPOTENT_OPERATIONS))
                    ),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if any(str(existing) != operation for existing in existing_operations):
        raise RepresentativeError(
            "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous representative command.",
            status_code=409,
        )
    return canonical_request_id


async def username_exists(
    db: AsyncSession,
    *,
    company_id: int,
    username: str,
    exclude_principal_id: int | None = None,
    exclude_legacy_driver_id: int | None = None,
) -> bool:
    principal_stmt = select(CompanyPrincipal.id).where(
        CompanyPrincipal.company_id == company_id,
        CompanyPrincipal.username == username,
    )
    if exclude_principal_id is not None:
        principal_stmt = principal_stmt.where(CompanyPrincipal.id != exclude_principal_id)
    if await db.scalar(principal_stmt.limit(1)) is not None:
        return True

    # Transitional operational compatibility still requires a company-local Driver
    # username, but Driver is not consulted for tenant or authorization authority.
    legacy_stmt = select(Driver.id).where(
        Driver.company_id == company_id,
        Driver.username == username,
    )
    if exclude_legacy_driver_id is not None:
        legacy_stmt = legacy_stmt.where(Driver.id != exclude_legacy_driver_id)
    return await db.scalar(legacy_stmt.limit(1)) is not None


async def create_representative_persistence(
    db: AsyncSession,
    *,
    company_id: int,
    full_name: str,
    username: str,
    phone_number: str | None,
    password_hash: str,
    can_allow_debt: bool,
    max_debt_limit: Decimal,
):
    """Persist canonical Field identity plus the approved FIELD_ONLY sidecar."""
    principal = CompanyPrincipal(
        company_id=company_id,
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        phone_number=phone_number,
        principal_type=PrincipalType.FIELD_REPRESENTATIVE.value,
        is_active=True,
        auth_revision=1,
    )
    legacy_driver = Driver(
        company_id=company_id,
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        phone_number=phone_number,
        is_active=True,
        can_allow_debt=can_allow_debt,
        max_debt_limit=max_debt_limit,
    )
    db.add(principal)
    db.add(legacy_driver)
    await db.flush()

    profile = FieldRepresentative(
        company_id=company_id,
        principal_id=principal.id,
        principal_type=PrincipalType.FIELD_REPRESENTATIVE.value,
        can_allow_debt=can_allow_debt,
        max_debt_limit=max_debt_limit,
    )
    db.add(profile)
    await db.flush()

    bridge = IdentityLegacyDriverMap(
        company_id=company_id,
        legacy_driver_id=legacy_driver.id,
        classification="FIELD_ONLY",
        backoffice_principal_id=None,
        backoffice_user_id=None,
        field_principal_id=principal.id,
        field_representative_id=profile.id,
    )
    db.add(bridge)
    await db.flush()
    try:
        await assign_new_representative_default(db, company_id, int(profile.id))
    except FieldRoleError as exc:
        raise RepresentativeError(exc.code, "The default FIELD role is unavailable.",
                                  status_code=exc.status) from None
    return profile, principal, bridge, legacy_driver


async def load_management_row(
    db: AsyncSession,
    *,
    company_id: int,
    representative_id: int,
    for_update: bool = False,
):
    canonical_statement = (
        select(FieldRepresentative, CompanyPrincipal)
        .join(
            CompanyPrincipal,
            and_(
                CompanyPrincipal.company_id == FieldRepresentative.company_id,
                CompanyPrincipal.id == FieldRepresentative.principal_id,
                CompanyPrincipal.principal_type == PrincipalType.FIELD_REPRESENTATIVE.value,
            ),
        )
        .where(
            FieldRepresentative.company_id == company_id,
            FieldRepresentative.id == representative_id,
            FieldRepresentative.principal_type == PrincipalType.FIELD_REPRESENTATIVE.value,
        )
    )
    if for_update:
        canonical_statement = canonical_statement.with_for_update(
            of=(FieldRepresentative, CompanyPrincipal)
        )
    canonical_row = (await db.execute(canonical_statement)).one_or_none()
    if canonical_row is None:
        raise RepresentativeError(
            "REPRESENTATIVE_NOT_FOUND",
            "Representative was not found.",
            status_code=404,
        )
    profile, principal = canonical_row
    if (
        profile.company_id != company_id
        or principal.company_id != company_id
        or profile.principal_id != principal.id
    ):
        raise RepresentativeError(
            "REPRESENTATIVE_IDENTITY_INCONSISTENT",
            "Representative identity is inconsistent.",
            status_code=409,
        )

    compatibility_statement = (
        select(IdentityLegacyDriverMap, Driver)
        .join(
            Driver,
            and_(
                Driver.company_id == IdentityLegacyDriverMap.company_id,
                Driver.id == IdentityLegacyDriverMap.legacy_driver_id,
            ),
        )
        .where(
            IdentityLegacyDriverMap.company_id == company_id,
            IdentityLegacyDriverMap.field_principal_id == principal.id,
            IdentityLegacyDriverMap.field_representative_id == profile.id,
        )
    )
    if for_update:
        compatibility_statement = compatibility_statement.with_for_update(
            of=(IdentityLegacyDriverMap, Driver)
        )
    compatibility_row = (await db.execute(compatibility_statement)).one_or_none()
    bridge = compatibility_row[0] if compatibility_row is not None else None
    legacy_driver = compatibility_row[1] if compatibility_row is not None else None
    return profile, principal, bridge, legacy_driver


async def require_operational_compatibility(
    db: AsyncSession,
    *,
    company_id: int,
    representative_id: int,
):
    profile, principal, bridge, legacy_driver = await load_management_row(
        db,
        company_id=company_id,
        representative_id=representative_id,
        for_update=True,
    )
    if (
        bridge is None
        or legacy_driver is None
        or bridge.classification != "FIELD_ONLY"
        or bridge.company_id != company_id
        or bridge.field_principal_id != principal.id
        or bridge.field_representative_id != profile.id
        or bridge.legacy_driver_id != legacy_driver.id
        or legacy_driver.company_id != company_id
    ):
        raise RepresentativeError(
            "REPRESENTATIVE_OPERATIONAL_COMPATIBILITY_MISSING",
            "Representative operational compatibility is incomplete.",
            status_code=409,
        )
    return profile, principal, bridge, legacy_driver


def apply_representative_fields(
    *,
    profile: FieldRepresentative,
    principal: CompanyPrincipal,
    legacy_driver: Driver,
    fields: dict[str, object],
) -> None:
    """Synchronize approved mutable master fields across canonical and sidecar rows."""
    for field in ("full_name", "username", "phone_number"):
        if field in fields:
            setattr(principal, field, fields[field])
            setattr(legacy_driver, field, fields[field])
    for field in ("can_allow_debt", "max_debt_limit"):
        if field in fields:
            setattr(profile, field, fields[field])
            setattr(legacy_driver, field, fields[field])


def add_representative_audit(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    representative_id: int,
    action: str,
    before: dict | None,
    after: dict,
) -> None:
    """Persist secret-free representative master audit evidence."""
    db.add(
        SystemAuditLog(
            company_id=company_id,
            admin_id=actor_id,
            target_id=f"FieldRepresentative_{representative_id}",
            action_type=action,
            old_value=(
                json.dumps(before, sort_keys=True, ensure_ascii=False)
                if before is not None
                else None
            ),
            new_value=json.dumps(after, sort_keys=True, ensure_ascii=False),
        )
    )


__all__ = [
    "add_representative_audit",
    "apply_representative_fields",
    "create_representative_persistence",
    "guard_representative_request_identity",
    "load_management_row",
    "normalize_debt_limit",
    "require_operational_compatibility",
    "username_exists",
]
