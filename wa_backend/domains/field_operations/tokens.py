"""Purpose-bound signed references, never authentication or operator inputs."""
from __future__ import annotations

import jwt
from config import Config
from .contracts import FieldContractError

_ISSUER = "wanasah.field-contracts.v1"


def seal_reference(purpose: str, payload: dict) -> str:
    return jwt.encode(
        {**payload, "iss": _ISSUER, "aud": purpose, "v": 1},
        Config.SECRET_KEY, algorithm="HS256",
    )


def open_reference(purpose: str, token: str) -> dict:
    try:
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ValueError
        value = jwt.decode(
            token, Config.SECRET_KEY, algorithms=["HS256"],
            audience=purpose, issuer=_ISSUER,
            options={"require": ["iss", "aud", "v"]},
        )
        if value["v"] != 1:
            raise ValueError
        return value
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise FieldContractError(
            "FIELD_REFERENCE_INVALID", "The field reference is invalid.",
            status_code=422,
        ) from None


def owner_binding(context, driver_id: int) -> dict:
    # These are independent identities supplied only by canonical dependencies.
    return {
        "company": context.company_id, "principal": context.principal_id,
        "representative": context.representative_id, "driver": driver_id,
    }


def require_binding(value: dict, expected: dict) -> None:
    if any(type(value.get(key)) is not type(item) or value.get(key) != item
           for key, item in expected.items()):
        raise FieldContractError(
            "FIELD_REFERENCE_SCOPE_MISMATCH",
            "The field reference does not belong to this operation.",
            status_code=403,
        )
