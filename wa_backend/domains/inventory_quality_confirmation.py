"""Canonical credential confirmation for the Inventory quality workflow."""
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.credential_confirmation import verify_actor_password
from domains.identity.models import BackofficeUser, CompanyPrincipal


async def verify_quality_confirmation(
    db: AsyncSession, access: BackofficeCapabilityAccess, password: str,
) -> bool:
    subject = access.subject
    principal = await db.scalar(
        select(CompanyPrincipal)
        .join(BackofficeUser, and_(
            BackofficeUser.company_id == CompanyPrincipal.company_id,
            BackofficeUser.principal_id == CompanyPrincipal.id,
        ))
        .where(
            CompanyPrincipal.company_id == access.company_id,
            CompanyPrincipal.id == subject.principal_id,
            CompanyPrincipal.principal_type == "BACKOFFICE",
            CompanyPrincipal.is_active.is_(True),
            BackofficeUser.company_id == access.company_id,
            BackofficeUser.id == subject.backoffice_user_id,
            BackofficeUser.principal_type == "BACKOFFICE",
        )
    )
    return principal is not None and await verify_actor_password(principal, password)
