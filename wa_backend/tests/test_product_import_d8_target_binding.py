"""Target-binding gate: no DB, migrations, workers, or network."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.audit_product_import_d8_readonly import (
    _bind_env_file_db_target,
)

MIGRATION = "postgresql://migration:synthetic@staging.invalid/w_stage"
RUNTIME = "postgresql://runtime:synthetic@staging.invalid/w_stage"


class ExplicitTargetBindingTests(unittest.TestCase):
    def check(self, values: dict[str, str], env: dict[str, str],
              scope: str = "staging") -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "staging.env"
            path.write_text(
                "".join(f"{key}={value}\n" for key, value in values.items()),
                encoding="utf-8",
            )
            with patch.dict(os.environ, env, clear=True):
                _bind_env_file_db_target(path, scope=scope)

    def test_exact_file_target_and_inherited_target_match(self) -> None:
        values = {
            "DATABASE_URL_MIGRATION": MIGRATION,
            "DATABASE_URL": RUNTIME,
        }
        self.check(values, {})
        self.check(values, values)

    def test_conflicting_migration_or_runtime_target_is_denied(self) -> None:
        values = {
            "DATABASE_URL_MIGRATION": MIGRATION,
            "DATABASE_URL": RUNTIME,
        }
        for key in values:
            inherited = dict(values)
            inherited[key] = "postgresql://wrong:secret@other.invalid/production"
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, "conflicts") as ctx:
                    self.check(values, inherited)
                self.assertNotIn("secret", str(ctx.exception))
                self.assertNotIn("production", str(ctx.exception))

    def test_staging_requires_both_db_urls(self) -> None:
        for values in ({}, {"DATABASE_URL_MIGRATION": MIGRATION},
                       {"DATABASE_URL": RUNTIME}):
            with self.subTest(values=tuple(values)):
                with self.assertRaisesRegex(RuntimeError, "must explicitly declare"):
                    self.check(values, {})

    def test_interpolated_db_target_is_denied(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "literal URL"):
            self.check(
                {"DATABASE_URL_MIGRATION": "${INHERITED_MIGRATION}",
                 "DATABASE_URL": RUNTIME},
                {},
            )

    def test_migration_and_runtime_cannot_point_to_different_db(self) -> None:
        for runtime in (
            "postgresql://runtime:secret@other.invalid/w_stage",
            "postgresql://runtime:secret@staging.invalid/production",
            "postgresql://runtime:secret@staging.invalid:5444/w_stage",
        ):
            with self.subTest(target=runtime.split("@")[-1]):
                with self.assertRaisesRegex(RuntimeError, "targets disagree"):
                    self.check({
                        "DATABASE_URL_MIGRATION": MIGRATION,
                        "DATABASE_URL": runtime,
                    }, {})

    def test_explicit_compatible_driver_and_port_are_accepted(self) -> None:
        self.check({
            "DATABASE_URL_MIGRATION":
                "postgresql+psycopg://migration:one@staging.invalid:5432/w_stage",
            "DATABASE_URL":
                "postgresql+asyncpg://runtime:two@staging.invalid/w_stage",
        }, {})

    def test_malformed_urls_do_not_expose_credentials(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must identify") as ctx:
            self.check({
                "DATABASE_URL_MIGRATION": MIGRATION,
                "DATABASE_URL": "not-a-url-with-password-secret",
            }, {})
        self.assertNotIn("password-secret", str(ctx.exception))

    def test_developer_only_checks_targets_present_in_file(self) -> None:
        self.check({}, {}, scope="developer")
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            self.check({"DATABASE_URL_MIGRATION": MIGRATION},
                       {"DATABASE_URL_MIGRATION": RUNTIME}, scope="developer")


if __name__ == "__main__":
    unittest.main()
