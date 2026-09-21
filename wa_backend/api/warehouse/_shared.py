from sqlalchemy import Integer, any_, bindparam
from sqlalchemy.dialects.postgresql import ARRAY


def _escape_like(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _warehouse_array_membership(column, values, bind_name: str):
    normalized = sorted({int(value) for value in values})
    if not normalized:
        raise ValueError("Warehouse array membership requires values.")
    return column == any_(
        bindparam(
            bind_name,
            value=normalized,
            type_=ARRAY(Integer),
        )
    )

