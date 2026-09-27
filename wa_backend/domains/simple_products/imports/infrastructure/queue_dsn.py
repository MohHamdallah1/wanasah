"""Shared PostgreSQL DSN for Product Import infrastructure adapters."""
from __future__ import annotations

from sqlalchemy.engine import make_url

from config import Config


def product_import_psycopg_dsn() -> str:
    url = make_url(
        Config.SQLALCHEMY_DATABASE_URI
    )
    if not url.drivername.startswith(
        "postgresql"
    ):
        raise RuntimeError(
            "Product Import requires PostgreSQL."
        )
    return url.set(
        drivername="postgresql"
    ).render_as_string(
        hide_password=False
    )
