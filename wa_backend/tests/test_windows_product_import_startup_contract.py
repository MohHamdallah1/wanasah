from __future__ import annotations

import configparser
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.engine import make_url

from config import Config
from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


BACKEND = Path(__file__).resolve().parents[1]


class ProductImportWindowsDsnTests(unittest.TestCase):
    def test_windows_localhost_is_canonicalized_to_numeric_loopback(self) -> None:
        with (
            patch.object(sys, "platform", "win32"),
            patch.object(
                Config,
                "SQLALCHEMY_DATABASE_URI",
                "postgresql+asyncpg://user:pass@localhost:5432/example",
            ),
        ):
            resolved = make_url(product_import_psycopg_dsn())

        self.assertEqual(resolved.drivername, "postgresql")
        self.assertEqual(resolved.host, "127.0.0.1")
        self.assertEqual(resolved.database, "example")

    def test_windows_non_localhost_host_is_preserved(self) -> None:
        with (
            patch.object(sys, "platform", "win32"),
            patch.object(
                Config,
                "SQLALCHEMY_DATABASE_URI",
                "postgresql+asyncpg://user:pass@db.internal:5432/example",
            ),
        ):
            resolved = make_url(product_import_psycopg_dsn())

        self.assertEqual(resolved.host, "db.internal")


class ProcessOwnershipContractTests(unittest.TestCase):
    def test_web_api_does_not_open_product_import_connector_pool(self) -> None:
        main_source = (BACKEND / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("product_import_app.open_async()", main_source)
        self.assertNotIn(
            "from domains.simple_products.imports.infrastructure.queue import app as product_import_app",
            main_source,
        )
        self.assertIn("product_import_event_relay.start()", main_source)
        self.assertIn("worker_event_relay.start()", main_source)

    def test_http_mutations_defer_on_explicit_psycopg_connections(self) -> None:
        queue_source = (
            BACKEND / "domains/simple_products/imports/infrastructure/queue.py"
        ).read_text(encoding="utf-8")
        correction_source = (
            BACKEND / "domains/simple_products/imports/infrastructure/correction_repository.py"
        ).read_text(encoding="utf-8")

        self.assertIn("connection=conn", queue_source)
        self.assertIn("async with await psycopg.AsyncConnection.connect", queue_source)
        self.assertIn("defer_import_on_connection(", correction_source)
        self.assertIn(
            "async with await psycopg.AsyncConnection.connect", correction_source
        )

    def test_alembic_has_no_real_database_fallback(self) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(BACKEND / "alembic.ini", encoding="utf-8")
        self.assertEqual(parser.get("alembic", "sqlalchemy.url").strip(), "")

        env_source = (BACKEND / "alembic/env.py").read_text(encoding="utf-8")
        self.assertIn("DATABASE_URL_MIGRATION", env_source)
        self.assertIn("DATABASE_URL", env_source)
        self.assertIn("no alembic.ini database fallback is permitted", env_source)

    def test_runtime_dependencies_are_explicitly_pinned(self) -> None:
        requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("psycopg-pool==3.2.8", requirements)
        self.assertIn("alembic==1.18.4", requirements)


if __name__ == "__main__":
    unittest.main()
