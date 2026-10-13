from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.types import PrincipalType
from models import Driver, SystemAuditLog
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)

from .contracts import (
    CreateRepresentativeCommand,
    RepresentativeError,
    UpdateRepresentativeCommand,
)
from .credentials import hash_initial_password
from .queries import get_representative, representative_payload
from .repository import require_operational_compatibility, username_exists


MONEY_MAX = Decimal("999999999.999")
MONEY_QUANT = Decimal("0.001")


def _normalize_debt_limit(value: Decimal) -> Decimal:
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


def _stable_hash(operation: str, payload: dict) -> str:
    canonical = json.dumps(
        {"operation": operation, **payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_create_hash(command: CreateRepresentativeCommand) -> str:
    # Passwords and password-derived values are deliberately excluded from durable
    # idempotency identity, matching the repository's sensitive-confirmation pattern.
    return _stable_hash(
        "REPRESENTATIVE_CREATE",
        {
            "full_name": command.full_name,
            "username": command.username,
            "phone_number": command.phone_number,
            "can_allow_debt": command.can_allow_debt,
            "max_debt_limit": str(command.max_debt_limit),
        },
    )


def _safe_update_hash(
    representative_id: int, command: UpdateRepresentativeCommand
) -> str:
    return _stable_hash(
        "REPRESENTATIVE_UPDATE",
        {"representative_id": representative_id, "fields": command.fields},
    )


def _audit(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    representative_id: int,
    action: str,
    before: dict | None,
    after: dict,
) -> None:
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


async def create_representative(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    command: CreateRepresentativeCommand,
) -> dict:
    debt_limit = _normalize_debt_limit(command.max_debt_limit)
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="REPRESENTATIVE_CREATE",
            request_id=command.request_id,
            request_hash=_safe_create_hash(command),
        )
        if replay is not None:
            await db.rollback()
            return replay

        if await username_exists(
            db, company_id=company_id, username=command.username
        ):
            raise RepresentativeError(
                "REPRESENTATIVE_USERNAME_CONFLICT",
                "Username is already in use in this company.",
                status_code=409,
            )

        password_hash = await hash_initial_password(command.password)
        principal = CompanyPrincipal(
            company_id=company_id,
            username=command.username,
            password_hash=password_hash,
            full_name=command.full_name,
            phone_number=command.phone_number,
            principal_type=PrincipalType.FIELD_REPRESENTATIVE.value,
            is_active=True,
            auth_revision=1,
        )
        legacy_driver = Driver(
            company_id=company_id,
            username=command.username,
            password_hash=password_hash,
            full_name=command.full_name,
            phone_number=command.phone_number,
            is_active=True,
            can_allow_debt=command.can_allow_debt,
            max_debt_limit=debt_limit,
        )
        db.add(principal)
        db.add(legacy_driver)
        await db.flush()

        profile = FieldRepresentative(
            company_id=company_id,
            principal_id=principal.id,
            principal_type=PrincipalType.FIELD_REPRESENTATIVE.value,
            can_allow_debt=command.can_allow_debt,
            max_debt_limit=debt_limit,
        )
        db.add(profile)
        await db.flush()

        db.add(
            IdentityLegacyDriverMap(
                company_id=company_id,
                legacy_driver_id=legacy_driver.id,
                classification="FIELD_ONLY",
                backoffice_principal_id=None,
                backoffice_user_id=None,
                field_principal_id=principal.id,
                field_representative_id=profile.id,
            )
        )
        await db.flush()

        record = await get_representative(
            db, company_id=company_id, representative_id=profile.id
        )
        payload = representative_payload(record)
        _audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            representative_id=profile.id,
            action="REPRESENTATIVE_CREATED",
            before=None,
            after=payload,
        )
        response = {
            "message": "Representative created successfully.",
            "representative": payload,
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except RepresentativeError:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise RepresentativeError(
            "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous representative command.",
            status_code=409,
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise RepresentativeError(
            "REPRESENTATIVE_CREATE_CONFLICT",
            "Representative could not be created because of a concurrent conflict.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


async def update_representative(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    representative_id: int,
    command: UpdateRepresentativeCommand,
) -> dict:
    fields = dict(command.fields)
    if "max_debt_limit" in fields:
        fields["max_debt_limit"] = _normalize_debt_limit(fields["max_debt_limit"])
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="REPRESENTATIVE_UPDATE",
            request_id=command.request_id,
            request_hash=_safe_update_hash(
                representative_id,
                UpdateRepresentativeCommand(command.request_id, fields),
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        profile, principal, _bridge, legacy_driver = await require_operational_compatibility(
            db,
            company_id=company_id,
            representative_id=representative_id,
        )
        before = representative_payload(
            await get_representative(
                db, company_id=company_id, representative_id=representative_id
            )
        )

        if "username" in fields and fields["username"] != principal.username:
            if await username_exists(
                db,
                company_id=company_id,
                username=str(fields["username"]),
                exclude_principal_id=principal.id,
                exclude_legacy_driver_id=legacy_driver.id,
            ):
                raise RepresentativeError(
                    "REPRESENTATIVE_USERNAME_CONFLICT",
                    "Username is already in use in this company.",
                    status_code=409,
                )

        for field in ("full_name", "username", "phone_number"):
            if field in fields:
                setattr(principal, field, fields[field])
                setattr(legacy_driver, field, fields[field])
        for field in ("can_allow_debt", "max_debt_limit"):
            if field in fields:
                setattr(profile, field, fields[field])
                setattr(legacy_driver, field, fields[field])

        await db.flush()
        after = representative_payload(
            await get_representative(
                db, company_id=company_id, representative_id=representative_id
            )
        )
        if after != before:
            _audit(
                db,
                company_id=company_id,
                actor_id=actor_id,
                representative_id=representative_id,
                action="REPRESENTATIVE_UPDATED",
                before=before,
                after=after,
            )
        response = {
            "message": "Representative updated successfully.",
            "representative": after,
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except RepresentativeError:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise RepresentativeError(
            "REPRESENTATIVE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous representative command.",
            status_code=409,
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise RepresentativeError(
            "REPRESENTATIVE_UPDATE_CONFLICT",
            "Representative could not be updated because of a concurrent conflict.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


__all__ = ["create_representative", "update_representative"]
