from __future__ import annotations

import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from .credentials import fingerprint_initial_password, hash_initial_password
from .queries import get_representative, representative_payload
from .repository import (
    add_representative_audit,
    apply_representative_fields,
    create_representative_persistence,
    guard_representative_request_identity,
    normalize_debt_limit,
    require_operational_compatibility,
    username_exists,
)


_MUTABLE_FIELDS = frozenset(
    {"full_name", "username", "phone_number", "can_allow_debt", "max_debt_limit"}
)


def _stable_hash(operation: str, payload: dict) -> str:
    canonical = json.dumps(
        {"operation": operation, **payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _create_request_hash(
    command: CreateRepresentativeCommand,
    *,
    normalized_debt_limit,
) -> str:
    return _stable_hash(
        "REPRESENTATIVE_CREATE",
        {
            "full_name": command.full_name,
            "username": command.username,
            "phone_number": command.phone_number,
            "password_fingerprint": fingerprint_initial_password(command.password),
            "can_allow_debt": command.can_allow_debt,
            "max_debt_limit": format(normalized_debt_limit, ".3f"),
        },
    )


def _update_request_hash(
    representative_id: int,
    fields: dict[str, object],
) -> str:
    return _stable_hash(
        "REPRESENTATIVE_UPDATE",
        {"representative_id": representative_id, "fields": fields},
    )


def _validated_update_fields(command: UpdateRepresentativeCommand) -> dict[str, object]:
    fields = dict(command.fields)
    if not fields:
        raise RepresentativeError(
            "REPRESENTATIVE_UPDATE_EMPTY",
            "At least one mutable representative field is required.",
            status_code=422,
        )
    unknown = set(fields) - _MUTABLE_FIELDS
    if unknown:
        raise RepresentativeError(
            "REPRESENTATIVE_UPDATE_FIELD_INVALID",
            "Representative update contains an unsupported field.",
            status_code=422,
        )
    if "max_debt_limit" in fields:
        fields["max_debt_limit"] = normalize_debt_limit(fields["max_debt_limit"])
    return fields


async def create_representative(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    command: CreateRepresentativeCommand,
) -> dict:
    debt_limit = normalize_debt_limit(command.max_debt_limit)
    request_hash = _create_request_hash(
        command,
        normalized_debt_limit=debt_limit,
    )
    try:
        canonical_request_id = await guard_representative_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation="REPRESENTATIVE_CREATE",
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="REPRESENTATIVE_CREATE",
            request_id=canonical_request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        if await username_exists(
            db,
            company_id=company_id,
            username=command.username,
        ):
            raise RepresentativeError(
                "REPRESENTATIVE_USERNAME_CONFLICT",
                "Username is already in use in this company.",
                status_code=409,
            )

        password_hash = await hash_initial_password(command.password)
        profile, _principal, _bridge, _legacy_driver = (
            await create_representative_persistence(
                db,
                company_id=company_id,
                full_name=command.full_name,
                username=command.username,
                phone_number=command.phone_number,
                password_hash=password_hash,
                can_allow_debt=command.can_allow_debt,
                max_debt_limit=debt_limit,
            )
        )
        payload = representative_payload(
            await get_representative(
                db,
                company_id=company_id,
                representative_id=int(profile.id),
            )
        )
        add_representative_audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            representative_id=int(profile.id),
            action="REPRESENTATIVE_CREATED",
            before=None,
            after=payload,
        )
        complete_idempotent_operation(idem, payload)
        await db.commit()
        return payload
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
    fields = _validated_update_fields(command)
    request_hash = _update_request_hash(representative_id, fields)
    try:
        canonical_request_id = await guard_representative_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation="REPRESENTATIVE_UPDATE",
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="REPRESENTATIVE_UPDATE",
            request_id=canonical_request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        profile, principal, _bridge, legacy_driver = (
            await require_operational_compatibility(
                db,
                company_id=company_id,
                representative_id=representative_id,
            )
        )
        before = representative_payload(
            await get_representative(
                db,
                company_id=company_id,
                representative_id=representative_id,
            )
        )

        if "username" in fields and fields["username"] != principal.username:
            if await username_exists(
                db,
                company_id=company_id,
                username=str(fields["username"]),
                exclude_principal_id=int(principal.id),
                exclude_legacy_driver_id=int(legacy_driver.id),
            ):
                raise RepresentativeError(
                    "REPRESENTATIVE_USERNAME_CONFLICT",
                    "Username is already in use in this company.",
                    status_code=409,
                )

        apply_representative_fields(
            profile=profile,
            principal=principal,
            legacy_driver=legacy_driver,
            fields=fields,
        )
        await db.flush()
        after = representative_payload(
            await get_representative(
                db,
                company_id=company_id,
                representative_id=representative_id,
            )
        )
        if after != before:
            add_representative_audit(
                db,
                company_id=company_id,
                actor_id=actor_id,
                representative_id=representative_id,
                action="REPRESENTATIVE_UPDATED",
                before=before,
                after=after,
            )

        complete_idempotent_operation(idem, after)
        await db.commit()
        return after
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
