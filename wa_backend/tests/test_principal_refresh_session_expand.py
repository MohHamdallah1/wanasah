"""Focused model/static/offline-DDL checks for additive refresh persistence."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import Base, RefreshToken
from domains.identity import models as identity_models  # noqa: F401

OLD_TABLES = set(Base.metadata.tables)
LEGACY_DDL = str(CreateTable(RefreshToken.__table__).compile(dialect=postgresql.dialect()))
LEGACY_INDEXES = sorted(str(CreateIndex(i).compile(dialect=postgresql.dialect())) for i in RefreshToken.__table__.indexes)
from domains.auth_sessions.models import PrincipalRefreshToken


class RefreshPersistenceTests(unittest.TestCase):
    def test_only_new_table_and_legacy_signature_preserved(self):
        self.assertEqual(set(Base.metadata.tables) - OLD_TABLES, {"principal_refresh_tokens"})
        self.assertEqual(str(CreateTable(RefreshToken.__table__).compile(dialect=postgresql.dialect())), LEGACY_DDL)
        self.assertEqual(sorted(str(CreateIndex(i).compile(dialect=postgresql.dialect())) for i in RefreshToken.__table__.indexes), LEGACY_INDEXES)

    def test_required_fields_and_exact_legacy_storage(self):
        table = PrincipalRefreshToken.__table__
        self.assertEqual(list(table.c.keys()), ["id", "company_id", "principal_id", "channel", "token", "expires_at",
                                               "is_revoked", "replaced_by_id", "auth_revision", "created_at"])
        self.assertEqual(table.c.token.type.length, RefreshToken.__table__.c.token.type.length)
        self.assertEqual(str(table.c.token.type), "VARCHAR(500)")
        self.assertEqual([c.name for c in table.c if c.nullable], ["replaced_by_id"])
        self.assertIsNone(table.c.auth_revision.default)
        self.assertTrue(table.c.id.autoincrement)

    def test_tenant_principal_and_successor_keys(self):
        fks = {str(fk.name): fk for fk in PrincipalRefreshToken.__table__.foreign_key_constraints}
        self.assertEqual(len(fks), 2)
        principal = fks["fk_principal_refresh_tokens_tenant_principal"]
        successor = fks["fk_principal_refresh_tokens_session_successor"]
        self.assertEqual(list(principal.column_keys), ["company_id", "principal_id"])
        self.assertEqual(list(successor.column_keys), ["company_id", "principal_id", "channel", "replaced_by_id"])
        self.assertEqual(successor.ondelete, "SET NULL (replaced_by_id)")
        self.assertEqual(successor.onupdate, "RESTRICT")

    def test_uniqueness_and_lookup_indexes(self):
        table = PrincipalRefreshToken.__table__
        from sqlalchemy import UniqueConstraint
        unique = {tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)}
        self.assertIn(("token",), unique)
        self.assertIn(("company_id", "principal_id", "channel", "id"), unique)
        indexes = {i.name: i for i in table.indexes}
        self.assertTrue(indexes["uq_principal_refresh_tokens_replaced_by_id"].unique)
        self.assertEqual(list(indexes["ix_principal_refresh_tokens_principal_channel"].columns.keys())[:3], ["company_id", "principal_id", "channel"])
        self.assertEqual(list(indexes["ix_principal_refresh_tokens_tenant_revocation_expiry"].columns.keys())[:3], ["company_id", "is_revoked", "expires_at"])
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        self.assertIn("channel IN ('DASHBOARD', 'FIELD')", ddl)
        self.assertIn("auth_revision > 0", ddl)

    def test_additive_offline_upgrade_and_fail_closed_downgrade(self):
        path = Path(__file__).resolve().parents[1] / "alembic/versions/b7e3f6a1c902_principal_refresh_session_expand.py"
        spec = importlib.util.spec_from_file_location("principal_refresh_revision", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.down_revision, "a4d2e7c9b630")
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context), patch.dict(os.environ, {"DATABASE_URL": "postgresql://restricted@localhost/test"}):
            module.upgrade()
            module.downgrade()
        ddl = output.getvalue()
        self.assertEqual(ddl.count("CREATE TABLE"), 1)
        self.assertIn("AS RESTRICTIVE", ddl)
        self.assertIn("FORCE ROW LEVEL SECURITY", ddl)
        self.assertIn("SET NULL (replaced_by_id)", ddl)
        self.assertIn("LOCK TABLE", ddl)
        self.assertIn("Cannot downgrade populated principal refresh sessions", ddl)
        self.assertNotIn("ALTER TABLE refresh_tokens", ddl)
        self.assertNotIn("UPDATE refresh_tokens", ddl)


if __name__ == "__main__":
    unittest.main()
