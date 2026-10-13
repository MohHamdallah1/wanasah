"""Shared PostgreSQL DSN for Product Import infrastructure adapters."""
from __future__ import annotations

import sys

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
    # On Windows the psycopg async pool's background AddConnection can hang
    # while resolving localhost even though a direct psycopg connection succeeds.
    # A numeric loopback address removes that resolver ambiguity without changing
    # the selected database, credentials, port, or non-local deployment hosts.
    if (
        sys.platform == "win32"
        and str(url.host or "").lower() == "localhost"
    ):
        url = url.set(host="127.0.0.1")
    return url.set(
        drivername="postgresql"
    ).render_as_string(
        hide_password=False
    )
