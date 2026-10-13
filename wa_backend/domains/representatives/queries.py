from __future__ import annotations

import base64
import hashlib
import json
from datetime import timezone
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.types import PrincipalType

from .contracts import (
    RepresentativeError,
    RepresentativePage,
    RepresentativeRecord,
    RepresentativeStatusFilter,
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _sort_rank(is_active: bool) -> int:
    return 0 if is_active else 1


def _encode_cursor(record: RepresentativeRecord, *, scope: str) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "representative",
            "scope": _scope_hash(scope),
            "active_rank": _sort_rank(record.is_active),
            "name": record.full_name,
            "id": record.representative_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, expected_scope: str) -> tuple[int, str, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
        )
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "representative"
            or payload.get("scope") != _scope_hash(expected_scope)
        ):
            raise ValueError
        active_rank = payload.get("active_rank")
        name = payload.get("name")
        representative_id = payload.get("id")
        if (
            active_rank not in (0, 1)
            or not isinstance(name, str)
            or type(representative_id) is not int
            or representative_id <= 0
        ):
            raise ValueError
        return active_rank, name, representative_id
    except Exception as exc:
        raise RepresentativeError(
            "REPRESENTATIVE_CURSOR_INVALID",
            "Representative cursor is invalid for the current query.",
            status_code=400,
        ) from exc


def _record(profile: FieldRepresentative, principal: CompanyPrincipal) -> RepresentativeRecord:
    created_at = min(principal.created_at, profile.created_at)
    updated_at = max(principal.updated_at, profile.updated_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return RepresentativeRecord(
        representative_id=int(profile.id),
        full_name=str(principal.full_name),
        username=str(principal.username),
        phone_number=str(principal.phone_number) if principal.phone_number is not None else None,
        is_active=bool(principal.is_active),
        can_allow_debt=bool(profile.can_allow_debt),
        max_debt_limit=Decimal(profile.max_debt_limit),
        created_at=created_at,
        updated_at=updated_at,
    )


def representative_payload(record: RepresentativeRecord) -> dict:
    return {
        "id": record.representative_id,
        "full_name": record.full_name,
        "username": record.username,
        "phone_number": record.phone_number,
        "is_active": record.is_active,
        "can_allow_debt": record.can_allow_debt,
        "max_debt_limit": format(record.max_debt_limit, ".3f"),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


async def list_representatives(
    db: AsyncSession,
    *,
    company_id: int,
    search: str | None,
    status: RepresentativeStatusFilter,
    cursor: str | None,
    limit: int,
) -> RepresentativePage:
    clean_search = (search or "").strip().lower()
    scope = f"representatives|{company_id}|{status}|{clean_search}"
    active_rank = case((CompanyPrincipal.is_active.is_(True), 0), else_=1)
    statement = (
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
            FieldRepresentative.principal_type == PrincipalType.FIELD_REPRESENTATIVE.value,
        )
    )
    if status == "active":
        statement = statement.where(CompanyPrincipal.is_active.is_(True))
    elif status == "inactive":
        statement = statement.where(CompanyPrincipal.is_active.is_(False))
    elif status != "all":
        raise RepresentativeError(
            "REPRESENTATIVE_STATUS_FILTER_INVALID",
            "Representative status filter is invalid.",
            status_code=422,
        )

    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        statement = statement.where(
            or_(
                func.lower(CompanyPrincipal.full_name).like(pattern, escape="\\"),
                func.lower(CompanyPrincipal.username).like(pattern, escape="\\"),
                func.lower(func.coalesce(CompanyPrincipal.phone_number, "")).like(
                    pattern, escape="\\"
                ),
            )
        )

    if cursor:
        cursor_rank, cursor_name, cursor_id = _decode_cursor(
            cursor, expected_scope=scope
        )
        statement = statement.where(
            or_(
                active_rank > cursor_rank,
                and_(active_rank == cursor_rank, CompanyPrincipal.full_name > cursor_name),
                and_(
                    active_rank == cursor_rank,
                    CompanyPrincipal.full_name == cursor_name,
                    FieldRepresentative.id > cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            statement.order_by(
                active_rank.asc(),
                CompanyPrincipal.full_name.asc(),
                FieldRepresentative.id.asc(),
            ).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    records = tuple(_record(profile, principal) for profile, principal in rows[:limit])
    next_cursor = (
        _encode_cursor(records[-1], scope=scope) if has_more and records else None
    )
    return RepresentativePage(records, next_cursor, has_more)


async def get_representative(
    db: AsyncSession,
    *,
    company_id: int,
    representative_id: int,
) -> RepresentativeRecord:
    row = (
        await db.execute(
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
    ).one_or_none()
    if row is None:
        raise RepresentativeError(
            "REPRESENTATIVE_NOT_FOUND",
            "Representative was not found.",
            status_code=404,
        )
    return _record(row[0], row[1])


__all__ = ["get_representative", "list_representatives", "representative_payload"]
