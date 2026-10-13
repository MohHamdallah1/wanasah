from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


class RepresentativeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


@dataclass(frozen=True, slots=True)
class RepresentativeRecord:
    representative_id: int
    full_name: str
    username: str
    phone_number: str | None
    is_active: bool
    can_allow_debt: bool
    max_debt_limit: Decimal


@dataclass(frozen=True, slots=True)
class RepresentativePage:
    items: tuple[RepresentativeRecord, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class CreateRepresentativeCommand:
    request_id: str
    full_name: str
    username: str
    password: str = field(repr=False)
    phone_number: str | None
    can_allow_debt: bool
    max_debt_limit: Decimal


@dataclass(frozen=True, slots=True)
class UpdateRepresentativeCommand:
    request_id: str
    fields: dict[str, object]


__all__ = [
    "CreateRepresentativeCommand",
    "RepresentativeError",
    "RepresentativePage",
    "RepresentativeRecord",
    "UpdateRepresentativeCommand",
]
