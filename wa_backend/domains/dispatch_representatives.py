"""SQL identity seam for Dispatch's temporary legacy operational driver IDs."""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Exists

from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.types import PrincipalType


def has_canonical_field_identity(
    *, company_id: int, legacy_driver_id: int | ColumnElement[int],
) -> Exists:
    """Compose an exact tenant-safe field identity check in WHERE or SELECT.

    The bridge is only an operational locator. Its populated field IDs must
    match the canonical profile and active field principal. This predicate
    grants no capability and leaves operational state and locks to the caller.
    """
    bridge = IdentityLegacyDriverMap
    representative = FieldRepresentative
    principal = CompanyPrincipal
    field_type = PrincipalType.FIELD_REPRESENTATIVE.value
    return (
        select(bridge.legacy_driver_id)
        .select_from(bridge)
        .join(representative, and_(
            representative.company_id == bridge.company_id,
            representative.id == bridge.field_representative_id,
            representative.principal_id == bridge.field_principal_id,
        ))
        .join(principal, and_(
            principal.company_id == bridge.company_id,
            principal.id == bridge.field_principal_id,
        ))
        .where(
            bridge.company_id == company_id,
            bridge.legacy_driver_id == legacy_driver_id,
            representative.principal_type == field_type,
            principal.principal_type == field_type,
            principal.is_active.is_(True),
        )
        .correlate_except(bridge, representative, principal)
        .exists()
    )


__all__ = ["has_canonical_field_identity"]
