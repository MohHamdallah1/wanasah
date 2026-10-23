"""Owner-only audited FIELD assignments using the existing durable command authority."""
import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from models import Role, SystemAuditLog
from services import InventoryMutationError, begin_idempotent_operation, complete_idempotent_operation
from domains.representatives.repository import guard_representative_request_identity
from domains.representatives.contracts import RepresentativeError
from .field_models import FieldRepresentativeRole
from .field_role_policy import FieldRoleError, require_field_safe, role_codes
from .field_role_targets import require_owner, require_representative, require_role


@dataclass(frozen=True)
class FieldRoleCommand:
    request_id: str
    representative_id: int
    role_id: int
    grant: bool


async def list_field_roles(db, access, representative_id: int, after_id: int, limit: int):
    await require_owner(db, access)
    await require_representative(db, access.company_id, representative_id)
    rows = (await db.execute(select(Role.id, Role.name, Role.system_key)
        .join(FieldRepresentativeRole, (FieldRepresentativeRole.company_id == Role.company_id)
              & (FieldRepresentativeRole.role_id == Role.id))
        .where(Role.company_id == access.company_id,
               FieldRepresentativeRole.field_representative_id == representative_id,
               Role.id > after_id).order_by(Role.id).limit(limit + 1))).all()
    page = rows[:limit]
    return {"items":[{"role_id":r.id,"name":r.name,"system_key":r.system_key} for r in page],
            "next_id": page[-1].id if len(rows) > limit else None}


async def change_field_role(db, access, actor_id: int, command: FieldRoleCommand):
    company_id = access.company_id
    operation = "REPRESENTATIVE_FIELD_ROLE_" + ("GRANT" if command.grant else "REVOKE")
    body = {"representative_id":command.representative_id,"role_id":command.role_id,"grant":command.grant}
    fingerprint = hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    try:
        await require_owner(db, access)
        await require_representative(db, company_id, command.representative_id)
        await require_role(db, company_id, command.role_id)
        request_id = await guard_representative_request_identity(db, company_id=company_id,
            request_id=command.request_id, operation=operation)
        idem, replay = await begin_idempotent_operation(db, company_id=company_id, actor_id=actor_id,
            operation=operation, request_id=request_id, request_hash=fingerprint)
        if replay is not None:
            await db.rollback()
            return replay
        await require_representative(db, company_id, command.representative_id, lock=True)
        await require_role(db, company_id, command.role_id, lock=True)
        if command.grant:
            require_field_safe(await role_codes(db, company_id, command.role_id))
            changed = (await db.execute(insert(FieldRepresentativeRole).values(
                company_id=company_id,field_representative_id=command.representative_id,role_id=command.role_id
            ).on_conflict_do_nothing().returning(FieldRepresentativeRole.role_id))).scalar_one_or_none() is not None
        else:
            changed = (await db.execute(delete(FieldRepresentativeRole).where(
                FieldRepresentativeRole.company_id == company_id,
                FieldRepresentativeRole.field_representative_id == command.representative_id,
                FieldRepresentativeRole.role_id == command.role_id
            ).returning(FieldRepresentativeRole.role_id))).scalar_one_or_none() is not None
        result = {**body, "changed":changed}
        if changed:
            db.add(SystemAuditLog(company_id=company_id,admin_id=actor_id,
                target_id="FieldRepresentative_" + str(command.representative_id),
                action_type=operation,
                old_value=json.dumps({"assigned":not command.grant}),
                new_value=json.dumps({**body,"request_id":request_id,
                    "owner_principal_id":access.subject.principal_id,
                    "owner_backoffice_user_id":access.subject.backoffice_user_id},sort_keys=True)))
        complete_idempotent_operation(idem, result)
        await db.commit()
        return result
    except (InventoryMutationError, RepresentativeError):
        await db.rollback()
        raise FieldRoleError("FIELD_ROLE_REQUEST_CONFLICT") from None
    except DBAPIError as exc:
        await db.rollback()
        state = getattr(exc.orig, "sqlstate", None)
        if state in {"40001","40P01","23503","23505","23514","42501"}:
            raise FieldRoleError("FIELD_ROLE_CONCURRENT_CONFLICT") from None
        raise
    except Exception:
        await db.rollback()
        raise
