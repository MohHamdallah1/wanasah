"""Canonical Backoffice authorization; no legacy actor ID is persisted."""
from sqlalchemy import select, text

from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected,
)
from domains.identity.models import BackofficeUser, CompanyPrincipal
from models import Company

from .errors import PurchaseReferenceError


async def require_identity(db, access):
    if not isinstance(access, BackofficeCapabilityAccess) or access.db is not db:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_ACCESS_DENIED", "Access denied.", status_code=403)
    tenant = await db.scalar(text("SELECT current_setting('app.current_tenant', true)"))
    if tenant != str(access.company_id):
        raise PurchaseReferenceError("PURCHASE_REFERENCE_TENANT_CONTEXT", "Tenant context is unavailable.", status_code=403)
    subject = access.subject
    actor = await db.scalar(
        select(BackofficeUser.id)
        .join(CompanyPrincipal, (
            (CompanyPrincipal.company_id == BackofficeUser.company_id)
            & (CompanyPrincipal.id == BackofficeUser.principal_id)
        ))
        .join(Company, Company.id == BackofficeUser.company_id)
        .where(
            BackofficeUser.company_id == access.company_id,
            BackofficeUser.id == subject.backoffice_user_id,
            BackofficeUser.principal_id == subject.principal_id,
            CompanyPrincipal.principal_type == "BACKOFFICE",
            CompanyPrincipal.is_active.is_(True),
            Company.is_active.is_(True),
        )
    )
    if actor is None:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_ACTOR_UNAVAILABLE", "Actor is unavailable.", status_code=403)
    return access.company_id


async def require_access(db, access, capabilities):
    company_id = await require_identity(db, access)
    try:
        await access.require(capabilities)  # company scope: never any_location
    except BackofficeCapabilityAccessRejected as exc:
        raise PurchaseReferenceError(
            "PURCHASE_REFERENCE_ACCESS_DENIED", "Purchase-reference permission is required.",
            status_code=403,
        ) from exc
    return company_id


async def require_receipt_access(db, access, location_id):
    company_id = await require_identity(db, access)
    try:
        await access.require("inbound.create", location_id)
    except BackofficeCapabilityAccessRejected as exc:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_ACCESS_DENIED",
                                     "Receipt permission is required at this warehouse.", status_code=403) from exc
    return company_id
